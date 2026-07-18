"""
OCR 引擎统一对外 API

职责:
- 编排 PaddleOCR 本地 + 阿里云云端
- 对外暴露 recognize_image / extract_pdf 两个稳定接口
- 内部通过 OCRRouter 做置信度路由
- 单例懒加载,避免重复初始化 PaddleOCR 模型
"""
from __future__ import annotations

import logging
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from ingest.image_ocr import recognize_image_cloud, recognize_image_local
from ingest.ocr_router import OCREngineType, OCRResult, OCRRouter
from ingest.pdf_extractor import extract_with_ocr_fallback, save_page_image

logger = logging.getLogger(__name__)


class OCREngine:
    """OCR 引擎(PaddleOCR 本地 + 阿里云兜底)

    Args:
        use_local: 是否启用本地 PaddleOCR(默认 True)
        cloud_fallback: 置信度不足时是否尝试云端(默认 True)
        lang: PaddleOCR 语言,默认 ch(中文)
        confidence_threshold: 本地结果可接受的最低置信度;低于此值会尝试云端
        work_dir: OCR 中间文件(如 PDF 临时图)输出目录,默认系统 temp
    """

    def __init__(
        self,
        use_local: bool = True,
        cloud_fallback: bool = True,
        lang: str = "ch",
        confidence_threshold: float = 0.6,
        work_dir: Optional[str] = None,
    ) -> None:
        self.use_local = use_local
        self.cloud_fallback = cloud_fallback
        self.lang = lang
        self.work_dir = work_dir
        self.router = OCRRouter(
            confidence_threshold=confidence_threshold,
            cloud_fallback=cloud_fallback,
        )

    # ------------------------------------------------------------------ #
    # 图片 OCR
    # ------------------------------------------------------------------ #
    def recognize_image(self, image_path: str) -> Dict[str, Any]:
        """识别单张图片

        Returns:
            {"text": str, "confidence": float, "engine": "paddleocr"|"aliyun"|"hybrid", ...}
        """
        local_result: OCRResult = (
            recognize_image_local(image_path, lang=self.lang)
            if self.use_local
            else OCRResult(
                text="",
                confidence=0.0,
                engine="disabled",
                error="use_local=False",
            )
        )

        def _call_cloud() -> OCRResult:
            return recognize_image_cloud(image_path)

        routed = self.router.route(local_result, cloud_result_factory=_call_cloud)
        return routed.to_dict()

    # ------------------------------------------------------------------ #
    # PDF OCR
    # ------------------------------------------------------------------ #
    def extract_pdf(self, pdf_path: str) -> List[Dict[str, Any]]:
        """提取 PDF 文本(文本层 + 扫描件 OCR 兜底)

        Returns:
            list of {"page": int, "text": str, "confidence": float, "engine": str, "used_fallback": bool}
        """
        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(pdf_path)

        work_root = Path(self.work_dir) if self.work_dir else Path(tempfile.gettempdir())
        work_root.mkdir(parents=True, exist_ok=True)

        def recognize_page(pdf_path: str, page_num: int) -> OCRResult:
            """单页 → 渲染为图 → OCREngine 完整路由"""
            tmp_dir = work_root / f"ocr_pdf_{Path(pdf_path).stem}"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            tmp_img = tmp_dir / f"page_{page_num}.png"
            save_page_image(pdf_path, page_num, str(tmp_img))
            res = self.recognize_image(str(tmp_img))
            return OCRResult(
                text=res["text"],
                confidence=res["confidence"],
                engine=res["engine"],
                page=page_num,
                used_fallback=res.get("used_fallback", False),
                error=res.get("error"),
            )

        return extract_with_ocr_fallback(pdf_path, recognize_page_fn=recognize_page)


# ====================================================================== #
# 单例工厂
# ====================================================================== #
_engine: Optional[OCREngine] = None
_engine_lock = threading.Lock()


def get_ocr_engine(
    use_local: bool = True,
    cloud_fallback: bool = True,
    lang: str = "ch",
    confidence_threshold: float = 0.6,
) -> OCREngine:
    """获取 OCREngine 单例

    注意:首次调用时按 (use_local, cloud_fallback, lang, threshold) 缓存;
    后续传不同参数会沿用第一次的配置(避免误用),需要切配置请显式 reset。
    """
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = OCREngine(
                    use_local=use_local,
                    cloud_fallback=cloud_fallback,
                    lang=lang,
                    confidence_threshold=confidence_threshold,
                )
    return _engine


def reset_ocr_engine() -> None:
    """重置单例(测试用)"""
    global _engine
    with _engine_lock:
        _engine = None