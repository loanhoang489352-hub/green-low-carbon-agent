"""
P6.R.2: 把 policies 表转 markdown 进 knowledge_base/ — 让 RAG 检索到

PolicyUpdater 抓的政策落 data/policy_updates.db::policies 表。
但 RAG 引擎 rebuild_index() 只从 knowledge_base/*.md 读,不读 policies。
此脚本把 policies 转 markdown,这样:
- rebuild_index 后,27 条 P6.R.2 新 policies 真正进 RAG 索引
- P5-G eval 重跑,hit_rate 应提升(0.7576 → 期望 0.80+)

用法:
    python scripts/import_policies_to_kb.py                       # 默认增量
    python scripts/import_policies_to_kb.py --full              # 全部
    python scripts/import_policies_to_kb.py --rebuild          # 转完自动 rebuild
"""
import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def export_policies(out_dir: Path, since: str | None = None) -> int:
    """P6.R.2: 把 policies 表转 markdown → out_dir

    Args:
        out_dir: knowledge_base 内的子目录(例 knowledge_base/policies/)
        since: ISO date,只导这个时间之后的(增量)

    Returns:
        导出条数
    """
    from paths import POLICY_UPDATES_DB

    out_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(POLICY_UPDATES_DB))
    try:
        if since:
            rows = conn.execute(
                "SELECT id, title, content, category, source_url, created_at "
                "FROM policies WHERE created_at >= ? ORDER BY created_at",
                (since,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, title, content, category, source_url, created_at "
                "FROM policies ORDER BY created_at"
            ).fetchall()

        exported = 0
        for pid, title, content, category, source_url, created_at in rows:
            # 文件名:id 为主,标题 slug 辅助
            # Windows 文件名禁 | < > : " / \ | ? * ,去这些
            import re
            slug = re.sub(r'[<>:"/\\|?*]', '', (title or "policy")[:30]).replace(" ", "_")
            md_path = out_dir / f"{pid:04d}_{slug}.md"
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(f"# {title}\n\n")
                f.write(f"**ID**: {pid}\n")
                f.write(f"**类别**: {category}\n")
                f.write(f"**来源**: <{source_url}>\n")
                f.write(f"**抓取时间**: {created_at}\n\n")
                f.write("---\n\n")
                f.write(content or "(无内容)")
                f.write("\n")
            exported += 1
        return exported
    finally:
        conn.close()


def rebuild_index() -> int:
    """P6.R.2: 重建 RAG 索引让 policies 进 ChromaDB"""
    from rag.rag_engine import get_rag_engine, RAGConfig
    from paths import KNOWLEDGE_BASE_DIR

    engine = get_rag_engine(RAGConfig(collection_name="green_agent_knowledge"))
    if not getattr(engine, "_initialized", False):
        engine.initialize(str(KNOWLEDGE_BASE_DIR))
    n = engine.rebuild_index(str(KNOWLEDGE_BASE_DIR))
    return n


def main():
    parser = argparse.ArgumentParser(description="P6.R.2: policies → markdown + rebuild RAG")
    parser.add_argument("--out", default="knowledge_base/policies",
                        help="markdown 输出目录(相对项目根)")
    parser.add_argument("--since", help="ISO date,只导这个时间之后(增量)")
    parser.add_argument("--rebuild", action="store_true",
                        help="转完后自动 rebuild RAG 索引")
    parser.add_argument("--no-export", action="store_true",
                        help="只 rebuild 不转 markdown(用上次导出)")
    args = parser.parse_args()

    out_dir = PROJECT_ROOT / args.out

    if not args.no_export:
        print(f"[INFO] 导出 policies → {out_dir}")
        if args.since:
            print(f"       (增量, since={args.since})")
        n = export_policies(out_dir, since=args.since)
        print(f"[OK] 导出 {n} 条 markdown")

    if args.rebuild:
        print(f"[INFO] 重建 RAG 索引(含新 policies markdown)...")
        HF_HUB_OFFLINE = 1  # noqa
        n = rebuild_index()
        print(f"[OK] 索引 {n} 文档块")
        print(f"\n  提示: 跑 P5-G eval 验证 hit_rate 变化")
        print(f"        HF_HUB_OFFLINE=1 python scripts/eval_retrieval.py --subset curated")


if __name__ == "__main__":
    sys.exit(main() or 0)
