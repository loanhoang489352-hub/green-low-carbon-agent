"""
Bug 15 修复测试: 高德静态地图作底图

覆盖:
A. /api/staticmap 路由已注册
B. staticmap handler 存在 + 校验 bbox
C. renderSVGMap 使用高德静态图 URL 作背景
D. CSS .travel-staticmap-bg 存在
"""
from __future__ import annotations

import re
import subprocess
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ---------------------------------------------------------------------------
# A. /api/staticmap 路由
# ---------------------------------------------------------------------------
def test_staticmap_route_registered():
    """system.py 必须注册 /api/staticmap 路由"""
    content = (PROJECT_ROOT / "src/server/routers/system.py").read_text(encoding="utf-8")
    assert '"/api/staticmap"' in content
    assert "staticmap" in content


def test_staticmap_handler_validates_bbox():
    """staticmap handler 必须校验 bbox 格式"""
    content = (PROJECT_ROOT / "src/server/routers/system.py").read_text(encoding="utf-8")
    start = content.find("def staticmap(handler):")
    assert start > 0, "staticmap handler 未找到"
    end = content.find("\n    def ", start + 50)
    body = content[start:end] if end > 0 else content[start:start + 3000]
    assert "bbox" in body, "handler 必须解析 bbox"
    assert "GAODE_API_KEY" in body, "handler 必须读 GAODE_API_KEY"


def test_staticmap_handler_proxies_amap():
    """handler 必须构造高德 URL 并代理"""
    content = (PROJECT_ROOT / "src/server/routers/system.py").read_text(encoding="utf-8")
    start = content.find("def staticmap(handler):")
    assert start > 0
    end = content.find("\n    def ", start + 50)
    body = content[start:end] if end > 0 else content[start:start + 3000]
    assert "restapi.amap.com" in body, "handler 必须构造高德 URL"
    assert "staticmap" in body, "handler 必须调 /v3/staticmap 端点"


# ---------------------------------------------------------------------------
# B. 前端 renderSVGMap 使用 /api/staticmap
# ---------------------------------------------------------------------------
def test_renderSVGMap_uses_staticmap_proxy():
    """renderSVGMap 必须用 /api/staticmap(避免 API key 暴露)"""
    js = (PROJECT_ROOT / "web/travel-map.js").read_text(encoding="utf-8")
    assert "/api/staticmap" in js, "前端必须通过 /api/staticmap 代理"
    assert "bbox" in js, "必须传 bbox"
    assert "markers" in js, "必须传 markers"
    assert "encodeURIComponent" in js, "URL 参数必须编码"


def test_renderSVGMap_includes_origin_destination_markers():
    """必须构造 A/B 起终点 marker 参数"""
    js = (PROJECT_ROOT / "web/travel-map.js").read_text(encoding="utf-8")
    assert "0x11998e" in js, "A 标记必须用主题绿色"
    assert "0xef4444" in js, "B 标记必须用红色"


# ---------------------------------------------------------------------------
# C. CSS 存在
# ---------------------------------------------------------------------------
def test_staticmap_bg_css_exists():
    """.travel-staticmap-bg CSS 必须存在"""
    content = (PROJECT_ROOT / "web/index.html").read_text(encoding="utf-8")
    assert ".travel-staticmap-bg" in content
    assert ".travel-overlay-svg" in content
    assert ".travel-staticmap-wrap" in content


def test_staticmap_bg_positioning():
    """.travel-staticmap-bg 必须 absolute 覆盖在 .travel-staticmap-wrap 内"""
    content = (PROJECT_ROOT / "web/index.html").read_text(encoding="utf-8")
    m = re.search(r"\.travel-staticmap-bg\s*\{([^}]+)\}", content)
    assert m, ".travel-staticmap-bg CSS 块未找到"
    body = m.group(1)
    assert "position: absolute" in body or "position:absolute" in body
    assert "object-fit" in body or "width: 100%" in body


# ---------------------------------------------------------------------------
# D. 真实 HTTP 烟测
# ---------------------------------------------------------------------------
def test_real_http_staticmap_endpoint():
    """真实 HTTP /api/staticmap 必须返 200 + image"""
    try:
        # 北京西站 → 首都机场 真实坐标
        url = "http://127.0.0.1:8000/api/staticmap?bbox=116.30,39.88,116.62,40.06&size=600*400&zoom=11&markers=mid,0x11998e,A:116.32,39.89;mid,0xef4444,B:116.59,40.05"
        resp = urllib.request.urlopen(url, timeout=15)
        status = resp.status
        body = resp.read(200)
    except Exception as e:
        import pytest
        pytest.skip(f"服务未运行 ({e})")
    assert status == 200, f"/api/staticmap 应返 200,实际 {status}"
    ctype = resp.headers.get("Content-Type", "")
    assert "image" in ctype, f"必须是图片,Content-Type={ctype}"
    assert len(body) > 1000, f"图片应 > 1KB,实际 {len(body)} bytes"


def test_travel_map_js_syntax_valid():
    """travel-map.js 语法检查"""
    js_path = PROJECT_ROOT / "web/travel-map.js"
    proc = subprocess.run(
        ["node", "--check", str(js_path)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, f"travel-map.js 语法错误:{proc.stderr[:500]}"
