"""
P5-G: RAG 检索质量评估脚本

使用方法:
    python scripts/eval_retrieval.py --subset curated
    python scripts/eval_retrieval.py --subset full --collection green_agent_knowledge

输出:
    - 控制台: hit_rate@5, MRR@10, NDCG@10
    - data/eval_report.md: misses 列表 + per-category 明细
    - exit 0 当 curated subset hit_rate@5 ≥ 0.60(或 full ≥ 0.40)否则 exit 1
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import List, Dict, Tuple

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

GOLDEN_SET = PROJECT_ROOT / "tests" / "eval" / "golden_set.jsonl"
REPORT_PATH = PROJECT_ROOT / "data" / "eval_report.md"

# Curated 通过阈值,full 信息性
THRESHOLDS = {
    "curated": 0.60,
    "full": 0.40,
}


def load_golden(subset: str | None = None) -> List[Dict]:
    """加载 golden set,可选过滤 subset"""
    entries = []
    with open(GOLDEN_SET, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            if subset and e.get("subset") != subset:
                continue
            entries.append(e)
    return entries


def slug_of(source: str | None) -> str:
    """source 路径(如 'policy\\national\\xxx.md')→ slug(文件名 stem)"""
    if not source:
        return ""
    # 兼容 windows / posix 分隔符
    s = source.replace("\\", "/").split("/")[-1]
    if s.endswith(".md"):
        s = s[:-3]
    return s


def retrieve(engine, query: str, top_k: int) -> List[str]:
    """对单条 query 调 retrieve(),返 top_k 的 slug 列表"""
    results = engine.retrieve(query, top_k=top_k)
    slugs = []
    for r in results:
        # 兼容多种返回结构(Document / dict / namedtuple)
        meta = getattr(r, "metadata", None) or (r.get("metadata") if isinstance(r, dict) else None)
        source = (meta or {}).get("source", "") if meta else ""
        slugs.append(slug_of(source))
    return slugs


def hit_rate_at_k(predictions: List[str], expected: str, k: int) -> int:
    """1 if expected in top-k else 0"""
    return 1 if expected in predictions[:k] else 0


def reciprocal_rank(predictions: List[str], expected: str) -> float:
    """1 / rank(1-indexed) 若 expected 在 predictions 中,否则 0"""
    for i, p in enumerate(predictions):
        if p == expected:
            return 1.0 / (i + 1)
    return 0.0


def ndcg_at_k(predictions: List[str], expected: str, k: int) -> float:
    """二元 relevance NDCG@k(只一个相关文档时,DCG = 1/log2(rank+1))"""
    for i, p in enumerate(predictions[:k]):
        if p == expected:
            return 1.0 / math.log2(i + 2)
    return 0.0


def evaluate(entries: List[Dict], engine, k_hit=5, k_mrr=10, k_ndcg=10) -> Dict:
    """对每条 query 跑检索,聚合三个 metric + 收集 misses"""
    hits, mrrs, ndcgs = [], [], []
    misses = []
    per_cat = defaultdict(lambda: {"hit": 0, "n": 0})

    for e in entries:
        q = e["query"]
        expected = e["expected_source_slug"]
        cat = e.get("category", "?")
        try:
            preds = retrieve(engine, q, top_k=k_mrr)
        except Exception as ex:
            preds = []
            print(f"[WARN] retrieve failed for '{q}': {ex}")

        h = hit_rate_at_k(preds, expected, k_hit)
        m = reciprocal_rank(preds, expected)
        n = ndcg_at_k(preds, expected, k_ndcg)
        hits.append(h)
        mrrs.append(m)
        ndcgs.append(n)
        per_cat[cat]["hit"] += h
        per_cat[cat]["n"] += 1

        if h == 0:
            misses.append({
                "query": q,
                "expected": expected,
                "category": cat,
                "top3_actual": preds[:3],
            })

    n = len(entries) or 1
    return {
        "n": len(entries),
        f"hit_rate@{k_hit}": sum(hits) / n,
        f"mrr@{k_mrr}": sum(mrrs) / n,
        f"ndcg@{k_ndcg}": sum(ndcgs) / n,
        "per_category": {c: v["hit"] / v["n"] for c, v in per_cat.items()},
        "misses": misses,
    }


def write_report(result: Dict, subset: str, collection: str) -> None:
    """写 data/eval_report.md(含 misses)"""
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    lines.append(f"# RAG 检索质量评估报告 — subset={subset}")
    lines.append("")
    lines.append(f"- 集合: `{collection}`")
    lines.append(f"- 总 query 数: **{result['n']}**")
    lines.append("")
    lines.append("## 总体指标")
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("|---|---|")
    for k, v in result.items():
        if k in ("n", "per_category", "misses"):
            continue
        lines.append(f"| {k} | {v:.4f} |")
    lines.append("")
    lines.append("## 分类 hit_rate@5")
    lines.append("")
    lines.append("| 类目 | hit_rate@5 |")
    lines.append("|---|---|")
    for cat, hr in sorted(result["per_category"].items(), key=lambda x: -x[1]):
        lines.append(f"| {cat} | {hr:.4f} |")
    lines.append("")
    if result["misses"]:
        lines.append(f"## 未命中明细({len(result['misses'])} 条)")
        lines.append("")
        for m in result["misses"]:
            lines.append(f"- **query**: `{m['query']}`  (类目: {m['category']})")
            lines.append(f"  - 期望 slug: `{m['expected']}`")
            lines.append(f"  - top-3 实际: {m['top3_actual']}")
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="RAG 检索质量评估")
    parser.add_argument("--subset", choices=["curated", "full"], default="curated",
                        help="curated=CI gate(30+条) / full=全集(50+条)")
    parser.add_argument("--collection", default="green_agent_knowledge",
                        help="ChromaDB collection 名(默认 green_agent_knowledge)")
    parser.add_argument("--no-exit-code", action="store_true",
                        help="不根据 threshold 返 exit code(用于本地诊断)")
    args = parser.parse_args()

    # subset=curated 只跑 curated;subset=full 跑全集
    if args.subset == "full":
        entries = load_golden(subset=None)
    else:
        entries = load_golden(subset="curated")

    if not entries:
        print(f"[ERR] golden set 为空(subset={args.subset})")
        sys.exit(2)

    print(f"[eval] subset={args.subset} → {len(entries)} queries, collection={args.collection}")

    from rag.rag_engine import get_rag_engine, RAGConfig
    from paths import KNOWLEDGE_BASE_DIR
    engine = get_rag_engine(RAGConfig(collection_name=args.collection))
    if not engine._initialized:
        ok = engine.initialize(str(KNOWLEDGE_BASE_DIR))
        if not ok:
            print("[ERR] RAG 引擎初始化失败")
            sys.exit(2)

    result = evaluate(entries, engine)
    print()
    print(f"=== 评估结果 ===")
    print(f"  n               = {result['n']}")
    print(f"  hit_rate@5      = {result['hit_rate@5']:.4f}")
    print(f"  mrr@10          = {result['mrr@10']:.4f}")
    print(f"  ndcg@10         = {result['ndcg@10']:.4f}")
    print()
    print(f"  分类 hit_rate@5:")
    for cat, hr in sorted(result["per_category"].items(), key=lambda x: -x[1]):
        print(f"    {cat:20s} {hr:.4f}")
    print()
    print(f"  未命中: {len(result['misses'])} 条")
    print(f"  报告:   {REPORT_PATH}")

    write_report(result, args.subset, args.collection)

    threshold = THRESHOLDS[args.subset]
    passed = result["hit_rate@5"] >= threshold
    print()
    print(f"  阈值: hit_rate@5 >= {threshold} → {'PASS' if passed else 'FAIL'}")

    if args.no_exit_code:
        sys.exit(0)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
