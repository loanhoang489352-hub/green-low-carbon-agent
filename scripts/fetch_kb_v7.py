"""
KB-v7: 抓国家统计局 + CCER 方法学等高价值国家级原文
(国标网 JS 渲染搜索难直抓,改抓 mee.gov.cn 列表里的 CCER 方法学等)
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
    from bs4 import BeautifulSoup
except ImportError:
    print("[ERROR] pip install httpx beautifulsoup4"); sys.exit(1)


ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "raw" / datetime.now().strftime("%Y-%m-%d") / "kb_v7_批量"
OUT_DIR.mkdir(parents=True, exist_ok=True)


# 高价值国家级文档(从 mee.gov.cn 双碳列表 + 国新办挑选)
URLS = [
    # CCER 方法学(2024-2025 重点)
    {
        "title": "温室气体自愿减排项目方法学 可再生能源电解水制氢(CCER-01-004-V01)",
        "url": "https://www.mee.gov.cn/xxgk2018/xxgk/xxgk06/202512/t20251226_1139056.html",
        "date_hint": "2025-12",
        "category": "ccer-electrolytic-hydrogen",
    },
    {
        "title": "温室气体自愿减排项目方法学 中深层地热能井下换热供暖技术应用工程(CCER-01-003-V01)",
        "url": "https://www.mee.gov.cn/xxgk2018/xxgk/xxgk06/202512/t20251226_1139063.html",
        "date_hint": "2025-12",
        "category": "ccer-deep-geothermal",
    },
    {
        "title": "温室气体自愿减排项目方法学 规模化猪场粪污沼气回收利用工程(CCER-15-001-V01)",
        "url": "https://www.mee.gov.cn/xxgk2018/xxgk/xxgk06/202512/t20251217_1138026.html",
        "date_hint": "2025-12",
        "category": "ccer-pig-farm-biogas",
    },
    # 省级温室气体清单
    {
        "title": "关于印发《省级温室气体清单编制指南(2025 年版)》的通知",
        "url": "https://www.mee.gov.cn/xxgk2018/xxgk/xxgk05/202601/t20260104_1139798.html",
        "date_hint": "2026-01",
        "category": "provincial-ghg-inventory",
    },
    # 适应气候变化
    {
        "title": "关于印发《中国适应气候变化进展报告(2023)》的函",
        "url": "https://www.mee.gov.cn/xxgk2018/xxgk/xxgk06/202406/t20240607_1075247.html",
        "date_hint": "2024-06",
        "category": "climate-adaptation-progress",
    },
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

SLEEP = 2.0


def slugify_url(url: str) -> str:
    path = urlparse(url).path
    name = path.split("/")[-1].split(".")[0]
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
    soup = BeautifulSoup(html, "html.parser")

    title = ""
    if soup.title:
        title = soup.title.get_text(strip=True)
    for sel in ["h1", "div.titletop", "div.title", ".article-title"]:
        el = soup.select_one(sel)
        if el:
            t = el.get_text(strip=True)
            if 5 < len(t) < 200:
                title = t
                break

    body = ""
    for sel in [
        "div.TRS_Editor", "#UCAP-CONTENT", "div.neiright_JPZ_GK_CP",
        ".content_box", ".article_content", "#content",
    ]:
        container = soup.select_one(sel)
        if container:
            paragraphs = []
            for p in container.find_all("p"):
                t = p.get_text(strip=True)
                if len(t) > 20:
                    paragraphs.append(t)
            if len(paragraphs) < 3:
                paragraphs = []
                for el in container.find_all(["div", "li"], recursive=True):
                    if el.find(["div", "p"], recursive=False):
                        continue
                    t = el.get_text(strip=True)
                    if len(t) > 20:
                        paragraphs.append(t)
            body = "\n\n".join(paragraphs)
            if len(body) > 200:
                break

    if len(body) < 200:
        paragraphs = []
        for p in soup.find_all("p"):
            text = p.get_text(strip=True)
            if len(text) > 20:
                paragraphs.append(text)
        body = "\n\n".join(paragraphs)

    return title, body


def main() -> int:
    print(f"=== KB-v7 批量抓 ===\n输出: {OUT_DIR}\n")
    summary = []
    for i, item in enumerate(URLS, 1):
        url = item["url"]
        slug = slugify_url(url)
        print(f">> [{i}/{len(URLS)}] {item['title'][:50]}...")
        html = fetch(url)
        if html is None:
            summary.append({"idx": i, "url": url, "ok": False})
            time.sleep(SLEEP)
            continue

        html_path = OUT_DIR / f"{slug}.html"
        html_path.write_text(html, encoding="utf-8")

        title, body = extract_text(html)
        body_path = OUT_DIR / f"{slug}.body.txt"
        body_path.write_text(f"# {title}\n\nURL: {url}\n抓取: {datetime.now().isoformat()}\n\n---\n\n{body}", encoding="utf-8")

        meta = {
            "url": url, "title": title or item["title"],
            "date_hint": item["date_hint"], "category": item["category"],
            "fetched_at": datetime.now().isoformat(),
            "html_bytes": len(html), "body_chars": len(body),
        }
        (OUT_DIR / f"{slug}.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        print(f"   [OK] html={len(html)}b body={len(body)}c title='{title[:50]}'")
        summary.append({"idx": i, "url": url, "ok": True, "slug": slug, "body_chars": len(body)})
        time.sleep(SLEEP)

    print(f"\n=== 汇总 ===")
    ok = sum(1 for s in summary if s.get("ok"))
    print(f"  成功: {ok}/{len(URLS)}")
    for s in summary:
        mark = "✅" if s.get("ok") else "❌"
        extra = f"body={s.get('body_chars',0)}c slug={s.get('slug','?')}" if s.get("ok") else "FAIL"
        print(f"  {mark} [{s['idx']}] {extra}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
