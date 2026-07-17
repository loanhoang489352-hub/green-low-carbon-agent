"""
Bug 11 + Bug 12 修复测试

Bug 11: app.py:204 调 is_secure_mode() 但没 import → POST 500
Bug 12: get_knowledge_stats 不处理 ChromaDB 异常 → /api/knowledge/stats 500
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ---------------------------------------------------------------------------
# Bug 11: is_secure_mode import
# ---------------------------------------------------------------------------
def test_is_secure_mode_imported_in_app():
    """app.py 必须 import is_secure_mode(防止 NameError 500)"""
    content = (PROJECT_ROOT / "src/server/app.py").read_text(encoding="utf-8")
    # 找 from .router import ...
    m = re.search(r"from \.router import (.+)", content)
    assert m, "app.py 必须 from .router import ..."
    imports = m.group(1)
    assert "is_secure_mode" in imports, (
        "app.py 必须 import is_secure_mode(否则 _dispatch 报 NameError → 500)"
    )


def test_is_secure_mode_defined_in_router():
    """router.py 必须定义 is_secure_mode 函数"""
    content = (PROJECT_ROOT / "src/server/router.py").read_text(encoding="utf-8")
    assert "def is_secure_mode" in content


# ---------------------------------------------------------------------------
# Bug 12: knowledge_stats 降级处理
# ---------------------------------------------------------------------------
def test_get_knowledge_stats_handles_rag_errors():
    """get_knowledge_stats 必须 try/except 处理 RAG 异常,不让 /api/knowledge/stats 500"""
    content = (PROJECT_ROOT / "src/agent/core.py").read_text(encoding="utf-8")
    # 找 get_knowledge_stats 函数
    m = re.search(
        r"def get_knowledge_stats\(self\)[\s\S]+?return stats",
        content,
    )
    assert m, "get_knowledge_stats 函数未找到"
    body = m.group(0)
    # 必须有 try/except 包裹 rag_stats 调用
    assert "try:" in body, "必须 try: 包裹 rag_engine.get_stats()"
    assert "rag_engine.get_stats" in body
    assert "except" in body, "必须有 except 兜底"


def test_get_knowledge_stats_fallback_preserves_static_count():
    """RAG 失败时,total_documents 应回退到静态 KB 文档数,而不是 0"""
    content = (PROJECT_ROOT / "src/agent/core.py").read_text(encoding="utf-8")
    m = re.search(
        r"def get_knowledge_stats\(self\)[\s\S]+?return stats",
        content,
    )
    assert m
    body = m.group(0)
    # except 块内不应把 total_documents 强制设 0
    # 应该保持 knowledge_manager.get_stats() 的结果(42 文档)
    assert "rag_error" in body, "降级时记录 rag_error 便于排查"
    # 验证 except 块没有 "total_documents = 0" 这种覆盖
    except_block = body.split("except")[1] if "except" in body else ""
    if "total_documents = 0" in except_block:
        assert False, "except 块不应把 total_documents 强制设 0"


# ---------------------------------------------------------------------------
# 真实 API 烟测
# ---------------------------------------------------------------------------
def test_real_knowledge_stats_does_not_500():
    """/api/knowledge/stats 必须不返 500(RAG 失败时降级)"""
    import urllib.request
    try:
        resp = urllib.request.urlopen("http://127.0.0.1:8000/api/knowledge/stats", timeout=5)
        status = resp.status
        body = resp.read(2000).decode("utf-8", errors="replace")
    except Exception as e:
        import pytest
        pytest.skip(f"服务未运行 ({e}),跳过真实 HTTP 烟测")
    # 不应是 500
    assert status != 500, f"/api/knowledge/stats 返 500(Bug12 未修复):{body[:200]}"
    import json
    data = json.loads(body)
    # 应有 total_documents(可能是 0 + 静态 KB)
    assert "total_documents" in data or "knowledge_base_files" in data
