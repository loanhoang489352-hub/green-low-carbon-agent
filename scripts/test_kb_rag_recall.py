"""
KB-v2 RAG 召回测试

测试新加的 3 篇北京 2026 政策详情页是否能被 RAG 正确召回

用法:
    PYTHONIOENCODING=utf-8 python scripts/test_kb_rag_recall.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from rag.rag_engine import get_rag_engine, reset_rag_engine
from paths import KNOWLEDGE_BASE_DIR


# 6 个测试查询(分别覆盖 3 篇新文档的核心内容)
QUERIES = [
    # 来自 beijing_2025_report.md
    ("北京 2025 年 PM2.5 是多少", "beijing_2025_report"),
    ("北京碳市场累计交易了多少 CO2", "beijing_2025_report"),
    # 来自 beijing_2026_check.md
    ("北京 2026 年碳排放检查的对象有多少家", "beijing_2026_check"),
    ("北京重点碳排放单位检查截止时间", "beijing_2026_check"),
    # 来自 beijing_2026_low_carbon_call.md
    ("北京 2026 低碳领跑者面向哪些行业", "beijing_2026_low_carbon_call"),
    ("北京气候友好型区域评选标准", "beijing_2026_low_carbon_call"),
]


def main() -> int:
    print("=== KB-v2 RAG 召回测试 ===\n")

    # 重置 + 重建索引
    reset_rag_engine()
    engine = get_rag_engine()
    engine.initialize(str(KNOWLEDGE_BASE_DIR))

    print(f"知识库目录: {KNOWLEDGE_BASE_DIR}")
    stats = engine.get_stats()
    print(f"索引文档总数: {stats.get('total_documents', 'N/A')}")
    print(f"  向量库大小: {stats.get('vector_store_size', 'N/A')}\n")

    # 跑 6 查询
    hits = 0
    misses = []
    for i, (query, expected_slug) in enumerate(QUERIES, 1):
        print(f"--- 查询 {i}/{len(QUERIES)} ---")
        print(f"  Q: {query}")
        print(f"  期望命中文件: {expected_slug}*.md")

        results = engine.retrieve(query, top_k=3)
        if not results:
            print(f"  ❌ 无结果")
            misses.append((query, expected_slug, "无结果"))
            continue

        # 检查 top3 是否包含期望文件(RetrievalResult dataclass)
        top_files = [r.metadata.get("source", "?") for r in results]
        top_scores = [round(r.score, 3) for r in results]

        ok = any(expected_slug in str(f) for f in top_files)
        status = "✅" if ok else "❌"
        print(f"  {status} top3 文件: {[Path(f).name for f in top_files]}")
        print(f"     scores: {top_scores}")

        if ok:
            hits += 1
        else:
            misses.append((query, expected_slug, f"top3={[Path(f).name for f in top_files]}"))

        print()

    print("=== 总结 ===")
    print(f"  命中率: {hits}/{len(QUERIES)} ({100*hits//len(QUERIES)}%)")
    if misses:
        print(f"  未命中:")
        for q, exp, info in misses:
            print(f"    - Q: {q}")
            print(f"      期望: {exp}, 实际: {info}")

    return 0 if hits == len(QUERIES) else 1


if __name__ == "__main__":
    sys.exit(main())
