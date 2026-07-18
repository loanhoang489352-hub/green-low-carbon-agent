"""
PDF 文本提取 — PDFPlumber 优先(原生文本层),扫描件走 OCR 兜底

策略:
1. 先用 pdfplumber 抽文本层(快、准、不依赖 OCR)
2. 如果某页文本层为空(或字符数 < 阈值),判定为扫描件
3. 把扫描页转成图片,交给 OCREngine 处理
"""
from __future__ import annotations

import io
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from ingest.ocr_router import OCREngineType, OCRResult

logger = logging.getLogger(__name__)


# 默认:扫描页阈值(字符数 < 此值视为扫描件)
SCAN_PAGE_CHAR_THRESHOLD = 50


def _pdfplumber_available() -> bool:
    try:
        import pdfplumber  # type: ignore  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def extract_text_layer(
    pdf_path: str,
    char_threshold: int = SCAN_PAGE_CHAR_THRESHOLD,
) -> List[Dict[str, Any]]:
    """用 pdfplumber 抽取每页文本;返回 list of {page, text, is_scan, confidence}

    - is_scan=True 的页需要走 OCR 兜底
    - confidence 文本层给 1.0(确定性高)
    """
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(pdf_path)

    if not _pdfplumber_available():
        raise ImportError("pdfplumber 未安装,无法提取 PDF 文本层")

    import pdfplumber  # type: ignore

    pages: List[Dict[str, Any]] = []
    with pdfplumber.open(str(path)) as pdf:
        for idx, page in enumerate(pdf.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception as exc:  # noqa: BLE001
                logger.warning("[pdfplumber] 第 %s 页抽取失败: %s", idx, exc)
                text = ""
            text = text.strip()
            pages.append(
                {
                    "page": idx,
                    "text": text,
                    "is_scan": len(text) < char_threshold,
                    "confidence": 1.0 if text else 0.0,
                    "engine": OCREngineType.PDFPLUMBER.value,
                }
            )
    return pages


def render_page_to_image(
    pdf_path: str,
    page_num: int,
    dpi: int = 200,
) -> bytes:
    """把 PDF 第 page_num 页(1-indexed)转成 PNG 字节流

    优先 pdfplumber + Pillow;回退 pypdfium2;再回退 PyMuPDF。
    """
    if _pdfplumber_available():
        try:
            import pdfplumber  # type: ignore
            from PIL import Image  # type: ignore

            with pdfplumber.open(str(pdf_path)) as pdf:
                page = pdf.pages[page_num - 1]
                img = page.to_image(resolution=dpi)
                buf = io.BytesIO()
                img.original.save(buf, format="PNG")
                return buf.getvalue()
        except Exception as exc:  # noqa: BLE001
            logger.debug("[render] pdfplumber 路径失败,尝试回退: %s", exc)

    # 回退:pypdfium2(常驻系统包)
    try:
        import pypdfium2 as pdfium  # type: ignore

        pdf = pdfium.PdfDocument(str(pdf_path))
        page = pdf[page_num - 1]
        pil_image = page.render(scale=dpi / 72).to_pil()
        buf = io.BytesIO()
        pil_image.save(buf, format="PNG")
        return buf.getvalue()
    except Exception as exc:  # noqa: BLE001
        logger.debug("[render] pypdfium2 路径失败: %s", exc)

    # 再次回退:PyMuPDF(fitz)
    try:
        import fitz  # type: ignore  # PyMuPDF

        doc = fitz.open(str(pdf_path))
        page = doc[page_num - 1]
        pix = page.get_pixmap(dpi=dpi)
        return pix.tobytes("png")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"无法渲染 PDF 第 {page_num} 页: {exc}") from exc


def save_page_image(
    pdf_path: str,
    page_num: int,
    output_path: str,
    dpi: int = 200,
) -> str:
    """渲染并保存为磁盘文件,返回路径(供 OCREngine 直接读)"""
    img_bytes = render_page_to_image(pdf_path, page_num, dpi=dpi)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(img_bytes)
    return output_path


def extract_with_ocr_fallback(
    pdf_path: str,
    recognize_page_fn,
    char_threshold: int = SCAN_PAGE_CHAR_THRESHOLD,
) -> List[Dict[str, Any]]:
    """PDF 提取主入口:文本层 + OCR 兜底

    Args:
        pdf_path: PDF 路径
        recognize_page_fn: callable(pdf_path, page_num) -> OCRResult
            (由 OCREngine 提供,统一封装 PDF → 临时图 → OCR 的流程)
        char_threshold: 扫描页判断阈值

    Returns:
        每页一个 dict: {page, text, confidence, engine, used_fallback}
    """
    text_pages = extract_text_layer(pdf_path, char_threshold=char_threshold)
    out: List[Dict[str, Any]] = []
    for p in text_pages:
        if not p["is_scan"]:
            out.append(
                {
                    "page": p["page"],
                    "text": p["text"],
                    "confidence": p["confidence"],
                    "engine": p["engine"],
                    "used_fallback": False,
                }
            )
            continue

        # 扫描页 → OCR 兜底
        try:
            ocr_result: OCRResult = recognize_page_fn(pdf_path, p["page"])
            out.append(
                {
                    "page": p["page"],
                    "text": ocr_result.text,
                    "confidence": ocr_result.confidence,
                    "engine": ocr_result.engine,
                    "used_fallback": True,
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[pdf_extractor] 第 %s 页 OCR 兜底失败: %s", p["page"], exc)
            out.append(
                {
                    "page": p["page"],
                    "text": "",
                    "confidence": 0.0,
                    "engine": "ocr_failed",
                    "used_fallback": True,
                    "error": str(exc),
                }
            )
    return out