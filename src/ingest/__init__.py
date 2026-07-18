"""
ingest 子包 — 把外部数据(图片 / PDF / HTML)转换为知识库可消费的文本

P9.OCR 模块入口:
- ocr_engine: 统一对外 API
- ocr_router: 本地/云路由(置信度阈值决策)
- image_ocr: 单图片 OCR(PaddleOCR + 阿里云兜底)
- pdf_extractor: PDF 文本层提取 + 扫描件 OCR 兜底

设计原则:
1. 懒加载 — PaddleOCR / 阿里云 SDK 都是重型依赖,首次调用时才 import
2. 可降级 — 云端 key 缺失或本地引擎不可用时,自动回退到备用方案
3. 测试友好 — 所有外部依赖通过抽象层注入,支持 mock
"""

from ingest.ocr_engine import OCREngine, get_ocr_engine, reset_ocr_engine
from ingest.ocr_router import OCRRouter, OCRResult, OCREngineType

__all__ = [
    "OCREngine",
    "get_ocr_engine",
    "reset_ocr_engine",
    "OCRRouter",
    "OCRResult",
    "OCREngineType",
]