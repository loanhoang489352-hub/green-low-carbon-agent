"""
KB-v7 RAG 召回测试(CCER + 省级清单 + 适应进展)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from rag.rag_engine import get_rag_engine, reset_rag_engine
from paths import KNOWLEDGE_BASE_DIR


QUERIES = [
    # 2025_ccer_methodology_expansion.md
    ("CCER 方法学 可再生能源电解水制氢", "ccer_methodology_expansion"),
    ("规模化猪场粪污沼气如何申请 CCER", "ccer_methodology_expansion"),
    ("中深层地热能 CCER 方法学", "ccer_methodology_expansion"),
    ("六氟化硫 SF6 回收 CCER", "ccer_methodology_expansion"),
    # 2025_provincial_ghg_inventory_guide.md
    ("省级温室气体清单编制 2025 年版", "provincial_ghg_inventory_guide"),
    # 2023_china_climate_adaptation_progress.md
    ("国家适应气候变化战略 2035 重点领域", "china_climate_adaptation_progress"),
]


def main() -> int:
    print("=== KB-v7 RAG 召回测试 ===\n")
    reset_rag_engine()
    engine = get_rag_engine()
    engine.initialize(str(KNOWLEDGE_BASE_DIR))
    stats = engine.get_stats()
    print(f"索引文档总数: {stats.get('total_documents', 'N/A')}\n")

    hits = 0
    misses = []
    for i, (query, expected_slug) in enumerate(QUERIES, 1):
        print(f"--- 查询 {i}/{len(QUERIES)} ---")
        print(f"  Q: {query}")
        print(f"  期望: {expected_slug}*.md")
        results = engine.retrieve(query, top_k=3)
        if not results:
            print("  ❌ 无结果")
            misses.append((query, expected_slug, "无结果"))
            continue
        top_files = [r.metadata.get("source", "?") for r in results]
        top_scores = [round(r.score, 3) for r in results]
        ok = any(expected_slug in str(f) for f in top_files)
        status = "✅" if ok else "❌"
        print(f"  {status} top3: {[Path(f).name for f in top_files]}")
        print(f"     scores: {top_scores}")
        if ok:
            hits += 1
        else:
            misses.append((query, expected_slug, f"top3={[Path(f).name for f in top_files]}"))
        print()

    print(f"=== 总结 ===")
    print(f"  命中率: {hits}/{len(QUERIES)} ({100*hits//len(QUERIES)}%)")
    if misses:
        for q, exp, info in misses:
            print(f"  ❌ Q: {q}")
            print(f"     期望: {exp}, 实际: {info}")
    return 0 if hits >= len(QUERIES) * 0.5 else 1


if __name__ == "__main__":
    sys.exit(main())
