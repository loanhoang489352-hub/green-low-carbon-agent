"""
列表页 -> 详情页链接提取器(Priority 2 工具)

输入: data/raw/{date}/{source}/*.html(列表页)
输出: 控制台打印每页提取到的所有详情页链接(URL + 标题)

用法:
    PYTHONIOENCODING=utf-8 python scripts/extract_detail_links.py data/raw/2026-06-10/生态环境部-双碳专题/001359_4871cb96.html
    PYTHONIOENCODING=utf-8 python scripts/extract_detail_links.py data/raw/2026-06-10/北京生态环境局-新闻/001404_3a5552da.html
"""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urljoin
import re

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("[ERROR] 需要 pip install beautifulsoup4")
    sys.exit(1)


def extract_links(html: str, base_url: str) -> list[dict]:
    """从列表页提取详情页链接"""
    soup = BeautifulSoup(html, "html.parser")
    seen = set()
    links = []

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        title = a.get_text(strip=True)

        # 过滤
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue
        if not title or len(title) < 6:  # 至少 6 字符的链接标题才算有意义
            continue

        # 拼绝对 URL
        abs_url = urljoin(base_url, href)

        # 只保留 http(s) 链接
        if not abs_url.startswith("http"):
            continue

        # 同 URL 去重
        if abs_url in seen:
            continue
        seen.add(abs_url)

        links.append({"url": abs_url, "title": title})

    return links


def classify_link(url: str, title: str) -> str:
    """简单分类:政策正文 / 列表导航 / 其它"""
    # 政策原文典型 URL 模式
    if re.search(r"\.(shtml|html)(\?.*)?$", url):
        if any(kw in title for kw in ["通知", "通告", "公告", "意见", "办法", "方案", "通报", "报告", "规划", "决议", "决定"]):
            return "✅ 政策正文"
        if any(kw in url for kw in ["xxgk", "zfxxgk", "zhengce", "policy", "wjk"]):
            return "🟡 可能政策"
    if any(kw in url for kw in ["list", "channel", "topic", "index"]):
        return "📋 列表/导航"
    if any(kw in url for kw in ["search", "login", "register", "contact", "about"]):
        return "❌ 功能页"
    return "🟡 待判定"


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: extract_detail_links.py <html-file>")
        sys.exit(1)

    fpath = Path(sys.argv[1])
    if not fpath.exists():
        print(f"[ERROR] 文件不存在: {fpath}")
        sys.exit(1)

    # 读 meta.json 拿原始 URL
    meta_path = fpath.parent / f"{fpath.name}.meta.json"
    base_url = ""
    if meta_path.exists():
        import json
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        base_url = meta.get("source_url", "")

    if not base_url:
        # 回退:从文件名/路径反推
        base_url = "https://www.mee.gov.cn/"  # 默认
        print(f"[WARN] 无 meta.json,使用默认 base_url: {base_url}")

    html = fpath.read_text(encoding="utf-8")
    print(f"=== {fpath.name} ===")
    print(f"  base_url: {base_url}")
    print(f"  bytes: {len(html)}\n")

    links = extract_links(html, base_url)
    print(f"  发现 {len(links)} 个链接\n")

    # 分类汇总
    categorized: dict[str, list] = {}
    for lk in links:
        cat = classify_link(lk["url"], lk["title"])
        categorized.setdefault(cat, []).append(lk)

    # 打印分类结果(政策正文优先)
    order = ["✅ 政策正文", "🟡 可能政策", "🟡 待判定", "📋 列表/导航", "❌ 功能页"]
    for cat in order:
        if cat not in categorized:
            continue
        items = categorized[cat]
        print(f"--- {cat} ({len(items)}) ---")
        for i, lk in enumerate(items[:20]):  # 每类最多打印 20 个
            print(f"  [{i+1:2d}] {lk['title'][:60]:60s}")
            print(f"       {lk['url']}")
        if len(items) > 20:
            print(f"  ... 还有 {len(items) - 20} 个")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
