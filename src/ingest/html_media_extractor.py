"""
HTML 内嵌媒体提取 — 用 BeautifulSoup 提取 <img src=...> / <embed src=...> / <iframe src=...>

用途:
- 政府政策页常常把正式 PDF 嵌在 <embed> / <iframe>,或不把正文写在 HTML 里
- 这些 URL 也作为次级抓取任务送入 OCR pipeline
- 只挑看起来是政府/资源站点的 URL,过滤掉 logo / 装饰图

输出: List[MediaItem] — 每条含 (url, mime_hint, kind)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urljoin

logger = logging.getLogger(__name__)


# URL 看起来是 PDF 的特征
_PDF_URL_HINTS = (".pdf", "pdf?", "pdf=", "/pdf/", "type=pdf")
# URL 看起来是图片的特征
_IMAGE_URL_HINTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")


@dataclass
class MediaItem:
    """HTML 内嵌媒体"""

    url: str  # 绝对 URL
    kind: str  # "pdf" | "image" | "iframe"
    mime_hint: str = ""  # 推测的 MIME(image/png 等)

    def to_dict(self) -> dict:
        return {"url": self.url, "kind": self.kind, "mime_hint": self.mime_hint}


def _looks_like_pdf(url: str) -> bool:
    u = (url or "").lower()
    return any(h in u for h in _PDF_URL_HINTS)


def _looks_like_image(url: str) -> bool:
    u = (url or "").lower()
    if any(h in u for h in _IMAGE_URL_HINTS):
        return True
    # base64 data URL 也算
    return u.startswith("data:image/")


def _infer_image_mime(url: str) -> str:
    u = (url or "").lower()
    if ".png" in u:
        return "image/png"
    if ".webp" in u:
        return "image/webp"
    if ".bmp" in u:
        return "image/bmp"
    if ".gif" in u:
        return "image/gif"
    return "image/jpeg"


class HTMLMediaExtractor:
    """从 HTML 提取需要 OCR 的媒体 URL

    Args:
        max_items: 单页最多返回多少条(防广告站意外爆炸),默认 10
        base_url: 用于 urljoin 相对路径;不传则尝试从传入 html 解析
    """

    def __init__(self, max_items: int = 10, base_url: Optional[str] = None) -> None:
        self.max_items = max_items
        self.base_url = base_url

    def extract(self, html: str, base_url: Optional[str] = None) -> List[MediaItem]:
        """提取 HTML 中的 <img> / <embed> / <iframe>

        Args:
            html: HTML 字符串
            base_url: 用于相对路径解析;不传则用 self.base_url
        """
        if not html:
            return []
        base = base_url or self.base_url or ""
        items: List[MediaItem] = []

        try:
            from bs4 import BeautifulSoup
        except Exception as exc:  # noqa: BLE001
            logger.warning("[HTMLMediaExtractor] bs4 不可用: %s", exc)
            return items

        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception as exc:  # noqa: BLE001
            logger.warning("[HTMLMediaExtractor] 解析失败: %s", exc)
            return items

        # <img src=...>
        for img in soup.find_all("img"):
            src = img.get("src") or ""
            if not src or src.startswith("data:image/svg"):
                continue
            if not _looks_like_image(src):
                # 即使后缀不是图片,也按图片处理(很多政府站图片不带后缀)
                pass
            url = self._absolutize(src, base)
            if url:
                items.append(
                    MediaItem(
                        url=url,
                        kind="image",
                        mime_hint=_infer_image_mime(url),
                    )
                )

        # <embed src=...> + <iframe src=...> + <object data=...>
        for tag in soup.find_all(["embed", "iframe", "object"]):
            attr = "src" if tag.name != "object" else "data"
            src = tag.get(attr) or ""
            if not src:
                continue
            url = self._absolutize(src, base)
            if not url:
                continue
            if _looks_like_pdf(url) or tag.name in ("embed", "iframe", "object"):
                items.append(
                    MediaItem(
                        url=url,
                        kind="pdf" if _looks_like_pdf(url) else tag.name,
                        mime_hint="application/pdf",
                    )
                )

        # 去重(同 URL 出现多次)
        seen = set()
        unique: List[MediaItem] = []
        for it in items:
            key = (it.url, it.kind)
            if key in seen:
                continue
            seen.add(key)
            unique.append(it)
            if len(unique) >= self.max_items:
                break
        return unique

    @staticmethod
    def _absolutize(href: str, base: str) -> str:
        """把相对路径转绝对 URL"""
        if not href:
            return ""
        if href.startswith(("http://", "https://", "data:")):
            return href
        if not base:
            return ""
        try:
            return urljoin(base, href)
        except Exception:
            return ""