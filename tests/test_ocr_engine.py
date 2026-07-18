"""
P9.OCR — OCREngine 单元测试

设计原则:
- 所有外部依赖(PaddleOCR / 阿里云 OCR / pdfplumber)通过 monkeypatch 注入 mock
- 不依赖真实 OCR 模型 / 网络(运行轻量)
- 覆盖本地/云/降级/扫描件等关键路径
"""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 强制 ingest 模块可见
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


# ========================================================================== #
# Fixtures
# ========================================================================== #
@pytest.fixture
def tmp_image(tmp_path):
    """造一个 1x1 PNG 占位文件(不校验内容,只校验 OCR 是否被调用)"""
    p = tmp_path / "fixture.png"
    # 最小合法 PNG:1x1 灰度
    p.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x00\x00\x00\x00:~\x9bU"
        b"\x00\x00\x00\nIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01"
        b"\x18\xdd\x8d\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    return str(p)


@pytest.fixture(autouse=True)
def clean_aliyun_env(monkeypatch):
    """默认清空 aliyun env,各测试按需再 set"""
    monkeypatch.delenv("ALIYUN_OCR_KEY", raising=False)
    monkeypatch.delenv("ALIYUN_OCR_SECRET", raising=False)


# ========================================================================== #
# 1. 图片 OCR:本地 PaddleOCR(mock,直接 patch recognize_image_local)
# ========================================================================== #
def test_recognize_image_local_high_confidence(tmp_image, monkeypatch):
    """高置信度直接返回本地结果,engine=paddleocr"""
    from ingest import ocr_engine
    from ingest.ocr_router import OCRResult

    # 注意:ocr_engine 在 import 时把 recognize_image_local 绑定到本地名字空间,
    # 所以必须 patch ingest.ocr_engine.recognize_image_local 而非 image_ocr 模块。
    monkeypatch.setattr(
        "ingest.ocr_engine.recognize_image_local",
        lambda path, lang="ch": OCRResult(
            text="低碳生活从我做起", confidence=0.92, engine="paddleocr"
        ),
    )

    eng = ocr_engine.OCREngine(cloud_fallback=False)
    result = eng.recognize_image(tmp_image)

    assert result["engine"] == "paddleocr"
    assert result["confidence"] == pytest.approx(0.92, abs=1e-3)
    assert "低碳" in result["text"]
    assert result["used_fallback"] is False
    print("✅ test_recognize_image_local_high_confidence PASSED")


# ========================================================================== #
# 2. 置信度阈值触发云端
# ========================================================================== #
def test_recognize_image_low_confidence_triggers_cloud(tmp_image, monkeypatch):
    """低置信度 → router 自动调云端(用 mock 替换云端)"""
    from ingest import ocr_engine
    from ingest.ocr_router import OCRResult

    # 本地:低置信度 0.3
    monkeypatch.setattr(
        "ingest.ocr_engine.recognize_image_local",
        lambda path, lang="ch": OCRResult(
            text="低质量本地", confidence=0.3, engine="paddleocr"
        ),
    )

    # 配 key + patch 云端
    monkeypatch.setenv("ALIYUN_OCR_KEY", "fake_ak_1234567890")
    monkeypatch.setenv("ALIYUN_OCR_SECRET", "fake_sk_1234567890")

    def fake_cloud(path):
        return OCRResult(text="云端识别:碳达峰", confidence=0.95, engine="aliyun")

    monkeypatch.setattr("ingest.ocr_engine.recognize_image_cloud", fake_cloud)

    eng = ocr_engine.OCREngine(confidence_threshold=0.6)
    result = eng.recognize_image(tmp_image)

    # 云端分高,被采纳
    assert result["engine"].startswith("hybrid") or result["engine"] == "aliyun"
    assert result["confidence"] == pytest.approx(0.95, abs=1e-3)
    assert "云端" in result["text"]
    assert result["used_fallback"] is True
    print("✅ test_recognize_image_low_confidence_triggers_cloud PASSED")


# ========================================================================== #
# 3. 云端 key 缺失 → 降级用本地
# ========================================================================== #
def test_recognize_image_no_cloud_key_falls_back_to_local(tmp_image, monkeypatch):
    """key 未配置 → 即使低置信度,也不调云端,直接返本地"""
    from ingest import ocr_engine
    from ingest.ocr_router import OCRResult

    monkeypatch.setattr(
        "ingest.ocr_engine.recognize_image_local",
        lambda path, lang="ch": OCRResult(
            text="本地结果", confidence=0.3, engine="paddleocr"
        ),
    )

    eng = ocr_engine.OCREngine(confidence_threshold=0.6)
    assert eng.router.is_cloud_available() is False

    result = eng.recognize_image(tmp_image)
    assert result["engine"] == "paddleocr"
    assert result["confidence"] == pytest.approx(0.3, abs=1e-3)
    assert result["used_fallback"] is False
    print("✅ test_recognize_image_no_cloud_key_falls_back_to_local PASSED")


# ========================================================================== #
# 4. 云端 key 是占位符 → 也算未配置
# ========================================================================== #
def test_cloud_router_rejects_placeholder_keys(monkeypatch):
    """ALIYUN_OCR_KEY=__SET_ME__ / your_access_key → 视为未配置"""
    from ingest.ocr_router import OCRRouter

    monkeypatch.setenv("ALIYUN_OCR_KEY", "__SET_ME__")
    monkeypatch.setenv("ALIYUN_OCR_SECRET", "your_secret_key")

    router = OCRRouter()
    assert router.is_cloud_available() is False
    print("✅ test_cloud_router_rejects_placeholder_keys PASSED")


# ========================================================================== #
# 5. PDF 文本层提取(pdfplumber mock)
# ========================================================================== #
def test_extract_pdf_text_layer_only(monkeypatch, tmp_path):
    """PDF 全部是文本层 → OCR 不应被调用,直接拿 pdfplumber 结果"""
    from ingest import ocr_engine

    fake_pdf_pages = [
        {"page": 1, "text": "第一章 低碳生活", "is_scan": False, "confidence": 1.0, "engine": "pdfplumber"},
        {"page": 2, "text": "第二章 绿色出行", "is_scan": False, "confidence": 1.0, "engine": "pdfplumber"},
    ]

    monkeypatch.setattr(
        "ingest.pdf_extractor.extract_text_layer",
        lambda *a, **kw: fake_pdf_pages,
    )
    # OCR 不应被调用
    ocr_called = {"count": 0}

    def should_not_run(*a, **kw):
        ocr_called["count"] += 1
        raise AssertionError("OCR 不应在文本层完整时被调用")

    monkeypatch.setattr("ingest.ocr_engine.recognize_image_local", should_not_run)

    pdf_path = tmp_path / "fake.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")  # 占位内容

    eng = ocr_engine.OCREngine()
    pages = eng.extract_pdf(str(pdf_path))

    assert len(pages) == 2
    assert pages[0]["text"] == "第一章 低碳生活"
    assert pages[0]["used_fallback"] is False
    assert pages[0]["engine"] == "pdfplumber"
    assert ocr_called["count"] == 0
    print("✅ test_extract_pdf_text_layer_only PASSED")


# ========================================================================== #
# 6. PDF 扫描件 OCR 兜底
# ========================================================================== #
def test_extract_pdf_scan_page_falls_back_to_ocr(monkeypatch, tmp_path):
    """扫描页 → is_scan=True → 应走 OCR;render 路径也要 mock"""
    from ingest import ocr_engine
    from ingest.ocr_router import OCRResult

    # 文本层:第 1 页是文本,第 2 页是扫描
    fake_pdf_pages = [
        {"page": 1, "text": "首页正文", "is_scan": False, "confidence": 1.0, "engine": "pdfplumber"},
        {"page": 2, "text": "", "is_scan": True, "confidence": 0.0, "engine": "pdfplumber"},
    ]
    monkeypatch.setattr(
        "ingest.pdf_extractor.extract_text_layer",
        lambda *a, **kw: fake_pdf_pages,
    )

    # 渲染 PDF → 图:跳过实际渲染,直接返回路径
    # 注意:save_page_image 在 ocr_engine 内部被引用为本地名字,patch 在 ocr_engine 模块
    monkeypatch.setattr(
        "ingest.ocr_engine.save_page_image",
        lambda pdf, page_num, output_path, dpi=200: output_path,
    )

    # OCR 本地 mock
    monkeypatch.setattr(
        "ingest.ocr_engine.recognize_image_local",
        lambda path, lang="ch": OCRResult(
            text="OCR识别:碳达峰碳中和", confidence=0.88, engine="paddleocr"
        ),
    )

    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

    eng = ocr_engine.OCREngine(cloud_fallback=False)
    pages = eng.extract_pdf(str(pdf_path))

    assert len(pages) == 2
    assert pages[0]["text"] == "首页正文"
    assert pages[0]["used_fallback"] is False

    assert pages[1]["text"] == "OCR识别:碳达峰碳中和"
    assert pages[1]["used_fallback"] is True
    assert pages[1]["engine"] == "paddleocr"
    assert pages[1]["confidence"] == pytest.approx(0.88, abs=1e-3)
    print("✅ test_extract_pdf_scan_page_falls_back_to_ocr PASSED")


# ========================================================================== #
# 7. PDF 文件不存在
# ========================================================================== #
def test_extract_pdf_file_not_found():
    """路径不存在 → FileNotFoundError"""
    from ingest import ocr_engine

    eng = ocr_engine.OCREngine()
    with pytest.raises(FileNotFoundError):
        eng.extract_pdf("D:/this/does/not/exist.pdf")
    print("✅ test_extract_pdf_file_not_found PASSED")


# ========================================================================== #
# 8. Router 决策逻辑(纯单元,无 I/O)
# ========================================================================== #
def test_router_decision_logic():
    """OCRRouter.should_use_cloud 单测"""
    from ingest.ocr_router import OCRResult, OCRRouter

    router = OCRRouter(confidence_threshold=0.6, cloud_fallback=True)

    # 高置信度 → 不需云端
    high = OCRResult(text="x", confidence=0.9, engine="paddleocr")
    assert router.should_use_cloud(high) is False

    # 低置信度 → 需要云端
    low = OCRResult(text="x", confidence=0.4, engine="paddleocr")
    assert router.should_use_cloud(low) is True

    # 本地报错 → 也要云端
    err = OCRResult(text="", confidence=0.0, engine="paddleocr", error="oops")
    assert router.should_use_cloud(err) is True

    # 关闭 cloud_fallback → 永不调云端
    router_off = OCRRouter(confidence_threshold=0.6, cloud_fallback=False)
    assert router_off.should_use_cloud(low) is False
    print("✅ test_router_decision_logic PASSED")


# ========================================================================== #
# 9. 单例工厂
# ========================================================================== #
def test_ocr_engine_singleton():
    """get_ocr_engine 同一进程内返回同一实例"""
    from ingest import ocr_engine

    ocr_engine.reset_ocr_engine()
    e1 = ocr_engine.get_ocr_engine()
    e2 = ocr_engine.get_ocr_engine()
    assert e1 is e2
    print("✅ test_ocr_engine_singleton PASSED")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])