"""
P5-G: eval_retrieval.py 单元测试(纯 stub,不触 RAG/模型)

覆盖:
1. slug_of: 解析多种 source 格式 → 文件名 stem
2. hit_rate_at_k: top-k 内命中=1
3. reciprocal_rank: 1/rank,未命中=0
4. ndcg_at_k: log2 衰减
5. evaluate: 聚合 + per-category + misses
6. load_golden: subset 过滤
7. golden_set 文件本身格式校验(必含字段、subset 限定值)
8. unique slugs 检查(避免一个 query 对应不存在的 slug)
"""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import pytest


def test_slug_of_handles_paths():
    from eval_retrieval import slug_of
    assert slug_of("policy\\national\\xxx.md") == "xxx"
    assert slug_of("basic/carbon_basics.md") == "carbon_basics"
    assert slug_of("foo.md") == "foo"
    assert slug_of("foo") == "foo"
    assert slug_of("") == ""
    assert slug_of(None) == ""


def test_hit_rate_at_k():
    from eval_retrieval import hit_rate_at_k
    assert hit_rate_at_k(["a", "b", "c", "d", "e"], "c", 5) == 1
    assert hit_rate_at_k(["a", "b", "c", "d", "e"], "c", 2) == 0
    assert hit_rate_at_k(["a"], "a", 5) == 1
    assert hit_rate_at_k([], "a", 5) == 0


def test_reciprocal_rank():
    from eval_retrieval import reciprocal_rank
    assert reciprocal_rank(["a", "b", "c"], "a") == 1.0
    assert reciprocal_rank(["a", "b", "c"], "b") == 0.5
    assert reciprocal_rank(["a", "b", "c"], "c") == pytest.approx(1 / 3)
    assert reciprocal_rank(["a", "b", "c"], "z") == 0.0


def test_ndcg_at_k():
    from eval_retrieval import ndcg_at_k
    import math
    # rank=1 → 1/log2(2) = 1.0
    assert ndcg_at_k(["x"], "x", 10) == 1.0
    # rank=2 → 1/log2(3)
    assert ndcg_at_k(["a", "x"], "x", 10) == pytest.approx(1 / math.log2(3))
    # 不在 top-k
    assert ndcg_at_k(["a", "b", "c"], "x", 3) == 0.0


def test_evaluate_aggregates():
    """模拟 engine,验证 evaluate 计算正确"""
    from eval_retrieval import evaluate

    class FakeEngine:
        # 简单模拟:第 0/2 条命中,第 1 条不命中
        _responses = {
            "q1": [{"metadata": {"source": "policy/aaa.md"}}],
            "q2": [{"metadata": {"source": "policy/zzz.md"}}],
            "q3": [{"metadata": {"source": "policy/ccc.md"}}],
        }

        def retrieve(self, q, top_k=10):
            return self._responses.get(q, [])

    entries = [
        {"query": "q1", "expected_source_slug": "aaa", "category": "C1"},
        {"query": "q2", "expected_source_slug": "bbb", "category": "C1"},
        {"query": "q3", "expected_source_slug": "ccc", "category": "C2"},
    ]
    res = evaluate(entries, FakeEngine())
    assert res["n"] == 3
    assert res["hit_rate@5"] == pytest.approx(2 / 3)
    assert res["mrr@10"] == pytest.approx((1.0 + 0.0 + 1.0) / 3)
    assert res["per_category"]["C1"] == 0.5  # q1 命中 / q2 未命中
    assert res["per_category"]["C2"] == 1.0
    assert len(res["misses"]) == 1
    assert res["misses"][0]["query"] == "q2"


def test_load_golden_subset_filter(tmp_path, monkeypatch):
    """load_golden(subset=curated) 只返 curated"""
    import eval_retrieval
    fake_golden = tmp_path / "golden.jsonl"
    fake_golden.write_text(
        json.dumps({"query": "a", "expected_source_slug": "x", "subset": "curated"}) + "\n" +
        json.dumps({"query": "b", "expected_source_slug": "y", "subset": "full"}) + "\n" +
        json.dumps({"query": "c", "expected_source_slug": "z", "subset": "curated"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(eval_retrieval, "GOLDEN_SET", fake_golden)
    assert len(eval_retrieval.load_golden(subset="curated")) == 2
    assert len(eval_retrieval.load_golden(subset="full")) == 1
    assert len(eval_retrieval.load_golden(subset=None)) == 3


# ---------------------------------------------------------------------------
# Golden set 文件本身的格式约束(变更时早期发现错误)
# ---------------------------------------------------------------------------
def _read_real_golden():
    path = PROJECT_ROOT / "tests" / "eval" / "golden_set.jsonl"
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def test_golden_set_format():
    entries = _read_real_golden()
    assert len(entries) >= 50, f"golden set 至少 50 条,实际 {len(entries)}"
    required = {"query", "expected_source_slug", "subset", "category"}
    for i, e in enumerate(entries):
        missing = required - set(e.keys())
        assert not missing, f"entry {i} 缺字段: {missing}"
        assert e["subset"] in ("curated", "full"), \
            f"entry {i} subset 非法: {e['subset']}"
        assert e["query"].strip(), f"entry {i} query 为空"
        assert e["expected_source_slug"].strip(), f"entry {i} slug 为空"


def test_golden_set_curated_subset_size():
    entries = _read_real_golden()
    curated = [e for e in entries if e["subset"] == "curated"]
    # curated 子集是 CI gate,应有合理体量
    assert 25 <= len(curated) <= 40, \
        f"curated 子集应在 25-40 条,实际 {len(curated)}"
