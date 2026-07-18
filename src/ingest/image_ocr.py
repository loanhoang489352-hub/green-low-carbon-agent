"""
单图片 OCR — PaddleOCR 本地 + 阿里云兜底

PaddleOCR 3.0 是中文 SOTA,Apache 2.0,免费。
阿里云 OCR 走 ReadOCR 高级版(2026 主流接口),需 ALIYUN_OCR_KEY + ALIYUN_OCR_SECRET。

两个引擎都被设计成"懒加载":首次调用时才 import + 初始化。
PaddleOCR 初始化一次后放进程内单例,避免反复加载模型(~300MB)。
"""
from __future__ import annotations

import base64
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from ingest.ocr_router import OCREngineType, OCRResult

logger = logging.getLogger(__name__)


# ====================================================================== #
# 本地 PaddleOCR
# ====================================================================== #
class _PaddleOCREngine:
    """PaddleOCR 懒加载单例

    - 仅在第一次调用 recognize() 时 import paddleocr(避免启动时 ~300MB 开销)
    - 双检锁保证多线程安全
    - 不可用时(没装 paddleocr / paddlepaddle)返回 None,让上层降级
    """

    _instance: Optional["_PaddleOCREngine"] = None
    _lock = threading.Lock()

    def __init__(self, lang: str = "ch") -> None:
        self.lang = lang
        self._engine: Any = None
        self._available: Optional[bool] = None
        self._import_error: Optional[str] = None

    @classmethod
    def get_instance(cls, lang: str = "ch") -> "_PaddleOCREngine":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(lang=lang)
        return cls._instance

    def _ensure_engine(self) -> bool:
        if self._available is True:
            return True
        if self._available is False:
            return False
        try:
            from paddleocr import PaddleOCR  # type: ignore

            # 3.x: lang / use_doc_orientation / use_doc_unwarping 等参数;
            # 2.x: lang / use_angle_cls。两者 try 兜底。
            try:
                self._engine = PaddleOCR(
                    lang=self.lang, use_doc_orientation=False, use_doc_unwarping=False
                )
            except TypeError:
                self._engine = PaddleOCR(lang=self.lang, use_angle_cls=True)
            self._available = True
            logger.info("[PaddleOCR] 引擎初始化成功 lang=%s", self.lang)
            return True
        except Exception as exc:  # noqa: BLE001
            self._available = False
            self._import_error = str(exc)
            logger.warning(
                "[PaddleOCR] 不可用(本地 OCR 降级为 None): %s", exc
            )
            return False

    @property
    def available(self) -> bool:
        return self._ensure_engine()

    def recognize(self, image_path: str) -> OCRResult:
        if not self._ensure_engine():
            return OCRResult(
                text="",
                confidence=0.0,
                engine=OCREngineType.PADDLEOCR.value,
                error=f"paddleocr_unavailable: {self._import_error}",
            )

        path = Path(image_path)
        if not path.exists():
            return OCRResult(
                text="",
                confidence=0.0,
                engine=OCREngineType.PADDLEOCR.value,
                error=f"file_not_found: {image_path}",
            )

        try:
            # PaddleOCR 3.x 推荐 ocr() 替代 deprecated()
            try:
                result = self._engine.ocr(str(path))
            except AttributeError:
                result = self._engine.ocr(str(path), cls=True)

            lines: List[str] = []
            scores: List[float] = []
            # 3.x: [[[bbox, (text, score)], ...]]
            # 2.x: [[[bbox, (text, score)], ...]]
            for page_res in result or []:
                for item in page_res or []:
                    try:
                        text = item[1][0]
                        score = float(item[1][1])
                        lines.append(text)
                        scores.append(score)
                    except (IndexError, TypeError, ValueError):
                        continue

            text = "\n".join(lines)
            confidence = sum(scores) / len(scores) if scores else 0.0
            return OCRResult(
                text=text,
                confidence=confidence,
                engine=OCREngineType.PADDLEOCR.value,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[PaddleOCR] 识别失败: %s", exc)
            return OCRResult(
                text="",
                confidence=0.0,
                engine=OCREngineType.PADDLEOCR.value,
                error=f"recognize_failed: {exc}",
            )


def recognize_image_local(image_path: str, lang: str = "ch") -> OCRResult:
    """PaddleOCR 识别单张图片"""
    return _PaddleOCREngine.get_instance(lang=lang).recognize(image_path)


# ====================================================================== #
# 云端 阿里云 OCR
# ====================================================================== #
class _AliyunOCREngine:
    """阿里云 OCR 客户端(懒加载)

    用 aliyun-python-sdk-core + aliyun-python-sdk-ocr;
    SDK 缺失 / 凭证缺失时 available=False,上层降级。
    """

    def __init__(self) -> None:
        self._client: Any = None
        self._available: Optional[bool] = None
        self._reason: str = ""

    def _ensure_client(self) -> bool:
        if self._available is True:
            return True
        if self._available is False:
            return False

        ak = os.environ.get("ALIYUN_OCR_KEY", "").strip()
        sk = os.environ.get("ALIYUN_OCR_SECRET", "").strip()
        if not ak or not sk:
            self._available = False
            self._reason = "ALIYUN_OCR_KEY/SECRET 未配置"
            return False

        try:
            from aliyunsdkcore.client import AcsClient  # type: ignore
            from aliyunsdkocr.request.v20191230.RecognizeAdvancedRequest import (  # type: ignore
                RecognizeAdvancedRequest,
            )

            self._client = AcsClient(ak, sk, "cn-shanghai")
            # 保留 request 类供 recognize() 复用
            self._request_cls = RecognizeAdvancedRequest
            self._available = True
            logger.info("[AliyunOCR] 客户端初始化成功")
            return True
        except Exception as exc:  # noqa: BLE001
            self._available = False
            self._reason = str(exc)
            logger.warning("[AliyunOCR] 不可用: %s", exc)
            return False

    @property
    def available(self) -> bool:
        return self._ensure_client()

    def recognize(self, image_path: str) -> OCRResult:
        if not self._ensure_client():
            return OCRResult(
                text="",
                confidence=0.0,
                engine=OCREngineType.ALIYUN.value,
                error=f"aliyun_unavailable: {self._reason}",
            )

        path = Path(image_path)
        if not path.exists():
            return OCRResult(
                text="",
                confidence=0.0,
                engine=OCREngineType.ALIYUN.value,
                error=f"file_not_found: {image_path}",
            )

        try:
            with open(path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode("ascii")

            request = self._request_cls()
            request.set_ImageURL(f"data:image/jpeg;base64,{img_b64}")

            response = self._client.do_action_with_exception(request)
            # 解析 JSON
            try:
                import json

                data = json.loads(response)
            except Exception:  # noqa: BLE001
                # SDK 返回 bytes/str,有时是 JSON 字符串
                data = {}

            content = data.get("Data", {}) or {}
            # 阿里云高级版返回 Content + Prism_OCRData;只取 Content 兜底
            text = (
                content.get("content", "")
                if isinstance(content, dict)
                else str(content)
            )
            # 阿里云不给单字置信度;用整页 0.9 作为"高置信度兜底"
            confidence = float(content.get("confidence", 0.9)) if isinstance(content, dict) else 0.9

            return OCRResult(
                text=text or "",
                confidence=confidence,
                engine=OCREngineType.ALIYUN.value,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[AliyunOCR] 调用失败: %s", exc)
            return OCRResult(
                text="",
                confidence=0.0,
                engine=OCREngineType.ALIYUN.value,
                error=f"aliyun_failed: {exc}",
            )


_aliyun_engine: Optional[_AliyunOCREngine] = None


def _get_aliyun_engine() -> _AliyunOCREngine:
    global _aliyun_engine
    if _aliyun_engine is None:
        _aliyun_engine = _AliyunOCREngine()
    return _aliyun_engine


def recognize_image_cloud(image_path: str) -> OCRResult:
    """阿里云 OCR 识别单张图片(政府公开政策文件,可走云)"""
    return _get_aliyun_engine().recognize(image_path)