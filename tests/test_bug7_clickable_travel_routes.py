"""
Bug 7 修复测试: 出行卡片可点击切换地图 + 地图降级提示

覆盖:
A. addMessage 给卡片加 data-route-index / data-message-id
B. setupChatContainerDelegation 接管 .travel-route click
C. selectTravelRoute 函数存在
D. _cacheToolResult 缓存最近 toolResult
E. renderTravelMap 接受 focusIndex 参数
F. CSS .travel-route 有 cursor:pointer + hover + focused
G. 降级 .travel-map-fallback 提示
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ---------------------------------------------------------------------------
# A. 卡片可点击 — index.html 静态扫描
# ---------------------------------------------------------------------------
def test_travel_route_cards_have_data_attributes():
    """每个 travel-route 必须有 data-route-index 和 data-message-id"""
    content = (PROJECT_ROOT / "web/index.html").read_text(encoding="utf-8")
    # 找 .travel-route 模板
    m = re.search(r'<div class="travel-route[^"]*"\s+data-mode=[\s\S]+?</div>', content)
    assert m, "未找到 .travel-route 模板"
    body = m.group(0)
    assert 'data-route-index' in body, "卡片必须含 data-route-index"
    assert 'data-message-id' in body, "卡片必须含 data-message-id"
    assert 'role="button"' in body, "卡片必须有 role=button(a11y)"
    assert 'tabindex="0"' in body, "卡片必须有 tabindex=0(键盘可达)"


def test_travel_route_has_focused_state():
    """focused class 用于视觉高亮"""
    content = (PROJECT_ROOT / "web/index.html").read_text(encoding="utf-8")
    # 模板中必须有 ${isFocus ? 'focused' : ''}
    assert "'focused'" in content, "模板必须根据 isFocus 加 focused class"
    # CSS 必须有 .travel-route.focused 样式
    assert ".travel-route.focused" in content, "必须定义 .travel-route.focused 样式"


# ---------------------------------------------------------------------------
# B. 事件委托接管 .travel-route
# ---------------------------------------------------------------------------
def test_chat_container_delegation_handles_travel_route():
    """setupChatContainerDelegation 必须处理 .travel-route click"""
    content = (PROJECT_ROOT / "web/index.html").read_text(encoding="utf-8")
    # 找委托处理 travel-route 的部分
    m = re.search(
        r"if \(target\.classList\.contains\('travel-route'\)\)\s*\{[\s\S]+?\n\s+\}\s*\n\s+return;",
        content,
    )
    assert m, "委托 click 必须处理 .travel-route"
    body = m.group(0)
    assert "selectTravelRoute" in body, "必须调 selectTravelRoute"
    assert "data-message-id" in body
    assert "data-route-index" in body


# ---------------------------------------------------------------------------
# C. selectTravelRoute 函数存在
# ---------------------------------------------------------------------------
def test_selectTravelRoute_function_exists():
    content = (PROJECT_ROOT / "web/index.html").read_text(encoding="utf-8")
    assert "function selectTravelRoute" in content
    # Bug18 后函数体更长,改用 3000 字符窗口
    start = content.find("function selectTravelRoute")
    assert start > 0
    snippet = content[start:start + 3000]
    assert "renderTravelMap" in snippet, "selectTravelRoute 必须调 renderTravelMap"
    assert "focused" in snippet, "selectTravelRoute 必须切换 .focused class"
    assert "getElementById" in snippet, "selectTravelRoute 必须查 DOM"
    # Bug18 新增:必须用 data-tool-result 属性(防缓存丢失)
    assert "data-tool-result" in snippet, "Bug18: selectTravelRoute 必须用 data-tool-result"


# ---------------------------------------------------------------------------
# D. _cacheToolResult 缓存
# ---------------------------------------------------------------------------
def test_cacheToolResult_function_exists():
    content = (PROJECT_ROOT / "web/index.html").read_text(encoding="utf-8")
    assert "function _cacheToolResult" in content
    assert "window.__currentTravelToolResult" in content, "必须缓存到 window.__currentTravelToolResult"
    assert "_cacheToolResult(toolResult)" in content, "addMessage 调 renderTravelMap 前必须缓存"


# ---------------------------------------------------------------------------
# E. renderTravelMap focusIndex 参数
# ---------------------------------------------------------------------------
def test_renderTravelMap_accepts_focusIndex():
    js = (PROJECT_ROOT / "web/travel-map.js").read_text(encoding="utf-8")
    # 函数签名
    m = re.search(
        r"function renderTravelMap\([^)]+\)\s*\{",
        js,
    )
    assert m, "renderTravelMap 函数未找到"
    sig = m.group(0)
    assert "focusIndex" in sig, "renderTravelMap 必须有 focusIndex 参数"
    # 函数体内必须根据 focusIndex 决定颜色
    assert "isFocus" in js, "renderTravelMap 必须用 isFocus 变量判断"
    assert "focusIndex" in js, "renderTravelMap 必须用 focusIndex"


def test_travel_map_js_syntax_valid():
    """node --check 验证 travel-map.js 语法"""
    js_path = PROJECT_ROOT / "web/travel-map.js"
    proc = subprocess.run(
        ["node", "--check", str(js_path)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, f"travel-map.js 语法错误:{proc.stderr[:500]}"


# ---------------------------------------------------------------------------
# F. CSS — 卡片可点击
# ---------------------------------------------------------------------------
def test_travel_route_css_clickable():
    content = (PROJECT_ROOT / "web/index.html").read_text(encoding="utf-8")
    assert ".travel-route" in content
    # 找包含 cursor: pointer 的 .travel-route 规则块(可能多个)
    m = re.search(r"\.travel-route\s*\{([^}]*cursor:\s*pointer[^}]*)\}", content)
    assert m, "必须有 .travel-route 块含 cursor: pointer"
    body = m.group(1)
    assert "transition" in body, ".travel-route 块内必须有 transition"
    # 还必须有 hover 块
    assert ".travel-route:hover" in content, "必须有 :hover 块"
    # focused 块
    assert ".travel-route.focused" in content, "必须有 .travel-route.focused 块"


def test_travel_route_fallback_message():
    """无 polyline 时显示 fallback 提示"""
    content = (PROJECT_ROOT / "web/index.html").read_text(encoding="utf-8")
    assert "travel-map-fallback" in content
    # 模板里必须有 fallback
    assert "暂无地理坐标数据" in content or "travel-map-fallback" in content
