"""
批量抓单个详情页 -> 转 markdown 草稿(Priority 2)

输入:URL 列表(自己改 URLS 列表)
输出:data/raw/{date}/详情页_批量/{slug}.html + .meta.json

后续人工 review + 改写到 knowledge_base/policy/

用法:
    PYTHONIOENCODING=utf-8 python scripts/fetch_detail_pages.py
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

try:
    import httpx
except ImportError:
    print("[ERROR] pip install httpx"); sys.exit(1)

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("[ERROR] pip install beautifulsoup4"); sys.exit(1)


ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "raw" / datetime.now().strftime("%Y-%m-%d") / "详情页_批量"
OUT_DIR.mkdir(parents=True, exist_ok=True)


# === 待抓的详情页(来自 Priority 2 列表页提取结果)===
URLS = [
    {
        "title": "关于公开征求更新《企业温室气体排放核算与报告指南 发电设施》和《企业温室气体排放核查技术指南 发电设施》有关燃煤碳氧化率",
        "url": "https://www.mee.gov.cn/xxgk2018/xxgk/xxgk06/202605/t20260521_1154888.html",
        "date_hint": "2026-05",
        "category": "national-carbon-market-guidance",
    },
    {
        "title": "关于做好 2026 年全国碳排放权交易市场有关工作的通知",
        "url": "https://www.mee.gov.cn/xxgk2018/xxgk/xxgk06/202602/t20260209_1143900.html",
        "date_hint": "2026-02",
        "category": "national-carbon-market-2026",
    },
    {
        "title": "关于印发《产品碳足迹因子数据库建设工作指引》的通知",
        "url": "https://www.mee.gov.cn/xxgk2018/xxgk/xxgk06/202512/t20251212_1137600.html",
        "date_hint": "2025-12",
        "category": "carbon-footprint-database",
    },
    {
        "title": "国家温室气体排放因子数据库(第二版)正式发布",
        "url": "https://www.mee.gov.cn/ywgz/ydqhbh/wsqtkz/202603/t20260301_1145117.shtml",
        "date_hint": "2026-03",
        "category": "ghg-emission-factor-database-v2",
    },
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

SLEEP = 2.0


def slugify_url(url: str) -> str:
    """URL -> 文件名 slug"""
    path = urlparse(url).path
    name = path.split("/")[-1].split(".")[0]  # t20260521_1154888
    return name or hashlib.md5(url.encode()).hexdigest()[:8]


def fetch(url: str) -> str | None:
    try:
        r = httpx.get(url, timeout=30, follow_redirects=True, headers=HEADERS)
        r.raise_for_status()
        if r.encoding and r.encoding.lower() not in ("utf-8", "utf8"):
            r.encoding = "utf-8"
        return r.text
    except Exception as e:
        print(f"  [FAIL] {type(e).__name__}: {str(e)[:80]}")
        return None


def extract_text(html: str) -> tuple[str, str]:
    """提取标题 + 正文。返回 (title, body_text)"""
    soup = BeautifulSoup(html, "html.parser")

    # title
    title = ""
    if soup.title:
        title = soup.title.get_text(strip=True)
    # 部分 mee.gov.cn 用 h1 / div.titletop
    for sel in ["h1", "div.titletop", "div.title", ".article-title"]:
        el = soup.select_one(sel)
        if el:
            t = el.get_text(strip=True)
            if 5 < len(t) < 200:
                title = t
                break

    # body — 优先正文容器(mee.gov.cn 用 .TRS_Editor / UCAP-CONTENT)
    body = ""
    for sel in [
        "div.TRS_Editor",          # 生态环境部最常用
        "#UCAP-CONTENT",
        "div.neiright_JPZ_GK_CP",   # 信息公开模板
        ".content_box",
        ".article_content",
        "#content",
    ]:
        container = soup.select_one(sel)
        if container:
            paragraphs = []
            # 优先按 <p> 取
            for p in container.find_all("p"):
                t = p.get_text(strip=True)
                if len(t) > 20:
                    paragraphs.append(t)
            # 若 <p> 不够,再按 div 取(mee 大量用 div 而非 p)
            if len(paragraphs) < 3:
                paragraphs = []
                for el in container.find_all(["div", "li"], recursive=True):
                    # 跳过嵌套包含子段的容器
                    if el.find(["div", "p"], recursive=False):
                        continue
                    t = el.get_text(strip=True)
                    if len(t) > 20:
                        paragraphs.append(t)
            body = "\n\n".join(paragraphs)
            if len(body) > 200:
                break

    # 兜底:整页 <p>
    if len(body) < 200:
        paragraphs = []
        for p in soup.find_all("p"):
            text = p.get_text(strip=True)
            if len(text) > 20:
                paragraphs.append(text)
        body = "\n\n".join(paragraphs)

    return title, body


def main() -> int:
    print(f"=== 批量抓详情页 ===")
    print(f"输出目录: {OUT_DIR}\n")

    summary = []
    for i, item in enumerate(URLS, 1):
        url = item["url"]
        slug = slugify_url(url)
        print(f">> [{i}/{len(URLS)}] {item['title'][:50]}...")
        print(f"   {url}")

        html = fetch(url)
        if html is None:
            summary.append({"idx": i, "url": url, "ok": False})
            time.sleep(SLEEP)
            continue

        # 保存 HTML
        html_path = OUT_DIR / f"{slug}.html"
        html_path.write_text(html, encoding="utf-8")

        # 提取标题/正文
        title, body = extract_text(html)
        body_path = OUT_DIR / f"{slug}.body.txt"
        body_path.write_text(f"# {title}\n\nURL: {url}\n抓取: {datetime.now().isoformat()}\n\n---\n\n{body}", encoding="utf-8")

        # meta
        meta_path = OUT_DIR / f"{slug}.meta.json"
        meta = {
            "url": url,
            "title": title or item["title"],
            "date_hint": item["date_hint"],
            "category": item["category"],
            "fetched_at": datetime.now().isoformat(),
            "html_bytes": len(html),
            "body_chars": len(body),
        }
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        print(f"   [OK] html={len(html)} bytes, body={len(body)} chars, title='{title[:50]}'")
        summary.append({"idx": i, "url": url, "ok": True, "slug": slug, "body_chars": len(body)})

        time.sleep(SLEEP)

    print(f"\n=== 汇总 ===")
    ok = sum(1 for s in summary if s.get("ok"))
    print(f"  成功: {ok}/{len(URLS)}")
    for s in summary:
        mark = "✅" if s.get("ok") else "❌"
        extra = f"body={s.get('body_chars', 0)}c slug={s.get('slug', '?')}" if s.get("ok") else "FAIL"
        print(f"  {mark} [{s['idx']}] {extra}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
