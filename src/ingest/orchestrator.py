"""
OCR 摄入编排器 — PolicyUpdater / KnowledgeUpdater 的统一入口

输入:
- URL + (可选) Content-Type
- 或直接 bytes + mime

输出:
- IngestResult { ok, mime, text, engine, confidence, content_hash, cached, error }

策略:
1. URL → httpx 抓 bytes → 按 MIME 分支
   - application/pdf → PDFExtractor(pypdf + 必要时 OCR 兜底)
   - image/png|jpeg → OCREngine.recognize
   - 默认 HTML → 跳过(留给原 HTML 流程)
2. content_hash 命中 data/ocr_cache/<hash>.json → 直接返,避免重复 OCR
3. 失败不抛异常,统一返回 IngestResult(error=...) 让上层降级
"""
from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from ingest.ocr_cache import OCRCache, get_ocr_cache
from ingest.ocr_engine import OCREngine, get_ocr_engine
from ingest.pdf_extractor import extract_with_ocr_fallback

logger = logging.getLogger(__name__)


@dataclass
class IngestResult:
    """OCR 摄入结果"""

    ok: bool
    mime: str = ""
    text: str = ""
    engine: str = ""
    confidence: float = 0.0
    page_count: int = 0
    content_hash: str = ""
    cached: bool = False
    source_url: str = ""
    error: Optional[str] = None
    media_items: Optional[List[Dict[str, Any]]] = None  # HTML 内嵌媒体

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "mime": self.mime,
            "text": self.text,
            "engine": self.engine,
            "confidence": round(self.confidence, 4),
            "page_count": self.page_count,
            "content_hash": self.content_hash,
            "cached": self.cached,
            "source_url": self.source_url,
            "error": self.error,
            "media_items": self.media_items,
        }


def _normalize_mime(mime: str) -> str:
    """统一小写,剥 charset"""
    if not mime:
        return ""
    return mime.split(";", 1)[0].strip().lower()


def _is_pdf(mime: str, url: str = "") -> bool:
    m = _normalize_mime(mime)
    if m == "application/pdf":
        return True
    u = (url or "").lower()
    return ".pdf" in u and not u.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif"))


def _is_image(mime: str, url: str = "") -> bool:
    m = _normalize_mime(mime)
    if m.startswith("image/"):
        return True
    u = (url or "").lower()
    return any(u.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"))


def _is_html(mime: str) -> bool:
    m = _normalize_mime(mime)
    return m.startswith("text/html") or m == "application/xhtml+xml"


class IngestOrchestrator:
    """OCR 摄入编排器 — 统一 PDF / 图片 / HTML 入口

    Args:
        ocr_engine: 自定义 OCREngine,默认 get_ocr_engine()
        cache: 自定义 OCRCache,默认 get_ocr_cache()
        max_pdf_pages: PDF 扫描页 OCR 最多处理多少页(防失控),默认 50
    """

    def __init__(
        self,
        ocr_engine: Optional[OCREngine] = None,
        cache: Optional[OCRCache] = None,
        max_pdf_pages: int = 50,
    ) -> None:
        self.ocr_engine = ocr_engine or get_ocr_engine()
        self.cache = cache or get_ocr_cache()
        self.max_pdf_pages = max_pdf_pages

    # ------------------------------------------------------------------ #
    # URL 入口
    # ------------------------------------------------------------------ #
    def ingest_url(
        self,
        url: str,
        content_type: Optional[str] = None,
        timeout: int = 30,
    ) -> IngestResult:
        """从 URL 抓取并按 MIME 分支摄入"""
        if not url:
            return IngestResult(ok=False, source_url=url, error="empty_url")

        mime = _normalize_mime(content_type or "")

        try:
            import httpx
        except Exception as exc:  # noqa: BLE001
            return IngestResult(ok=False, source_url=url, error=f"httpx_unavailable: {exc}")

        # 1) 先按 URL 特征猜(很多政府站 content-type 不准)
        if not mime:
            if _is_pdf("", url):
                mime = "application/pdf"
            elif _is_image("", url):
                mime = "image/jpeg"

        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "*/*",
            }
            r = httpx.get(url, timeout=timeout, follow_redirects=True, headers=headers)
            r.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            return IngestResult(
                ok=False, source_url=url, mime=mime, error=f"fetch_failed: {type(exc).__name__}: {str(exc)[:120]}"
            )

        # 用响应头补 mime
        if not mime:
            mime = _normalize_mime(r.headers.get("content-type", ""))

        body = r.content
        return self.ingest_bytes(body, mime=mime, source_url=url)

    # ------------------------------------------------------------------ #
    # bytes 入口
    # ------------------------------------------------------------------ #
    def ingest_bytes(
        self,
        content: bytes,
        mime: str = "",
        source_url: str = "",
    ) -> IngestResult:
        """按 MIME 分支摄入二进制

        - application/pdf → pdfplumber + OCR fallback
        - image/*         → OCREngine.recognize
        - text/html       → 不做 OCR,只返回 mime=text/html(交给上层 HTML 流程)
        """
        mime = _normalize_mime(mime)

        # 0) 缓存:URL + mime 维度的轻量 hash(用于抓来前预判)
        url_hash = ""
        if source_url:
            url_hash = OCRCache.hash_url_with_meta(source_url, mime, len(content or b""))
            cached = self.cache.get(url_hash)
            if cached:
                cached["cached"] = True
                cached.setdefault("source_url", source_url)
                return _result_from_cache(cached, mime)

        # 1) PDF
        if _is_pdf(mime, source_url):
            return self._ingest_pdf(content, mime, source_url, url_hash)

        # 2) 图片
        if _is_image(mime, source_url):
            return self._ingest_image(content, mime, source_url, url_hash)

        # 3) HTML — 不 OCR,只返 ok=True + 空文本,留给上层 HTML 提取
        if _is_html(mime):
            return IngestResult(
                ok=True,
                mime="text/html",
                text="",
                engine="html_passthrough",
                source_url=source_url,
                content_hash=url_hash,
            )

        # 4) 未知 — 当作 HTML 兜底
        return IngestResult(
            ok=False,
            mime=mime,
            source_url=source_url,
            content_hash=url_hash,
            error=f"unsupported_mime: {mime or 'unknown'}",
        )

    # ------------------------------------------------------------------ #
    # PDF / 图片分支
    # ------------------------------------------------------------------ #
    def _ingest_pdf(
        self,
        content: bytes,
        mime: str,
        source_url: str,
        url_hash: str,
    ) -> IngestResult:
        if not content:
            return IngestResult(ok=False, mime=mime, source_url=source_url, error="empty_pdf_bytes")

        # 落临时文件,PDFExtractor 需要磁盘路径
        import tempfile
        import os

        content_hash = OCRCache.compute_hash(content, mime)
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(content)
                tmp_path = tmp.name
        except Exception as exc:  # noqa: BLE001
            return IngestResult(ok=False, mime=mime, source_url=source_url, error=f"tmp_write_failed: {exc}")

        try:
            # 单页 OCR 工厂:把 PDF 页渲染成临时图 → OCREngine
            engine = self.ocr_engine

            def recognize_page(pdf_path: str, page_num: int):
                from ingest.pdf_extractor import save_page_image

                img_tmp = tempfile.NamedTemporaryFile(
                    delete=False, suffix=".png", dir=os.path.dirname(tmp_path)
                )
                img_tmp.close()
                try:
                    save_page_image(pdf_path, page_num, img_tmp.name)
                    res = engine.recognize_image(img_tmp.name)
                finally:
                    try:
                        os.unlink(img_tmp.name)
                    except OSError:
                        pass
                from ingest.ocr_router import OCRResult

                return OCRResult(
                    text=res.get("text", ""),
                    confidence=res.get("confidence", 0.0),
                    engine=res.get("engine", ""),
                    page=page_num,
                    used_fallback=res.get("used_fallback", False),
                    error=res.get("error"),
                )

            try:
                pages = extract_with_ocr_fallback(tmp_path, recognize_page_fn=recognize_page)
            except Exception as exc:  # noqa: BLE001
                return IngestResult(
                    ok=False,
                    mime=mime,
                    source_url=source_url,
                    content_hash=content_hash,
                    error=f"pdf_extract_failed: {type(exc).__name__}: {str(exc)[:120]}",
                )

            page_count = len(pages)
            # 截断保护
            if page_count > self.max_pdf_pages:
                pages = pages[: self.max_pdf_pages]
            full_text = "\n\n".join(f"[Page {p['page']}]\n{p['text']}" for p in pages if p.get("text"))
            # 综合 confidence(文本层=1.0,OCR 兜底按实际值)
            confidences = [p.get("confidence", 0.0) for p in pages]
            avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
            engines = sorted({p.get("engine", "") for p in pages if p.get("engine")})
            engine_str = ",".join(engines) or "pdfplumber"

            # 写缓存
            payload = {
                "content_hash": content_hash,
                "mime": mime,
                "source_url": source_url,
                "engine": engine_str,
                "confidence": avg_conf,
                "page_count": page_count,
                "text": full_text,
                "saved_at": _now_iso(),
            }
            try:
                self.cache.put(payload)
            except Exception:
                pass

            return IngestResult(
                ok=bool(full_text),
                mime=mime,
                text=full_text,
                engine=engine_str,
                confidence=avg_conf,
                page_count=page_count,
                content_hash=content_hash,
                cached=False,
                source_url=source_url,
            )
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def _ingest_image(
        self,
        content: bytes,
        mime: str,
        source_url: str,
        url_hash: str,
    ) -> IngestResult:
        if not content:
            return IngestResult(ok=False, mime=mime, source_url=source_url, error="empty_image_bytes")

        content_hash = OCRCache.compute_hash(content, mime)

        # 落临时文件 OCREngine 读路径
        import tempfile
        import os
        from pathlib import Path

        suffix = Path(source_url).suffix or ".img"
        # mime → 后缀
        if mime and "png" in mime:
            suffix = ".png"
        elif mime and ("jpeg" in mime or "jpg" in mime):
            suffix = ".jpg"
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
        except Exception as exc:  # noqa: BLE001
            return IngestResult(ok=False, mime=mime, source_url=source_url, error=f"tmp_write_failed: {exc}")

        try:
            try:
                # OCREngine.recognize_image 走完整 PaddleOCR + 云端兜底路由
                res = self.ocr_engine.recognize_image(tmp_path)
            except Exception as exc:  # noqa: BLE001
                return IngestResult(
                    ok=False,
                    mime=mime,
                    source_url=source_url,
                    content_hash=content_hash,
                    error=f"ocr_failed: {type(exc).__name__}: {str(exc)[:120]}",
                )

            text = res.get("text", "") or ""
            confidence = float(res.get("confidence", 0.0) or 0.0)
            engine = res.get("engine", "") or ""

            payload = {
                "content_hash": content_hash,
                "mime": mime,
                "source_url": source_url,
                "engine": engine,
                "confidence": confidence,
                "page_count": 1,
                "text": text,
                "saved_at": _now_iso(),
            }
            try:
                self.cache.put(payload)
            except Exception:
                pass

            return IngestResult(
                ok=bool(text),
                mime=mime,
                text=text,
                engine=engine,
                confidence=confidence,
                page_count=1,
                content_hash=content_hash,
                cached=False,
                source_url=source_url,
            )
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _result_from_cache(cached: Dict[str, Any], mime: str) -> IngestResult:
    return IngestResult(
        ok=True,
        mime=_normalize_mime(cached.get("mime") or mime),
        text=cached.get("text", "") or "",
        engine=cached.get("engine", "") or "",
        confidence=float(cached.get("confidence", 0.0) or 0.0),
        page_count=int(cached.get("page_count", 0) or 0),
        content_hash=cached.get("content_hash", "") or "",
        cached=True,
        source_url=cached.get("source_url", "") or "",
    )


def _now_iso() -> str:
    from datetime import datetime

    return datetime.now().isoformat()