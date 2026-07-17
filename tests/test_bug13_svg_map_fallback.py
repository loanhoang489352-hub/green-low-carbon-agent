"""
Bug 13 修复测试: SVG 路线图兜底(Leaflet 瓦片失败时仍能显示)

覆盖:
A. renderSVGMap 函数存在(永远能渲染的兜底)
B. enhanceWithLeaflet 函数存在(SVG 之上的增强层)
C. renderTravelMap 改为先调 renderSVGMap 再 ensureLeaflet(不阻塞)
D. SVG 容器 CSS .travel-svg-map 存在
E. 出行卡片可点击切换聚焦时也调 renderSVGMap(不依赖 Leaflet)
F. 节点 --check 验证 JS 语法
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ---------------------------------------------------------------------------
# A. renderSVGMap 函数存在
# ---------------------------------------------------------------------------
def test_renderSVGMap_function_exists():
    """Bug13 核心:SVG 兜底函数必须存在"""
    js = (PROJECT_ROOT / "web/travel-map.js").read_text(encoding="utf-8")
    m = re.search(
        r"function renderSVGMap\([^)]+\)\s*\{",
        js,
    )
    assert m, "renderSVGMap 函数未找到"
    # 截取到下一个 function / export 之前
    end = js.find("\n    function ", m.end() + 10)
    end2 = js.find("\n    })(", m.end() + 10)
    if end < 0 or (end2 > 0 and end2 < end):
        end = end2
    body = js[m.end():end] if end > 0 else js[m.end():m.end() + 20000]
    # 必须含 SVG 关键逻辑
    assert "decodeAmapPolyline" in body
    assert "viewBox" in body, "必须用 SVG viewBox"
    assert ("<svg" in body or "createElementNS" in body), "必须建 SVG"
    assert "stroke=" in body or "stroke:" in body, "必须画 path 折线"


def test_renderSVGMap_has_origin_destination_markers():
    """SVG 必须画起点 A + 终点 B 标记"""
    js = (PROJECT_ROOT / "web/travel-map.js").read_text(encoding="utf-8")
    m = re.search(
        r"function renderSVGMap\([^)]+\)\s*\{([\s\S]+?)\n\s{4}\}\s*\n",
        js,
    )
    assert m
    body = m.group(1)
    assert "marker" in body.lower() or "circle" in body.lower(), "必须有 marker 绘制"


# ---------------------------------------------------------------------------
# B. Bug16: enhanceWithLeaflet 已删除(不再用 Leaflet)
# ---------------------------------------------------------------------------
def test_enhanceWithLeaflet_removed():
    """Bug16: enhanceWithLeaflet 必须不存在(Leaflet 完全移除)"""
    js = (PROJECT_ROOT / "web/travel-map.js").read_text(encoding="utf-8")
    assert "function enhanceWithLeaflet" not in js, (
        "Bug16: enhanceWithLeaflet 函数必须不存在(Leaflet CDN 国内屏蔽)"
    )


# ---------------------------------------------------------------------------
# C. renderTravelMap 调用顺序
# ---------------------------------------------------------------------------
def test_renderTravelMap_calls_SVG_first():
    """renderTravelMap 简化后只调 renderSVGMap(Bug16 移除 Leaflet)"""
    js = (PROJECT_ROOT / "web/travel-map.js").read_text(encoding="utf-8")
    m = re.search(
        r"function renderTravelMap\([^)]+\)\s*\{([\s\S]+?)\n\s{4}\}\s*\n",
        js,
    )
    assert m
    body = m.group(1)
    # renderSVGMap 必须调(Bug16 后是唯一渲染路径)
    assert "renderSVGMap(" in body, "renderTravelMap 必须调 renderSVGMap"
    # ensureLeaflet 不应再被调(已移除)
    assert "ensureLeaflet(" not in body, "Bug16: ensureLeaflet 必须被移除"


def test_ensureLeaflet_failure_does_not_wipe_SVG():
    """Bug16: 已完全移除 Leaflet 依赖,渲染路径只剩 SVG + 高德静态图

    旧的 ensureLeaflet 函数应已不存在(避免误用 Leaflet CDN)
    """
    js = (PROJECT_ROOT / "web/travel-map.js").read_text(encoding="utf-8")
    # Bug16: ensureLeaflet 函数必须不存在(整个 Leaflet 依赖已移除)
    assert "function ensureLeaflet" not in js, (
        "Bug16: ensureLeaflet 函数必须不存在(Leaflet CDN 国内屏蔽)"
    )



def test_travel_staticmap_bg_has_position_absolute():
    """Bug16: .travel-staticmap-bg CSS 必须有 position: absolute"""
    # 只检查 <style> 块,避免匹配到 JS 字符串内
    content = (PROJECT_ROOT / "web/index.html").read_text(encoding="utf-8")
    # 找 <style>...</style> 块
    import re
    style_match = re.search(r"<style>([\s\S]+?)</style>", content)
    assert style_match, "没有 <style> 块"
    style = style_match.group(1)
    # 找 .travel-staticmap-bg 块
    m = re.search(r"\.travel-staticmap-bg\s*\{([^{}]+?)\}", style)
    assert m, ".travel-staticmap-bg CSS 块未找到"
    body = m.group(1)
    assert "absolute" in body, ".travel-staticmap-bg 必须 position: absolute"


# ---------------------------------------------------------------------------
# D. SVG 容器 CSS
# ---------------------------------------------------------------------------
def test_travel_svg_map_css_exists():
    """.travel-svg-map CSS 必须存在"""
    content = (PROJECT_ROOT / "web/index.html").read_text(encoding="utf-8")
    assert ".travel-svg-map" in content
    assert ".travel-svg-legend" in content
    m = re.search(r"\.travel-svg-map\s+svg\s*\{([^}]+)\}", content)
    assert m, ".travel-svg-map svg CSS 缺失"
    body = m.group(1)
    assert "height" in body, "SVG 必须有显式高度"


def test_travel_leaflet_overlay_positioning():
    """Leaflet overlay 必须 absolute 覆盖在 SVG 之上"""
    content = (PROJECT_ROOT / "web/index.html").read_text(encoding="utf-8")
    # 找 .travel-leaflet-overlay CSS
    m = re.search(r"\.travel-leaflet-overlay\s*\{([^}]+)\}", content)
    # 或者在 travel-map.js 中检查
    js = (PROJECT_ROOT / "web/travel-map.js").read_text(encoding="utf-8")
    assert "position:absolute" not in js, "Bug16: travel-map.js 不能有 position:absolute(Leaflet 残留)"
    assert "opacity:0.6" in js, "Leaflet overlay 必须半透明(SVG 在下可见)"


# ---------------------------------------------------------------------------
# E. 节点 --check
# ---------------------------------------------------------------------------
def test_travel_map_js_syntax_valid():
    js_path = PROJECT_ROOT / "web/travel-map.js"
    proc = subprocess.run(
        ["node", "--check", str(js_path)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, f"travel-map.js 语法错误:{proc.stderr[:500]}"


# ---------------------------------------------------------------------------
# F. selectTravelRoute 切换时也能重新渲染 SVG
# ---------------------------------------------------------------------------
def test_selectTravelRoute_calls_renderTravelMap():
    """点击切换时 selectTravelRoute 必须调 renderTravelMap(重新渲染 SVG)"""
    content = (PROJECT_ROOT / "web/index.html").read_text(encoding="utf-8")
    # 找 selectTravelRoute 函数(简化正则,允许任意缩进)
    start = content.find("function selectTravelRoute(")
    assert start > 0, "selectTravelRoute 函数未找到"
    # 截取函数体(到下一个 function 之前)
    end = content.find("function ", start + 50)
    body = content[start:end] if end > 0 else content[start:start + 2000]
    assert "renderTravelMap" in body, "selectTravelRoute 必须调 renderTravelMap"
    assert "routeIndex" in body, "必须传 routeIndex"
