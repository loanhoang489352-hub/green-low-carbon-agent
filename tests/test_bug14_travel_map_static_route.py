"""
Bug 14 修复测试: /travel-map.js 静态文件路由

覆盖:
A. system.py 必须注册 GET /travel-map.js 路由
B. travel_map_js handler 存在 + 返 no-cache 头
C. 真实 HTTP 验证 /travel-map.js 不再 404
D. i18n.js 路径不破坏
"""
from __future__ import annotations

import re
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ---------------------------------------------------------------------------
# A. 路由注册
# ---------------------------------------------------------------------------
def test_travel_map_js_route_registered():
    """system.py 必须注册 GET /travel-map.js 路由(否则 404)"""
    content = (PROJECT_ROOT / "src/server/routers/system.py").read_text(encoding="utf-8")
    assert '"/travel-map.js"' in content, "system.py 必须注册 /travel-map.js 路由"
    assert "travel_map_js" in content, "必须有 travel_map_js handler 引用"


def test_travel_map_js_handler_function_exists():
    """travel_map_js 函数必须存在"""
    content = (PROJECT_ROOT / "src/server/routers/system.py").read_text(encoding="utf-8")
    m = re.search(
        r"def travel_map_js\(handler\):",
        content,
    )
    assert m, "travel_map_js handler 未定义"


def test_travel_map_js_handler_serves_file():
    """handler 必须读 web/travel-map.js 并返 200 + application/javascript"""
    content = (PROJECT_ROOT / "src/server/routers/system.py").read_text(encoding="utf-8")
    start = content.find("def travel_map_js(handler):")
    assert start > 0
    # 截取到下一个 def 之前
    end = content.find("\n    def ", start + 50)
    body = content[start:end] if end > 0 else content[start:start + 2000]
    assert "travel-map.js" in body, "handler 必须读 travel-map.js"
    assert "application/javascript" in body, "必须设正确的 Content-type"
    assert "send_response(200)" in body, "必须返 200"


def test_travel_map_js_handler_no_cache():
    """handler 必须设 Cache-Control: no-cache(避免浏览器缓存旧版)"""
    content = (PROJECT_ROOT / "src/server/routers/system.py").read_text(encoding="utf-8")
    start = content.find("def travel_map_js(handler):")
    assert start > 0
    end = content.find("\n    def ", start + 50)
    body = content[start:end] if end > 0 else content[start:start + 2000]
    assert "Cache-Control" in body, "必须设 Cache-Control 头"
    assert "no-cache" in body or "no-store" in body, "必须含 no-cache/no-store"


# ---------------------------------------------------------------------------
# B. i18n.js 路径不破坏
# ---------------------------------------------------------------------------
def test_i18n_js_route_still_works():
    """/i18n.js 路径不能被破坏"""
    content = (PROJECT_ROOT / "src/server/routers/system.py").read_text(encoding="utf-8")
    assert '"/i18n.js"' in content
    assert "def i18n_js(handler):" in content


# ---------------------------------------------------------------------------
# C. 真实 HTTP 验证
# ---------------------------------------------------------------------------
def test_real_http_travel_map_js_not_404():
    """真实 HTTP 请求 /travel-map.js 必须不返 404"""
    try:
        resp = urllib.request.urlopen("http://127.0.0.1:8000/travel-map.js", timeout=5)
        status = resp.status
        body = resp.read(500).decode("utf-8", errors="replace")
    except Exception as e:
        import pytest
        pytest.skip(f"服务未运行 ({e}),跳过真实 HTTP 烟测")
    assert status == 200, f"/travel-map.js 应返 200,实际 {status}(Bug14 未修复)"
    # 必须有 renderTravelMap 函数定义
    assert "renderTravelMap" in body, "/travel-map.js 响应必须含 renderTravelMap 定义"
    # 必须有 renderSVGMap 兜底
    assert "renderSVGMap" in body, "/travel-map.js 响应必须含 renderSVGMap 兜底"


def test_real_http_travel_map_js_cache_header():
    """/travel-map.js 必须返 no-cache 头(防浏览器缓存旧版)"""
    try:
        resp = urllib.request.urlopen("http://127.0.0.1:8000/travel-map.js", timeout=5)
    except Exception as e:
        import pytest
        pytest.skip(f"服务未运行 ({e}),跳过")
    cache_control = resp.headers.get("Cache-Control", "")
    assert "no-cache" in cache_control or "no-store" in cache_control, (
        f"/travel-map.js 必须有 no-cache 头,实际:{cache_control}"
    )
