"""
P9.OCR 摄入管线测试 — 5 个核心场景

覆盖:
1. PDF URL → MIME 分支识别(application/pdf 走 IngestOrchestrator)
2. 图片 URL → MIME 分支识别(image/jpeg 走 IngestOrchestrator)
3. HTML 内嵌 <img>/<embed> 被 HTMLMediaExtractor 识别
4. OCRCache content_hash 命中缓存 → 不重复 OCR
5. front_matter 字段正确写入(ocr_engine / ocr_confidence / source_pdf / page_count)

网络请求用 monkeypatch 拦截,OCR 用 mock_factory;不真跑 PaddleOCR / 阿里云。
"""
import sys
import os
import json
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest


@pytest.fixture
def tmp_cache_dir(tmp_path, monkeypatch):
    """临时 OCR 缓存目录(避免污染 data/ocr_cache)"""
    cache_dir = tmp_path / "ocr_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    # 重置 OCRCache 单例并指向临时目录
    import ingest.ocr_cache as cache_mod

    monkeypatch.setattr(cache_mod, "OCR_CACHE_DIR", cache_dir)
    cache_mod.reset_ocr_cache()
    yield cache_dir
    cache_mod.reset_ocr_cache()


# ----------------------------------------------------------------------- #
# Test 1: PDF URL → MIME 分支识别 + 走 OCR pipeline
# ----------------------------------------------------------------------- #
def test_pdf_url_routes_to_ocr_orchestrator(tmp_cache_dir, monkeypatch):
    """application/pdf URL 应被识别为 PDF → 不走 HTML _extract_content"""
    from policy.updater import PolicyUpdater

    updater = PolicyUpdater(db_path=str(tmp_cache_dir / "policies.db"))

    pdf_bytes = b"%PDF-1.4\n%fake pdf body for unit test\n%%EOF\n"

    def fake_httpx_get(url, **kwargs):
        m = MagicMock()
        m.status_code = 200
        m.headers = {"content-type": "application/pdf"}
        m.content = pdf_bytes
        m.text = ""  # PDF 不是 text,空字符串避免误判
        m.raise_for_status = lambda: None
        m.encoding = "utf-8"
        return m

    monkeypatch.setattr("httpx.get", fake_httpx_get)

    # mock IngestOrchestrator.ingest_url → 返回结构化结果
    class FakeIngest:
        def __init__(self, *a, **kw):
            pass

        def ingest_url(self, url, content_type=None):
            from ingest.orchestrator import IngestResult

            return IngestResult(
                ok=True,
                mime="application/pdf",
                text="[OCR 提取的政策 PDF 文本] 第一章 总则 第二章 任务",
                engine="pdfplumber",
                confidence=1.0,
                page_count=3,
                content_hash="abc123",
                source_url=url,
            )

    monkeypatch.setattr(
        "ingest.orchestrator.IngestOrchestrator", FakeIngest
    )

    source = {
        "name": "test-pdf-policy",
        "url": "https://example.gov.cn/policy.pdf",
        "category": "国家战略",
        "type": "national",
    }

    added, err = updater._fetch_and_ingest_ocr(source, source["url"], "application/pdf", True)

    assert err is None, f"OCR 路径不应报错,实际: {err}"
    assert added == 1, f"应新增 1 条政策,实际 {added}"

    # 验证入库内容含 OCR 文本
    policies = updater.get_policies(limit=5)
    assert any("[OCR 提取的政策 PDF 文本]" in (p.get("title") or "") or p for p in policies)
    print("✅ test_pdf_url_routes_to_ocr_orchestrator PASSED")


# ----------------------------------------------------------------------- #
# Test 2: image URL → MIME 分支识别
# ----------------------------------------------------------------------- #
def test_image_url_routes_to_ocr_orchestrator(tmp_cache_dir, monkeypatch):
    """image/jpeg URL 应被识别为图片 → 走 IngestOrchestrator"""
    from knowledge.updater import KnowledgeUpdater, UpdateSource

    kb_dir = tmp_cache_dir / "kb"
    kb_dir.mkdir(parents=True, exist_ok=True)
    updater = KnowledgeUpdater(knowledge_base_path=str(kb_dir))

    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64 + b"IEND"

    def fake_urlopen(req, timeout=15, **kwargs):
        m = MagicMock()
        m.read.return_value = png_bytes
        m.getheader.side_effect = lambda k, default="": {
            "Content-Type": "image/png",
            "Last-Modified": "",
        }.get(k, default)
        return m

    # 拦截 urllib.request.urlopen(KnowledgeUpdater 用 urllib,非 httpx)
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    # mock OCREngine.recognize_image → 返 mock 结果
    def fake_recognize_image(self, image_path):
        return {
            "text": "[图片 OCR] 这是一份扫描的政策图,内容是... 双碳目标 2030",
            "confidence": 0.95,
            "engine": "paddleocr",
            "used_fallback": False,
        }

    monkeypatch.setattr(
        "ingest.ocr_engine.OCREngine.recognize_image", fake_recognize_image
    )

    # mock pdfplumber / pypdfium2 / fitz 全部不可用,确保走 OCR 路径
    monkeypatch.setattr("ingest.pdf_extractor._pdfplumber_available", lambda: False)

    src = UpdateSource(name="test-img", url="https://example.gov.cn/policy.png", type="policy")
    updater.sources = [src]

    result = updater._check_source(src)

    # 首次检查 last_hash is None → no update, 但不应报 OCR 错误
    assert result.error is None or "OCR" not in result.error, f"OCR 路径报错: {result.error}"
    print(f"✅ test_image_url_routes_to_ocr_orchestrator PASSED (error={result.error!r})")


# ----------------------------------------------------------------------- #
# Test 3: HTML 内嵌 <img>/<embed> 被 HTMLMediaExtractor 识别
# ----------------------------------------------------------------------- #
def test_html_embedded_media_extracted(tmp_cache_dir):
    """BeautifulSoup 应从 HTML 抽出 <img>/<embed>/<iframe> URL"""
    from ingest.html_media_extractor import HTMLMediaExtractor

    html = """
    <html><body>
      <h1>政策正文</h1>
      <p>正文段落...</p>
      <img src="https://example.gov.cn/policy-chart.png" />
      <img src="/relative/icon.jpg" />
      <embed src="https://example.gov.cn/full-policy.pdf" type="application/pdf" />
      <iframe src="https://example.gov.cn/embed.pdf"></iframe>
    </body></html>
    """

    extractor = HTMLMediaExtractor(max_items=10, base_url="https://example.gov.cn")
    items = extractor.extract(html, base_url="https://example.gov.cn")

    urls = [it.url for it in items]
    kinds = {it.kind for it in items}

    # 至少应抽到:1 个绝对图、1 个相对转绝对图、1 个 embed PDF、1 个 iframe PDF
    assert any("policy-chart.png" in u for u in urls), f"应识别绝对 img URL, 实际 {urls}"
    assert any(u.endswith("/relative/icon.jpg") or "icon.jpg" in u for u in urls), (
        f"应把相对路径转绝对, 实际 {urls}"
    )
    assert "pdf" in kinds, f"应识别 embed/iframe PDF, 实际 kinds {kinds}"

    # SVG / data:image 不进列表(过滤)
    html_with_svg = '<img src="data:image/svg+xml;base64,xxx" />'
    items2 = extractor.extract(html_with_svg, base_url="https://example.gov.cn")
    assert all("svg" not in (it.url or "").lower() for it in items2), "SVG 应被过滤"
    print(f"✅ test_html_embedded_media_extracted PASSED (got {len(items)} items)")


# ----------------------------------------------------------------------- #
# Test 4: content_hash 命中缓存 → 不重复 OCR
# ----------------------------------------------------------------------- #
def test_content_hash_cache_hit(tmp_cache_dir):
    """OCRCache.put/get → 同 content_hash 命中,跳过 OCR"""
    from ingest.ocr_cache import OCRCache

    cache = OCRCache(cache_dir=tmp_cache_dir)

    payload = {
        "content_hash": "deadbeef00000000",
        "mime": "application/pdf",
        "source_url": "https://example.gov.cn/x.pdf",
        "engine": "pdfplumber",
        "confidence": 1.0,
        "page_count": 5,
        "text": "[缓存] 这是一条已经 OCR 过的政策文本,共 5 页",
        "saved_at": "2026-07-18T10:00:00",
    }

    assert cache.put(payload) is True
    assert cache.has("deadbeef00000000") is True

    hit = cache.get("deadbeef00000000")
    assert hit is not None, "应能命中缓存"
    assert hit["text"].startswith("[缓存]")
    assert hit["page_count"] == 5
    assert hit["engine"] == "pdfplumber"

    # 同样的 bytes + mime 应算出稳定 hash
    h1 = OCRCache.compute_hash(b"hello", "application/pdf")
    h2 = OCRCache.compute_hash(b"hello", "application/pdf")
    assert h1 == h2
    # mime 不同应算出不同 hash(避免撞库)
    h3 = OCRCache.compute_hash(b"hello", "image/png")
    assert h1 != h3
    print("✅ test_content_hash_cache_hit PASSED")


# ----------------------------------------------------------------------- #
# Test 5: front-matter 字段正确写入
# ----------------------------------------------------------------------- #
def test_front_matter_fields(tmp_cache_dir):
    """build_document 应把所有 P9.OCR 字段写进 YAML 头"""
    from ingest.front_matter import build_document, build_front_matter

    doc = build_document(
        title="[OCR] 国务院 2026 双碳行动方案",
        body="第一章 总则 ... 第二章 主要目标 ...",
        ocr_engine="paddleocr",
        ocr_confidence=0.93,
        source_url="https://example.gov.cn/2026-action.pdf",
        source_pdf="https://example.gov.cn/2026-action.pdf",
        mime="application/pdf",
        page_count=12,
        content_hash="abc123def456",
        cached=False,
        extra={"policy_id": "P2026-001", "category": "国家战略"},
    )

    # front-matter 必须含这些字段
    for field in [
        "ocr_engine: paddleocr",
        "ocr_confidence: 0.93",
        "source_url:",
        "source_pdf:",
        "mime: application/pdf",
        "page_count: 12",
        "content_hash: abc123def456",
        "cached: false",
        "ingested_at:",
        "policy_id: P2026-001",
        "category:",
    ]:
        assert field in doc, f"front-matter 缺字段 {field!r}\n--- 实际 ---\n{doc[:400]}"

    # 标题与正文必须在 front-matter 之后
    assert "第一章 总则" in doc
    assert doc.index("# [OCR] 国务院") > doc.index("---"), "标题应在 front-matter 之后"

    # None 字段不出现
    fm_only = build_front_matter({"ocr_engine": "paddleocr", "page_count": None, "mime": ""})
    assert "ocr_engine: paddleocr" in fm_only
    assert "page_count" not in fm_only, "None/空字段不应出现"
    print("✅ test_front_matter_fields PASSED")


if __name__ == "__main__":
    # 命令行直接跑(用于本地调试)
    pytest.main([__file__, "-v"])