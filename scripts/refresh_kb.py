"""
知识库刷新脚本(KB-v2 半自动策展)

从 config/sources.yaml 读取政策/知识源,抓取原始 HTML 落到 data/raw/{date}/{source}/{slug}.html
供人工 review 后再手动 commit 进 knowledge_base/(不做自动入库,保留"知识策展"流程)

用法:
    python scripts/refresh_kb.py                 # 拉取所有 enabled=True 源
    python scripts/refresh_kb.py --list          # 列出所有源
    python scripts/refresh_kb.py --source X      # 只拉取 name=X 的源
    python scripts/refresh_kb.py --index         # 扫描 data/raw/ 生成 review index
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# 项目根
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

try:
    import httpx
except ImportError:
    print("[ERROR] 需要安装 httpx: pip install httpx")
    sys.exit(1)

try:
    from config_loader import get_policy_sources
except ImportError:
    print("[ERROR] 无法 import config_loader")
    sys.exit(1)


# 精细 headers(实测能通)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
}

# 默认限速(秒/请求,避免被反爬)
DEFAULT_SLEEP = 2.0

# 失败重试
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0


def slugify(name: str) -> str:
    """源名 → 文件名 slug"""
    return name.replace(" ", "_").replace("/", "_")


def fetch_url(url: str, timeout: int = 30) -> Optional[str]:
    """拉取 URL,带重试,失败返回 None"""
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = httpx.get(url, timeout=timeout, follow_redirects=True, headers=HEADERS)
            r.raise_for_status()
            if r.encoding and r.encoding.lower() not in ("utf-8", "utf8"):
                try:
                    r.encoding = "utf-8"
                except Exception:
                    pass
            return r.text
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF ** attempt
                print(f"  [WARN] {type(e).__name__}: {str(e)[:60]} (重试 {attempt}/{MAX_RETRIES-1} 等 {wait:.1f}s)")
                time.sleep(wait)
    print(f"  [FAIL] 重试 {MAX_RETRIES} 次仍失败: {type(last_err).__name__}: {str(last_err)[:80]}")
    return None


def save_raw(source: Dict[str, Any], html: str, base_dir: Path) -> Path:
    """保存原始 HTML 到 data/raw/{date}/{source_name}/{slug}.html"""
    today = datetime.now().strftime("%Y-%m-%d")
    src_dir = base_dir / today / slugify(source["name"])
    src_dir.mkdir(parents=True, exist_ok=True)

    # 文件名 = URL hash(避免重复)
    url_hash = hashlib.md5(source["url"].encode()).hexdigest()[:8]
    fname = f"{datetime.now().strftime('%H%M%S')}_{url_hash}.html"
    fpath = src_dir / fname

    fpath.write_text(html, encoding="utf-8")

    # 配套 meta.json(便于 review)
    meta = {
        "source_name": source["name"],
        "source_url": source["url"],
        "type": source.get("type", "html"),
        "category": source.get("category", ""),
        "region": source.get("region", ""),
        "fetched_at": datetime.now().isoformat(),
        "bytes": len(html),
        "url_hash": url_hash,
    }
    (src_dir / f"{fname}.meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return fpath


def list_sources() -> None:
    """列出所有源"""
    sources = get_policy_sources()
    print(f"=== {len(sources)} 个启用的源 ===")
    for i, s in enumerate(sources, 1):
        ok = fetch_url(s["url"], timeout=10) is not None
        status = "✅ 可通" if ok else "❌ 不可通"
        print(f"  [{i:2d}] {status}  {s['name']:25s}  {s['url']}")


def fetch_one(source: Dict[str, Any], base_dir: Path, sleep: float) -> Dict[str, Any]:
    """抓取单个源"""
    print(f"\n>> {source['name']} ({source.get('type', 'html')})")
    print(f"   URL: {source['url']}")
    t0 = time.time()
    html = fetch_url(source["url"])
    if not html:
        return {"name": source["name"], "ok": False, "elapsed_s": time.time() - t0}

    fpath = save_raw(source, html, base_dir)
    elapsed = time.time() - t0
    print(f"   [OK]  {len(html):>8} bytes -> {fpath.relative_to(ROOT)}  ({elapsed:.1f}s)")

    if sleep > 0:
        time.sleep(sleep)

    return {
        "name": source["name"],
        "ok": True,
        "elapsed_s": elapsed,
        "bytes": len(html),
        "path": str(fpath.relative_to(ROOT)),
    }


def build_review_index(raw_dir: Path) -> Path:
    """扫描 data/raw/ 生成 REVIEW.md(供人工 review)"""
    if not raw_dir.exists():
        print(f"[WARN] {raw_dir} 不存在,无 review 内容")
        return None

    today = datetime.now().strftime("%Y-%m-%d")
    out = ROOT / "REVIEW.md"

    lines = [
        f"# 知识库原始数据 Review 索引",
        f"\n生成时间: {datetime.now().isoformat()}",
        f"\n数据目录: `{raw_dir.relative_to(ROOT)}`",
        f"\n## Review 流程",
        f"1. 查看各源原始 HTML(用浏览器打开或编辑器)",
        f"2. 提取**真正有价值**的内容(剔除导航/广告/重复)",
        f"3. 改写为 `knowledge_base/` 下的 markdown",
        f"4. commit → 触发 RAG 重建",
        f"\n---",
        f"\n## 各源抓取记录",
    ]

    for date_dir in sorted(raw_dir.iterdir(), reverse=True):
        if not date_dir.is_dir():
            continue
        lines.append(f"\n### {date_dir.name}")
        for src_dir in sorted(date_dir.iterdir()):
            if not src_dir.is_dir():
                continue
            html_files = sorted(src_dir.glob("*.html"))
            if not html_files:
                continue
            lines.append(f"\n#### {src_dir.name} ({len(html_files)} 文件)")
            for hf in html_files:
                meta_path = hf.parent / f"{hf.name}.meta.json"
                meta = {}
                if meta_path.exists():
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                lines.append(
                    f"- `{hf.relative_to(ROOT)}`  "
                    f"({meta.get('bytes', 0)} bytes, "
                    f"{meta.get('category', '')} "
                    f"{meta.get('region', '')})"
                )

    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"  Review 索引: {out}")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="知识库刷新 — 拉源到 data/raw/")
    parser.add_argument("--list", action="store_true", help="列出所有源(连通性测试)")
    parser.add_argument("--source", type=str, help="只拉取指定 name 的源")
    parser.add_argument("--index", action="store_true", help="只生成 review 索引")
    parser.add_argument("--sleep", type=float, default=DEFAULT_SLEEP, help=f"源间限速(秒,默认 {DEFAULT_SLEEP})")
    args = parser.parse_args()

    raw_dir = ROOT / "data" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    if args.index:
        build_review_index(raw_dir)
        return 0

    if args.list:
        list_sources()
        return 0

    sources = get_policy_sources()
    if args.source:
        sources = [s for s in sources if s["name"] == args.source]
        if not sources:
            print(f"[ERROR] 未找到源: {args.source}")
            print("可用源:")
            for s in get_policy_sources():
                print(f"  - {s['name']}")
            return 1

    print(f"=== 准备抓取 {len(sources)} 个源 ===")
    print(f"原始数据目录: {raw_dir.relative_to(ROOT)}")
    print(f"源间限速: {args.sleep}s")

    results = []
    for s in sources:
        r = fetch_one(s, raw_dir, args.sleep)
        results.append(r)

    # 汇总
    print(f"\n=== 抓取汇总 ===")
    ok = sum(1 for r in results if r.get("ok"))
    print(f"  成功: {ok}/{len(results)}")
    for r in results:
        mark = "✅" if r.get("ok") else "❌"
        detail = f"{r.get('bytes', 0)} bytes" if r.get("ok") else f"{r.get('elapsed_s', 0):.1f}s"
        print(f"  {mark} {r['name']:25s}  {detail}")

    # 生成 review index
    build_review_index(raw_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
