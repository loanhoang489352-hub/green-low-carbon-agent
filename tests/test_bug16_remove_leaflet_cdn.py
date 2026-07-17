"""
Bug 16 修复测试: 移除被国内屏蔽的 Leaflet CDN 引用

覆盖:
A. index.html 不再引用 unpkg.com / leafletjs.com
B. travel-map.js 不依赖 Leaflet 任何 CDN
C. 地图现在只用国内服务(高德)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ---------------------------------------------------------------------------
# A. index.html 不引用被屏蔽的 CDN
# ---------------------------------------------------------------------------
def test_index_html_no_unpkg_cdn():
    """index.html <head> 不应再引用 unpkg.com/leafletjs.com(国内屏蔽)

    只检查 src=/href= 标签属性,允许注释里提到(解释为什么移除)
    """
    content = (PROJECT_ROOT / "web/index.html").read_text(encoding="utf-8")
    head_end = content.find("</head>")
    head = content[:head_end]
    # 提取所有 src= 和 href= 属性
    import re
    srcs = re.findall(r'(?:src|href)=["\']([^"\']+)["\']', head)
    for url in srcs:
        assert "unpkg.com" not in url, f"index.html <head> 不应再引用 unpkg.com: {url}"
        assert "leafletjs.com" not in url, f"不应引用 leafletjs.com: {url}"


def test_index_html_still_loads_travel_map():
    """必须保留 travel-map.js 引用(Bug 14 修复)"""
    content = (PROJECT_ROOT / "web/index.html").read_text(encoding="utf-8")
    assert "travel-map.js" in content, "必须保留 travel-map.js 引用"
    assert "?v=" in content, "必须用 ?v=N cache-bust"


# ---------------------------------------------------------------------------
# B. travel-map.js 不依赖 Leaflet 任何 CDN
# ---------------------------------------------------------------------------
def test_travel_map_no_leaflet_cdn():
    """travel-map.js 不应再引用 Leaflet CDN(必须用纯 SVG + 高德静态图)"""
    content = (PROJECT_ROOT / "web/travel-map.js").read_text(encoding="utf-8")
    assert "unpkg.com" not in content, "不应再引 unpkg.com"
    assert "leafletjs.com" not in content, "不应再引 leafletjs.com"


def test_travel_map_uses_only_domestic_cdn():
    """travel-map.js 必须只用国内服务(高德代理)"""
    content = (PROJECT_ROOT / "web/travel-map.js").read_text(encoding="utf-8")
    # 应通过 /api/staticmap 代理,不直接调国外 CDN
    assert "/api/staticmap" in content, "必须通过 /api/staticmap 代理"
    # 不应直接调任何国外 tile 服务器
    forbidden = ["tile.openstreetmap.org", "basemaps.cartocdn.com", "unpkg.com/leaflet", "leafletjs.com"]
    for url in forbidden:
        assert url not in content, f"不应直接调 {url}"


# ---------------------------------------------------------------------------
# C. 地图渲染路径完全用国内服务
# ---------------------------------------------------------------------------
def test_renderSVGMap_uses_gaode_staticmap():
    """renderSVGMap 必须用高德静态地图作底图"""
    content = (PROJECT_ROOT / "web/travel-map.js").read_text(encoding="utf-8")
    # 应有高德 markers 构造
    assert "0x11998e" in content, "必须用主题绿作 A 标记"
    assert "0xef4444" in content, "必须用红色作 B 标记"
    # 应有 bbox + markers 拼装
    assert "bbox" in content
    assert "encodeURIComponent" in content


def test_travel_map_js_syntax_valid():
    """JS 语法检查"""
    js_path = PROJECT_ROOT / "web/travel-map.js"
    import subprocess
    proc = subprocess.run(
        ["node", "--check", str(js_path)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, f"语法错误:{proc.stderr[:500]}"
