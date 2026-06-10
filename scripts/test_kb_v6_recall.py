"""
KB-v6 RAG 召回测试(P2 国家级政策原文)

覆盖刚加的 4 篇 mee.gov.cn 国家级政策原文
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from rag.rag_engine import get_rag_engine, reset_rag_engine
from paths import KNOWLEDGE_BASE_DIR


QUERIES = [
    # 2026_national_carbon_market_notice.md
    ("2026 年全国碳市场覆盖哪 4 个行业", "2026_national_carbon_market_notice"),
    ("2026 年发电行业碳排放配额清缴截止时间", "2026_national_carbon_market_notice"),
    # 2026_ghg_emission_factor_db_v2.md
    ("国家温室气体排放因子数据库第二版有多少个因子", "2026_ghg_emission_factor_db_v2"),
    ("排放因子数据库新增哪些产品的碳强度数据", "2026_ghg_emission_factor_db_v2"),
    # 2025_carbon_footprint_db_guideline.md
    ("产品碳足迹因子数据库建设由哪些部委联合发布", "2025_carbon_footprint_db_guideline"),
    # 2026_power_sector_carbon_guide_update.md
    ("燃煤碳氧化率因子的更新", "2026_power_sector_carbon_guide_update"),
]


def main() -> int:
    print("=== KB-v6 RAG 召回测试(国家政策)===\n")

    reset_rag_engine()
    engine = get_rag_engine()
    engine.initialize(str(KNOWLEDGE_BASE_DIR))

    stats = engine.get_stats()
    print(f"知识库目录: {KNOWLEDGE_BASE_DIR}")
    print(f"索引文档总数: {stats.get('total_documents', 'N/A')}\n")

    hits = 0
    misses = []
    for i, (query, expected_slug) in enumerate(QUERIES, 1):
        print(f"--- 查询 {i}/{len(QUERIES)} ---")
        print(f"  Q: {query}")
        print(f"  期望: {expected_slug}*.md")

        results = engine.retrieve(query, top_k=3)
        if not results:
            print(f"  ❌ 无结果")
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
        print(f"  未命中:")
        for q, exp, info in misses:
            print(f"    - Q: {q}")
            print(f"      期望: {exp}, 实际: {info}")

    return 0 if hits >= len(QUERIES) * 0.5 else 1


if __name__ == "__main__":
    sys.exit(main())
