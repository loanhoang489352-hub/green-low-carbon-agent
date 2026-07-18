"""
OCR 路由 — 本地/云端决策

策略:
- PaddleOCR 识别 → 拿 confidence
- confidence >= threshold → 直接用本地结果
- confidence < threshold 且云端可用 → 调阿里云 OCR
- 云端 key 缺失 → 跳过,降级用本地(允许低置信度)
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class OCREngineType(str, Enum):
    """OCR 引擎类型"""

    PADDLEOCR = "paddleocr"
    ALIYUN = "aliyun"
    PDFPLUMBER = "pdfplumber"
    HYBRID = "hybrid"  # 路由结果


@dataclass
class OCRResult:
    """OCR 识别结果(单张图或单页)"""

    text: str
    confidence: float
    engine: str
    page: Optional[int] = None
    used_fallback: bool = False
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "confidence": round(self.confidence, 4),
            "engine": self.engine,
            "page": self.page,
            "used_fallback": self.used_fallback,
            "error": self.error,
        }


class OCRRouter:
    """OCR 路由 — 置信度阈值决策 + 引擎降级

    Args:
        confidence_threshold: 本地结果可接受的最低置信度;低于此值会尝试云端
        cloud_fallback: 是否允许云端兜底
    """

    def __init__(
        self,
        confidence_threshold: float = 0.6,
        cloud_fallback: bool = True,
    ) -> None:
        if not 0.0 <= confidence_threshold <= 1.0:
            raise ValueError(
                f"confidence_threshold 必须在 [0, 1],得到 {confidence_threshold}"
            )
        self.confidence_threshold = confidence_threshold
        self.cloud_fallback = cloud_fallback

    # ------------------------------------------------------------------ #
    # 路由决策
    # ------------------------------------------------------------------ #
    def should_use_cloud(self, local_result: OCRResult) -> bool:
        """根据本地结果判断是否需要云端兜底"""
        if not self.cloud_fallback:
            return False
        if local_result.error:
            return True  # 本地出错,试试云端
        return local_result.confidence < self.confidence_threshold

    def is_cloud_available(self) -> bool:
        """检查云端 OCR 凭证是否齐全"""
        ak = os.environ.get("ALIYUN_OCR_KEY", "").strip()
        sk = os.environ.get("ALIYUN_OCR_SECRET", "").strip()
        # 占位符视为未配置
        if not ak or not sk:
            return False
        placeholders = ("__SET_ME__", "your_access_key", "your_secret_key")
        if any(p.lower() in ak.lower() for p in placeholders):
            return False
        if any(p.lower() in sk.lower() for p in placeholders):
            return False
        return True

    def merge_results(
        self,
        local: OCRResult,
        cloud: OCRResult,
    ) -> OCRResult:
        """本地 + 云端都成功时,选置信度更高的"""
        if local.confidence >= cloud.confidence:
            local.used_fallback = False
            return local
        cloud.used_fallback = True
        cloud.engine = f"{OCREngineType.HYBRID.value}(cloud)"
        return cloud

    def route(
        self,
        local_result: OCRResult,
        cloud_result_factory: Optional[Any] = None,
    ) -> OCRResult:
        """决策入口:拿本地结果,必要时调云端

        Args:
            local_result: PaddleOCR 已跑出的结果
            cloud_result_factory: 调用云端 OCR 的可调用对象(测试时可注入 mock)
        """
        if not self.should_use_cloud(local_result):
            return local_result

        # 需云端兜底
        if not self.is_cloud_available():
            logger.info(
                "[OCRRouter] 置信度 %s < %s 但云端 key 未配置,降级使用本地结果",
                local_result.confidence,
                self.confidence_threshold,
            )
            local_result.used_fallback = False
            return local_result

        if cloud_result_factory is None:
            logger.warning(
                "[OCRRouter] 未提供 cloud_result_factory,降级使用本地结果"
            )
            local_result.used_fallback = False
            return local_result

        try:
            cloud_result = cloud_result_factory()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[OCRRouter] 云端 OCR 调用失败,降级使用本地结果: %s", exc
            )
            local_result.used_fallback = False
            local_result.error = f"cloud_failed: {exc}"
            return local_result

        if cloud_result.error:
            logger.warning(
                "[OCRRouter] 云端 OCR 返回错误,降级使用本地结果: %s",
                cloud_result.error,
            )
            local_result.used_fallback = False
            return local_result

        return self.merge_results(local_result, cloud_result)

    # ------------------------------------------------------------------ #
    # 批量路由(给 PDF 多页用)
    # ------------------------------------------------------------------ #
    def route_batch(
        self,
        local_results: List[OCRResult],
        cloud_factory_for_page: Optional[Any] = None,
    ) -> List[OCRResult]:
        """对每页分别决策;cloud_factory_for_page(page_idx) → OCRResult"""
        out: List[OCRResult] = []
        for local in local_results:
            factory = (
                (lambda idx=local.page: cloud_factory_for_page(idx))
                if callable(cloud_factory_for_page)
                else None
            )
            out.append(self.route(local, factory))
        return out