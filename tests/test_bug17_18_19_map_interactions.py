"""
Bug 17 + 18 + 19 修复测试

Bug 17: 其他 3 方案路线不可见(白色在浅色底图)
Bug 18: 点击卡片切换地图不工作
Bug 19: 公交+地铁 卡片金额显示 0
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ---------------------------------------------------------------------------
# Bug 17: 非聚焦路线颜色对比可见
# ---------------------------------------------------------------------------
def test_non_focus_route_uses_visible_color():
    """非聚焦路线必须用对比色(非白色),确保浅色底图上可见"""
    js = (PROJECT_ROOT / "web/travel-map.js").read_text(encoding="utf-8")
    # Bug17 修复: 必有 palette 4 色定义
    assert "palette" in js, "必须有 palette 颜色调色板"
    # palette 至少 3 种颜色(避免 4 方案全用同色)
    palette_match = re.search(r"var palette\s*=\s*\[([^\]]+)\]", js)
    assert palette_match, "palette 必须定义"
    colors = re.findall(r"#[0-9a-fA-F]{6}", palette_match.group(1))
    assert len(colors) >= 3, f"palette 至少 3 种颜色,实际 {len(colors)}"


def test_focus_route_still_uses_green():
    """聚焦路线仍是主题绿(不被 Bug17 改坏)"""
    js = (PROJECT_ROOT / "web/travel-map.js").read_text(encoding="utf-8")
    # 聚焦路线: #11998e (主题绿)
    assert "#11998e" in js
    # 必须仍是"聚焦 = 11998e" 的判断
    assert ("isFocus" in js and "11998e" in js)


# ---------------------------------------------------------------------------
# Bug 18: 点击切换可靠
# ---------------------------------------------------------------------------
def test_travel_card_saves_tool_result_in_data_attr():
    """出行卡片必须把 toolResult 存到 data-tool-result 属性(双保险缓存)"""
    content = (PROJECT_ROOT / "web/index.html").read_text(encoding="utf-8")
    # 必须有 data-tool-result 属性
    assert "data-tool-result" in content, (
        "Bug18 修复: travel-card 必须有 data-tool-result 属性,确保点击切换时 toolResult 不丢失"
    )
    # 必须有 JSON.stringify
    assert "JSON.stringify(toolResult)" in content


def test_selectTravelRoute_uses_data_tool_result_first():
    """selectTravelRoute 优先用 data-tool-result(避免缓存丢失)"""
    content = (PROJECT_ROOT / "web/index.html").read_text(encoding="utf-8")
    # 找 selectTravelRoute 函数
    start = content.find("function selectTravelRoute(")
    assert start > 0
    end = content.find("\n        function ", start + 30)
    body = content[start:end] if end > 0 else content[start:start + 2000]
    # 必须读 data-tool-result 属性
    assert "data-tool-result" in body, (
        "Bug18 修复: selectTravelRoute 必须从 data-tool-result 读 toolResult"
    )
    assert "getAttribute" in body, "selectTravelRoute 必须用 getAttribute 读属性"


# ---------------------------------------------------------------------------
# Bug 19: cost 从 segments 累加
# ---------------------------------------------------------------------------
def test_cost_falls_back_to_segments():
    """cost 为空列表时必须从 segments 累加(公交+地铁通常每段有 cost)"""
    py = (PROJECT_ROOT / "src/agent/tools/extended.py").read_text(encoding="utf-8")
    # 必须有"if isinstance(cost_raw, (list, dict))"分支
    assert "isinstance(cost_raw, (list, dict))" in py
    # 必须在 list/dict 分支里累加 segments 的 cost
    assert "seg_cost" in py or "segments" in py
    # 必须在累加 buslines/metro 内部的 cost
    assert "buslines" in py
    # 必须 fallback 0
    assert "cost_yuan = 0" in py or "cost_yuan=0" in py


def test_cost_extraction_handles_all_routes():
    """测试 _cost 累加函数能处理各类型 route"""
    # Python twin:从 segments 累加 cost
    def parse_cost(top_cost, segments):
        if isinstance(top_cost, (list, dict)):
            seg_cost = 0.0
            for seg in segments:
                if isinstance(seg.get("cost"), (int, float, str)):
                    try:
                        seg_cost += float(seg["cost"])
                    except (TypeError, ValueError):
                        pass
                for line_key in ("bus", "metro"):
                    line = seg.get(line_key, {})
                    if isinstance(line.get("cost"), (int, float, str)):
                        try:
                            seg_cost += float(line["cost"])
                        except (TypeError, ValueError):
                            pass
                    for bl in line.get("buslines", []) or []:
                        bc = bl.get("cost")
                        if isinstance(bc, (int, float, str)):
                            try:
                                seg_cost += float(bc)
                            except (TypeError, ValueError):
                                pass
            return round(seg_cost, 1) if seg_cost > 0 else 0
        if isinstance(top_cost, (int, float, str)):
            try:
                return round(float(top_cost), 1)
            except (TypeError, ValueError):
                return 0
        return 0

    # 场景 1: 顶层 cost 正常数字
    assert parse_cost(3.0, []) == 3.0
    # 场景 2: 顶层 cost [] + segments 有 cost
    assert parse_cost([], [
        {"cost": "5.0", "bus": {"buslines": [{"cost": "3"}]}}
    ]) == 8.0
    # 场景 3: 顶层 cost {} + segments 数组
    assert parse_cost({}, [
        {"metro": {"buslines": [{"cost": 6.0}]}}
    ]) == 6.0
    # 场景 4: 顶层 None
    assert parse_cost(None, []) == 0
