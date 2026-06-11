"""
P6.J 源可达性测试脚本 单元测试

覆盖:
1. test_source() 基础测试(status 200 → ok=True)
2. test_source() 错误处理(网络错误 → ok=False + error 字段)
3. test_source() 关键词命中计数
4. test_source() 大小阈值过滤
5. load_yaml_sources() 解析
6. render_report() 生成 md
7. 候选源 10 个(端到端,可能因网络不同结果)
"""
import sys
import time
from pathlib import Path
from unittest import mock

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / 'src'))

import pytest


# ========== 1. test_source 基础 ==========

def test_test_source_success_200():
    """status 200 + 大小 > 阈值 + 关键词命中 → ok=True"""
    from scripts.test_new_sources import test_source

    mock_response = mock.MagicMock()
    mock_response.status_code = 200
    # httpx Response.content 是 bytes, .text 是 str
    mock_text = "碳中和 低碳 绿色 能源 减排 气候变化 可持续发展 环保 政策" * 200
    mock_response.content = mock_text.encode("utf-8")  # ~10 KB > 5KB 阈值
    mock_response.text = mock_text

    class MockClient:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return None
        def get(self, *a, **kw): return mock_response

    source = {
        "name": "test", "url": "http://example.com",
        "type": "html", "category": "test",
        "keywords": ["碳", "低碳"],
    }
    with mock.patch("httpx.Client", MockClient):
        result = test_source(source, timeout=5.0)
    assert result["test"]["ok"] is True
    assert result["test"]["status_code"] == 200
    assert result["test"]["keyword_hits"] >= 2


def test_test_source_status_404():
    """status 404 → ok=False"""
    from scripts.test_new_sources import test_source

    mock_response = mock.MagicMock()
    mock_response.status_code = 404

    class MockClient:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return None
        def get(self, *a, **kw): return mock_response

    source = {
        "name": "test", "url": "http://example.com",
        "type": "html", "category": "test", "keywords": [],
    }
    with mock.patch("httpx.Client", MockClient):
        result = test_source(source)
    assert result["test"]["ok"] is False
    assert result["test"]["status_code"] == 404


def test_test_source_network_error():
    """网络错误 → ok=False + error 字段"""
    from scripts.test_new_sources import test_source
    import httpx

    class MockClient:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return None
        def get(self, *a, **kw):
            raise httpx.ConnectError("Connection refused")

    source = {
        "name": "test", "url": "http://nonexistent.example.com",
        "type": "html", "category": "test", "keywords": [],
    }
    with mock.patch("httpx.Client", MockClient):
        result = test_source(source)
    assert result["test"]["ok"] is False
    assert "ConnectError" in result["test"]["error"]


def test_test_source_size_below_threshold():
    """响应 < min_size_kb → ok=False(即使 status 200)"""
    from scripts.test_new_sources import test_source

    mock_response = mock.MagicMock()
    mock_response.status_code = 200
    mock_response.text = "短"  # 1 KB < 5 KB 阈值

    class MockClient:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return None
        def get(self, *a, **kw): return mock_response

    source = {
        "name": "test", "url": "http://example.com",
        "type": "html", "category": "test", "keywords": ["碳"],
    }
    with mock.patch("httpx.Client", MockClient):
        result = test_source(source, min_size_kb=5.0)
    assert result["test"]["ok"] is False
    assert result["test"]["size_kb"] < 5


def test_test_source_no_keyword_hits():
    """status 200 + 大小够 + 关键词 0 命中 → ok=False"""
    from scripts.test_new_sources import test_source

    mock_response = mock.MagicMock()
    mock_response.status_code = 200
    mock_response.text = "随机内容" * 1000  # ~10 KB,无关键词

    class MockClient:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return None
        def get(self, *a, **kw): return mock_response

    source = {
        "name": "test", "url": "http://example.com",
        "type": "html", "category": "test",
        "keywords": ["碳", "绿色", "低碳", "能源"],
    }
    with mock.patch("httpx.Client", MockClient):
        result = test_source(source)
    assert result["test"]["ok"] is False
    assert result["test"]["keyword_hits"] == 0


# ========== 2. 报告生成 ==========

def test_render_report_basic(tmp_path):
    """render_report() 写 md 文件"""
    from scripts.test_new_sources import render_report

    results = [
        {
            "name": "src1", "url": "http://a.com", "type": "html", "category": "test",
            "note": "test note",
            "test": {"ok": True, "status_code": 200, "size_kb": 50.0, "keyword_hits": 3, "latency_ms": 100, "error": None},
        },
        {
            "name": "src2", "url": "http://b.com", "type": "html", "category": "test",
            "note": "test note 2",
            "test": {"ok": False, "status_code": 0, "size_kb": 0, "keyword_hits": 0, "latency_ms": 50, "error": "ConnectError"},
        },
    ]
    report_path = tmp_path / "report.md"
    render_report(results, report_path)
    assert report_path.exists()
    content = report_path.read_text(encoding="utf-8")
    assert "# 源可达性测试报告" in content
    assert "src1" in content
    assert "src2" in content
    assert "建议启用" in content
    assert "不可用源" in content


# ========== 3. YAML 加载 ==========

def test_load_yaml_sources():
    """load_yaml_sources() 解析 enabled 源"""
    from scripts.test_new_sources import load_yaml_sources
    sources = load_yaml_sources()
    # 真实 config 至少有 10 个 enabled 源
    assert isinstance(sources, list)
    assert len(sources) > 5, f"应至少 5 个 enabled 源, 实际 {len(sources)}"
    # 所有源都有 url
    for s in sources:
        assert "url" in s, f"源缺 url: {s}"


# ========== 4. 候选源结构 ==========

def test_candidate_sources_structure():
    """P6.J: 候选源列表 10 个,每个有 url + keywords + category"""
    from scripts.test_new_sources import CANDIDATE_SOURCES
    assert len(CANDIDATE_SOURCES) == 10, f"候选源应 10 个, 实际 {len(CANDIDATE_SOURCES)}"
    for s in CANDIDATE_SOURCES:
        assert "name" in s
        assert "url" in s
        assert "keywords" in s
        assert len(s["keywords"]) > 0
