"""
P6.S.24: Leaflet 地图 + polyline 解码 + 出行卡片升级测试

覆盖:
A. TravelPlanningTool._gaode_route 返回 polyline + origin_coord/destination_coord
B. Python twin polyline 解码算法(与 web/travel-map.js 算法镜像)
C. web/travel-map.js 文件存在 + 暴露 decodeAmapPolyline / renderTravelMap
D. web/index.html addMessage 调 renderTravelMap + 引入 travel-map.js
E. Leaflet CDN 引入 + CSS 选择器 .travel-leaflet-map 存在
F. node --check 验证 travel-map.js 语法有效
G. JS 算法与 Python twin 等价(静态扫描)
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ---------------------------------------------------------------------------
# Python twin of web/travel-map.js decoder(算法镜像,用于纯 Python 单测)
# 真实 JS 函数在浏览器中跑,这里只验证算法正确性
# ---------------------------------------------------------------------------
def decode_amap_polyline(s):
    """镜像 web/travel-map.js decodeAmapPolyline 算法"""
    if not s or not isinstance(s, str):
        return []
    points = []
    for seg in s.split(";"):
        seg = seg.strip()
        if not seg:
            continue
        parts = re.split(r"[,\s]+", seg)
        if len(parts) >= 2:
            try:
                lng, lat = float(parts[0]), float(parts[1])
                if abs(lat) <= 90 and abs(lng) <= 180:
                    points.append({"lat": lat, "lng": lng})
            except (ValueError, TypeError):
                pass
    return points


def compute_center(points):
    """镜像 web/travel-map.js computeCenter"""
    if not points:
        return {"lat": 39.9042, "lng": 116.4074}  # 北京兜底
    sum_lat = sum(p["lat"] for p in points)
    sum_lng = sum(p["lng"] for p in points)
    return {"lat": sum_lat / len(points), "lng": sum_lng / len(points)}


# ---------------------------------------------------------------------------
# A. 后端 _gaode_route polyline 字段(代码扫描)
# ---------------------------------------------------------------------------
def test_gaode_route_returns_polyline():
    """_gaode_route 必须把高德返回的 polyline 透出,前端 Leaflet 才能画"""
    content = (PROJECT_ROOT / "src/agent/tools/extended.py").read_text(encoding="utf-8")
    assert '"polyline": polyline' in content, "transit 路线必须含 polyline 字段"
    assert '"polyline": p.get("polyline")' in content, "cycling 路线必须含 polyline 字段"
    assert '"origin_coord": _coord_to_latlng' in content
    assert '"destination_coord": _coord_to_latlng' in content


# ---------------------------------------------------------------------------
# B. polyline 解码算法(Python twin)
# ---------------------------------------------------------------------------
def test_decode_amap_polyline_basic():
    pts = decode_amap_polyline("116.4,39.9;116.5,40.0;116.6,40.1")
    assert len(pts) == 3
    assert pts[0] == {"lat": 39.9, "lng": 116.4}
    assert pts[2] == {"lat": 40.1, "lng": 116.6}


def test_decode_amap_polyline_empty():
    assert decode_amap_polyline("") == []
    assert decode_amap_polyline(None) == []
    assert decode_amap_polyline(123) == []


def test_decode_amap_polyline_space_separator():
    pts = decode_amap_polyline("116.4 39.9;116.5 40.0")
    assert len(pts) == 2
    assert pts[0]["lat"] == 39.9


def test_decode_amap_polyline_out_of_range_filtered():
    pts = decode_amap_polyline("116.4,39.9;999,999;abc,def")
    assert len(pts) == 1
    assert pts[0]["lat"] == 39.9


def test_decode_amap_polyline_trailing_semicolon():
    pts = decode_amap_polyline("116.4,39.9;116.5,40.0;")
    assert len(pts) == 2


def test_compute_center_average():
    pts = [{"lat": 39.0, "lng": 116.0}, {"lat": 41.0, "lng": 118.0}]
    c = compute_center(pts)
    assert c["lat"] == 40.0
    assert abs(c["lng"] - 117.0) < 0.001


def test_compute_center_empty_fallback_beijing():
    c = compute_center([])
    assert c == {"lat": 39.9042, "lng": 116.4074}


# ---------------------------------------------------------------------------
# C. travel-map.js 文件存在 + 结构
# ---------------------------------------------------------------------------
def test_travel_map_file_exists():
    p = PROJECT_ROOT / "web/travel-map.js"
    assert p.exists(), "web/travel-map.js 必须存在"
    content = p.read_text(encoding="utf-8")
    assert "renderTravelMap" in content
    assert "decodeAmapPolyline" in content
    assert "computeCenter" in content
    assert "global.renderTravelMap" in content, "必须挂载到 global(window)"


# ---------------------------------------------------------------------------
# D. JS 算法与 Python twin 等价(静态扫描)
# ---------------------------------------------------------------------------
def test_js_decode_algorithm_mirrors_python():
    """静态校验 web/travel-map.js 内的 decodeAmapPolyline 函数体包含核心算法元素"""
    js_content = (PROJECT_ROOT / "web/travel-map.js").read_text(encoding="utf-8")
    m = re.search(
        r"function decodeAmapPolyline\(str\)\s*\{([\s\S]+?)\n\s{4}\}\s*\n",
        js_content,
    )
    assert m, "decodeAmapPolyline 函数未找到"
    body = m.group(1)
    assert "split(';')" in body or 'split(";")' in body, "必须按 ; 分割"
    assert "parseFloat" in body, "必须 parseFloat 经纬度"
    assert "Math.abs(lat)" in body, "必须过滤越界 lat"
    assert "Math.abs(lng)" in body, "必须过滤越界 lng"


def test_js_compute_center_mirrors_python():
    js_content = (PROJECT_ROOT / "web/travel-map.js").read_text(encoding="utf-8")
    m = re.search(
        r"function computeCenter\(points\)\s*\{([\s\S]+?)\n\s{4}\}\s*\n",
        js_content,
    )
    assert m, "computeCenter 函数未找到"
    body = m.group(1)
    assert "39.9042" in body, "空数据兜底北京坐标"
    assert "points.length" in body, "必须用 points.length 求平均"


# ---------------------------------------------------------------------------
# E. node --check 验证 JS 语法
# ---------------------------------------------------------------------------
def test_travel_map_js_syntax_valid():
    """travel-map.js 必须能被 Node.js 解析(无语法错误)"""
    js_path = PROJECT_ROOT / "web/travel-map.js"
    if not js_path.exists():
        import pytest
        pytest.skip("travel-map.js 不存在,跳过")
    proc = subprocess.run(
        ["node", "--check", str(js_path)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, f"travel-map.js 语法错误:{proc.stderr[:500]}"


# ---------------------------------------------------------------------------
# F. index.html 引入 travel-map.js + Leaflet CDN
# ---------------------------------------------------------------------------
def test_index_html_includes_travel_map_js():
    content = (PROJECT_ROOT / "web/index.html").read_text(encoding="utf-8")
    # Bug14: 接受 ?v=N cache-bust
    assert ('<script src="/travel-map.js"' in content
            or 'src="/travel-map.js?v=' in content), "必须引入 travel-map.js"
    # Bug16: Leaflet CDN 已完全移除(国内屏蔽)
    assert 'leaflet@1.9.4/dist/leaflet.css' not in content, "Leaflet CSS CDN 必须移除"
    assert 'leaflet@1.9.4/dist/leaflet.js' not in content, "Leaflet JS CDN 必须移除"


def test_index_html_addMessage_calls_renderTravelMap():
    content = (PROJECT_ROOT / "web/index.html").read_text(encoding="utf-8")
    start = content.find("function addMessage(")
    assert start > 0
    next_fn = content.find("function formatContent", start + 30)
    body = content[start:next_fn] if next_fn > 0 else content[start:start+10000]
    assert "renderTravelMap" in body, "addMessage 必须调 renderTravelMap"
    assert "hasMapPolyline" in body, "必须检测 polyline 存在"
    assert ".travel-map-placeholder" in body, "必须创建地图占位 div"


def test_index_html_travel_card_has_map_placeholder():
    content = (PROJECT_ROOT / "web/index.html").read_text(encoding="utf-8")
    assert "travel-map-placeholder" in content


# ---------------------------------------------------------------------------
# G. CSS — Leaflet 地图容器样式
# ---------------------------------------------------------------------------
def test_css_leaflet_map_styles():
    content = (PROJECT_ROOT / "web/index.html").read_text(encoding="utf-8")
    assert ".travel-leaflet-map" in content
    assert ".travel-marker-pin" in content
    assert ".travel-marker-start" in content
    assert ".travel-marker-end" in content
