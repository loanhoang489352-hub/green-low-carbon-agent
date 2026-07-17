"""
P6.S.26 Bug1 增量修复测试

覆盖以下 4 个 Bug1 根因(在原 test_bug1_amap_data_contract.py 之外的补充):
1. 距离/时长计算:round 到 1 位小数,避免 <1km 段显示 0.0km
2. urlencode 坐标用 quote() 单独编码,避免代理/CDN 截断逗号
3. 前端 weather 字段双兼容(description/temp_c 优先,desc/temp 兜底)
4. 失败时 tool_result.error 透传,前端能区分"无 key" vs "无路线"

不依赖真实高德 API(纯静态代码扫描 + JS 字符串解析)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ---------------------------------------------------------------------------
# 1. 距离/时长精度(round 到 1 位小数)
# ---------------------------------------------------------------------------
def test_distance_uses_round_one_decimal():
    """distance_km 必须 round 到 1 位小数,不再 // 1000 丢精度"""
    content = (PROJECT_ROOT / "src/agent/tools/extended.py").read_text(encoding="utf-8")
    # 公交路线距离计算
    assert "round(float(t.get(\"distance\", 0)) / 1000, 1)" in content, (
        "P6.S.26 fix: 公交路线 distance_km 必须 round(float/1000, 1),不能再用 // 1000"
    )
    # 骑行路线距离计算
    assert "round(float(p.get(\"distance\", 0)) / 1000, 1)" in content, (
        "骑行路线 distance_km 也必须 round(float/1000, 1)"
    )
    # 时长同步
    assert "round(float(t.get(\"duration\", 0)) / 60, 1)" in content, (
        "duration_min 也必须 round(float/60, 1)"
    )


def test_distance_precision_smoke():
    """< 1km 段距离必须 > 0(避免 800m 显示成 0.0km)"""
    # Mirror 修复后逻辑
    raw = "800"  # 800 米
    distance = round(float(raw) / 1000, 1)
    assert distance == 0.8, f"800m 应显示为 0.8km,实际 {distance}km"
    assert distance > 0, "< 1km 段距离不能为 0"


# ---------------------------------------------------------------------------
# 2. urlencode 坐标用 quote() 单独编码
# ---------------------------------------------------------------------------
def test_urllib_quote_used_for_coordinates():
    """transit/integrated 和 bicycling 端点的 origin/destination 坐标必须用 quote()"""
    content = (PROJECT_ROOT / "src/agent/tools/extended.py").read_text(encoding="utf-8")
    # 公交端点
    assert "urllib.parse.quote(origin_coord, safe=\"\")" in content, (
        "公交端点 origin 坐标必须用 quote() 单独编码"
    )
    assert "urllib.parse.quote(dest_coord, safe=\"\")" in content, (
        "公交端点 destination 坐标必须用 quote() 单独编码"
    )
    # 骑行端点
    # 已经有 2 次 (transit + bicycling),再加 bicycling 端点的 quote
    occurrences = content.count("urllib.parse.quote(origin_coord, safe=\"\")")
    assert occurrences >= 2, (
        f"origin_coord quote() 调用应至少 2 次(transit + bicycling),实际 {occurrences}"
    )


def test_urlencode_quote_preserves_comma():
    """quote(safe='') 必须把逗号编码为 %2C,避免 header 截断"""
    from urllib.parse import quote
    coord = "116.321,39.890"
    encoded = quote(coord, safe="")
    assert "%2C" in encoded, f"quote() 后应含 %2C,实际 {encoded}"
    assert "," not in encoded, "quote() 后逗号必须被转义"


# ---------------------------------------------------------------------------
# 3. 前端 weather 字段双兼容
# ---------------------------------------------------------------------------
def test_frontend_weather_dual_compat():
    """web/index.html 中 weather 字段必须兼容 description/temp_c 和 desc/temp"""
    content = (PROJECT_ROOT / "web/index.html").read_text(encoding="utf-8")
    # 优先 description, 兜底 desc
    assert "w.description ?? w.desc" in content, "前端必须优先读 weather.description, 兜底 weather.desc"
    # 优先 temp_c, 兜底 temp
    assert "w.temp_c ?? w.temp" in content, "前端必须优先读 weather.temp_c, 兜底 weather.temp"


def test_frontend_weather_escapes_html():
    """weather 字段必须 escapeHtml,避免 XSS"""
    content = (PROJECT_ROOT / "web/index.html").read_text(encoding="utf-8")
    # 找 addMessage 内的 HTML 渲染锚点(避开 CSS .travel-card-weather { ... })
    # 实际修复后的代码形如:`<div class="travel-card-weather">🌤️ ${escapeHtml(desc)} ...`
    pattern = re.compile(
        r'class="travel-card-weather"[^<]*\$\{escapeHtml\(', re.DOTALL
    )
    assert pattern.search(content), (
        "weather 渲染必须用 escapeHtml 包裹 desc/extras — "
        "检查 web/index.html 中 <div class=\"travel-card-weather\"> 块"
    )
    # 强约束:escapeHtml 出现 2 次(desc + extras)
    block_match = re.search(
        r'class="travel-card-weather".*?</div>', content, re.DOTALL
    )
    assert block_match, "找不到 travel-card-weather HTML 渲染块"
    block = block_match.group(0)
    assert block.count("escapeHtml(") >= 2, (
        f"travel-card-weather 块内 escapeHtml 调用应 >= 2 次(desc + extras),"
        f"实际 {block.count('escapeHtml(')} 次"
    )


# ---------------------------------------------------------------------------
# 4. 失败时 tool_result.error 透传
# ---------------------------------------------------------------------------
def test_core_travel_failure_propagates_error():
    """core.py 出行失败时必须把 error 写入 tool_result"""
    content = (PROJECT_ROOT / "src/agent/core.py").read_text(encoding="utf-8")
    # 失败分支的 tool_result dict 必须含 error 字段
    # P6.S.26 fix: 兼容两种写法("error": result.error / "error": error_text)
    failure_block_match = re.search(
        r"if not result\.success:.*?timestamp=",
        content, re.DOTALL,
    )
    assert failure_block_match, "core.py 找不到出行失败分支"
    block = failure_block_match.group(0)
    assert (
        '"error": result.error' in block
        or '"error": error_text' in block
    ), "失败分支 tool_result 必须包含 error 字段(result.error 或 error_text)"


def test_core_travel_failure_error_category():
    """失败时必须区分 missing_api_key vs no_route"""
    content = (PROJECT_ROOT / "src/agent/core.py").read_text(encoding="utf-8")
    assert "error_category" in content, (
        "core.py 必须有 error_category 字段区分失败原因"
    )
    assert "missing_api_key" in content, (
        "GAODE_API_KEY 缺失时必须标 error_category=missing_api_key"
    )
    assert "no_route" in content, (
        "其他失败(error 中无 GAODE_API_KEY)必须标 error_category=no_route"
    )


# ---------------------------------------------------------------------------
# 5. logger 替换裸 print 异常吞噬
# ---------------------------------------------------------------------------
def test_gaode_route_uses_logger_not_print():
    """_gaode_route 外层 except 必须用 _logger.error 替代 print"""
    content = (PROJECT_ROOT / "src/agent/tools/extended.py").read_text(encoding="utf-8")
    # 不应该有裸 print 在 except 块
    assert "_logger.error" in content, "extended.py 必须使用 _logger.error 记录错误"
    # 必须在 _gaode_route 内部使用
    gaode_route_match = re.search(
        r"def _gaode_route\(self.*?def _gaode_geocode",
        content, re.DOTALL,
    )
    assert gaode_route_match, "_gaode_route 方法未找到"
    gaode_route_body = gaode_route_match.group(0)
    assert "_logger.error" in gaode_route_body, (
        "_gaode_route 的 except 必须调用 _logger.error,不能再用 print"
    )


def test_gaode_geocode_uses_logger():
    """_gaode_geocode 的 except 也必须用 _logger.warning 替代 pass"""
    content = (PROJECT_ROOT / "src/agent/tools/extended.py").read_text(encoding="utf-8")
    # 找到 _gaode_geocode 方法体的范围(到下一个 def 之前)
    # P6.S.26: 兼容多行签名 def _gaode_geocode(\n        self, ...
    start = content.find("def _gaode_geocode")
    assert start > 0, "_gaode_geocode 方法未找到"
    # 找到下一个 def 的位置
    rest = content[start + 1:]
    next_def = rest.find("\n    def ")
    end = start + 1 + next_def if next_def > 0 else len(content)
    geocode_body = content[start:end]
    assert "_logger.warning" in geocode_body, (
        "_gaode_geocode 必须用 _logger.warning 记录 status!=1 / exception"
    )
    # 还要确保没有静默 except: pass
    assert "except Exception:\n            pass" not in geocode_body and \
           "except Exception:\n        pass" not in geocode_body, (
        "_gaode_geocode 不应有 except: pass 静默吞噬异常"
    )


# ---------------------------------------------------------------------------
# 6. observability logger 导入
# ---------------------------------------------------------------------------
def test_extended_imports_logger():
    """extended.py 必须从 observability 导入 get_logger"""
    content = (PROJECT_ROOT / "src/agent/tools/extended.py").read_text(encoding="utf-8")
    assert "from observability import get_logger" in content, (
        "extended.py 顶部必须 import get_logger(P5-B 结构化日志)"
    )
    assert "_logger = get_logger(__name__)" in content, (
        "模块级必须创建 _logger = get_logger(__name__)"
    )


# ---------------------------------------------------------------------------
# 7. 不破坏现有逻辑
# ---------------------------------------------------------------------------
def test_cost_robustness_preserved():
    """新增修改不能破坏已有的 cost 鲁棒解析"""
    content = (PROJECT_ROOT / "src/agent/tools/extended.py").read_text(encoding="utf-8")
    assert "isinstance(cost_raw, (list, dict))" in content, "cost 鲁棒解析必须保留"
    assert "except (TypeError, ValueError)" in content, "cost 解析必须 try/except"


def test_polyline_extraction_preserved():
    """新增修改不能破坏 polyline 嵌套层提取"""
    content = (PROJECT_ROOT / "src/agent/tools/extended.py").read_text(encoding="utf-8")
    assert "bl.get(\"polyline\")" in content, "polyline buslines 提取必须保留"
    assert "step.get(\"polyline\")" in content, "polyline walking steps 提取必须保留"


# ---------------------------------------------------------------------------
# 8. 端到端:无 API key 时优雅降级
# ---------------------------------------------------------------------------
def test_no_api_key_returns_informative_error():
    """无 GAODE_API_KEY 时 TravelPlanningTool.execute 必须返 error 提示"""
    import os
    # 确保无 key
    os.environ.pop("GAODE_API_KEY", None)

    from agent.tools.extended import TravelPlanningTool
    tool = TravelPlanningTool()
    result = tool.execute(origin="北京西站", destination="首都机场", mode="all")

    assert result.success is False
    assert result.error is not None
    # 必须明确告诉用户去配置 key
    assert "GAODE_API_KEY" in result.error or "高德" in result.error, (
        f"错误信息必须提示配置 GAODE_API_KEY,实际:{result.error}"
    )
