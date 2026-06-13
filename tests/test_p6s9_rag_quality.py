"""
P6.S.9 测试: RAG 检索质量 — 后置 score>=0.5 过滤 + top-20→rerank→top-5

验证:
1. 无关 query 应被后置过滤掉
2. 有关 query 全部 score>=0.5
3. initial_fetch_multiplier=4 真的拉了 20 个候选
4. top_k 截断生效
5. rerank 被调用
6. min_similarity 预过滤 + 后置过滤 二段式一致
"""
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


@dataclass
class FakeResult:
    id: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    score: float = 0.0

    def get_summary(self):
        return self.content[:100]


class MockRetriever:
    """Mock retriever — 可配置返回结果集,验证 engine 行为"""
    def __init__(self, results, reranker=None):
        self._results = results
        self.reranker = reranker
        self.calls = []

    def retrieve(self, query, top_k=5, filter_metadata=None, min_score=0.0):
        self.calls.append({"query": query, "top_k": top_k, "min_score": min_score})
        return self._results[:top_k]


class MockReranker:
    def __init__(self):
        self.calls = []

    def rerank(self, query, results):
        self.calls.append({"query": query, "count": len(results)})
        # 倒序(模拟按 score 倒序)
        return sorted(results, key=lambda r: r.score, reverse=True)


def _make_engine_with_mock(mock_retriever, post_filter_threshold=0.1, initial_fetch_multiplier=4):
    """构造一个挂上 mock retriever 的 RAGEngine"""
    from rag.rag_engine import RAGEngine, RAGConfig

    engine = RAGEngine.__new__(RAGEngine)
    engine.config = RAGConfig(
        enabled=True,
        min_similarity=0.05,
        post_filter_threshold=post_filter_threshold,
        initial_fetch_multiplier=initial_fetch_multiplier,
        default_top_k=5,
    )
    engine._retriever = mock_retriever
    engine._initialized = True
    engine.stats = {
        "total_queries": 0,
        "avg_query_time_ms": 0.0,
    }
    return engine


def test_post_filter_drops_low_score():
    """score < 0.1 的无关结果应被过滤掉"""
    retriever = MockRetriever([
        FakeResult(id="1", content="碳中和定义", score=0.85),
        FakeResult(id="2", content="不相关文档", score=0.04),  # 0.04 噪声
        FakeResult(id="3", content="低碳生活", score=0.72),
        FakeResult(id="4", content="更不相关", score=0.08),  # 也过滤
    ])
    engine = _make_engine_with_mock(retriever, post_filter_threshold=0.1)

    results = engine.retrieve("碳中和", top_k=5)

    assert len(results) == 2, f"应只剩 2 个 ≥0.1, 实际 {len(results)}"
    assert all(r.score >= 0.1 for r in results)
    assert {r.id for r in results} == {"1", "3"}
    print("✅ test_post_filter_drops_low_score PASSED")


def test_unrelated_query_returns_empty():
    """完全无关的 query 应被过滤为空"""
    retriever = MockRetriever([
        FakeResult(id="1", content="碳中和", score=0.08),  # 临界, 应被过滤
        FakeResult(id="2", content="低碳", score=0.07),
        FakeResult(id="3", content="出行", score=0.06),
    ])
    engine = _make_engine_with_mock(retriever, post_filter_threshold=0.1)

    results = engine.retrieve("你是什么模型", top_k=5)

    assert len(results) == 0, f"无关 query 应被全部过滤, 实际 {len(results)} 个"
    print("✅ test_unrelated_query_returns_empty PASSED")


def test_initial_fetch_multiplier_4():
    """retriever 应被请求 top_k * 4 = 20 个候选"""
    retriever = MockRetriever([])
    engine = _make_engine_with_mock(retriever, initial_fetch_multiplier=4)

    engine.retrieve("碳中和", top_k=5)
    assert retriever.calls[0]["top_k"] == 20, f"应请求 20 个, 实际 {retriever.calls[0]['top_k']}"
    print("✅ test_initial_fetch_multiplier_4 PASSED")


def test_top_k_truncation():
    """20 个候选通过过滤后应截断到 top_k=5"""
    # 20 个全部 ≥0.1 → 应只返 5 个
    candidates = [FakeResult(id=f"r{i}", content=f"result {i}", score=0.9 - i*0.01) for i in range(20)]
    retriever = MockRetriever(candidates)
    engine = _make_engine_with_mock(retriever, post_filter_threshold=0.1)

    results = engine.retrieve("test", top_k=5)
    assert len(results) == 5, f"应截断到 5, 实际 {len(results)}"
    assert results[0].score >= results[-1].score, "应保持分数降序"
    print("✅ test_top_k_truncation PASSED")


def test_reranker_is_called():
    """若 retriever 配了 reranker,应被调用"""
    reranker = MockReranker()
    retriever = MockRetriever([
        FakeResult(id="1", content="a", score=0.6),
        FakeResult(id="2", content="b", score=0.7),
    ], reranker=reranker)
    engine = _make_engine_with_mock(retriever)

    results = engine.retrieve("test", top_k=5)
    assert len(reranker.calls) == 1, f"reranker 应被调用 1 次, 实际 {len(reranker.calls)}"
    print("✅ test_reranker_is_called PASSED")


def test_rag_config_defaults_changed():
    """P6.S.9: RAGConfig 默认值应已更新"""
    from rag.rag_engine import RAGConfig

    cfg = RAGConfig()
    assert cfg.min_similarity == 0.05, f"min_similarity 应 0.05, 实际 {cfg.min_similarity}"
    assert cfg.post_filter_threshold == 0.005, f"post_filter_threshold 应 0.005, 实际 {cfg.post_filter_threshold}"
    assert cfg.initial_fetch_multiplier == 4, f"initial_fetch_multiplier 应 4, 实际 {cfg.initial_fetch_multiplier}"
    print("✅ test_rag_config_defaults_changed PASSED")


def test_all_filtered_below_threshold():
    """所有候选都低于阈值 → 返空列表(不是 5 个低分)"""
    # 全部 < 0.005 绝对下界,且 max*0.3 也 < 0.005
    retriever = MockRetriever([
        FakeResult(id=f"r{i}", content=f"content {i}", score=0.0001) for i in range(10)
    ])
    engine = _make_engine_with_mock(retriever, post_filter_threshold=0.005)

    results = engine.retrieve("test", top_k=5)
    assert results == [], f"应返空, 实际 {results}"
    print("✅ test_all_filtered_below_threshold PASSED")


def test_core_init_rag_uses_p6s9_config():
    """P6.S.9: core.py _init_rag_engine 应传新配置"""
    # 读 core.py 源码确认
    core_path = Path(__file__).resolve().parent.parent / "src" / "agent" / "core.py"
    src = core_path.read_text(encoding="utf-8")
    assert "post_filter_threshold=0.005" in src, "core.py 应配 post_filter_threshold=0.005"
    assert "initial_fetch_multiplier=4" in src, "core.py 应配 initial_fetch_multiplier=4"
    assert "min_similarity=0.05" in src, "core.py 应配 min_similarity=0.05"
    print("✅ test_core_init_rag_uses_p6s9_config PASSED")


if __name__ == "__main__":
    test_post_filter_drops_low_score()
    test_unrelated_query_returns_empty()
    test_initial_fetch_multiplier_4()
    test_top_k_truncation()
    test_reranker_is_called()
    test_rag_config_defaults_changed()
    test_all_filtered_below_threshold()
    test_core_init_rag_uses_p6s9_config()
    print("\n🎉 All P6.S.9 tests PASSED")
