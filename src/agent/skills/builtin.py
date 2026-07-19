"""
内置 Skills 和工具
提供低碳智能体所需的基础工具和组合技能
"""

import os
import sys
from pathlib import Path

script_path = Path(__file__).resolve()
project_root = script_path.parent.parent.parent
sys.path.insert(0, str(project_root / "src"))

from typing import List, Dict, Any

try:
    from config_loader import get_default_city

    _DEFAULT_CITY = get_default_city()
except Exception:
    _DEFAULT_CITY = "北京"

from agent.tools.base import BaseTool, ToolResult
from agent.skills.skill import Skill, SkillContext

# P12.4: 节能规划 Skill(独立文件)
from agent.skills.energy_planning_skill import EnergyPlanningSkill


# ============ 基础工具实现 ============


class WeatherTool(BaseTool):
    """天气查询工具"""

    @property
    def name(self) -> str:
        return "weather_query"

    @property
    def description(self) -> str:
        return "查询指定城市的天气信息，用于出行规划。返回温度、天气状况、空气质量等。"

    @property
    def parameters(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "city",
                "type": "string",
                "description": "城市名称，如：北京、濂泉响谷",
                "required": True,
            },
            {
                "name": "date",
                "type": "string",
                "description": "日期，格式 YYYY-MM-DD，默认查询今天",
                "required": False,
                "default": "",
            },
        ]

    def execute(self, **kwargs) -> ToolResult:
        import time

        start = time.time()

        city = kwargs.get("city", "")
        if not city:
            return ToolResult(
                success=False, error="缺少城市参数", execution_time=time.time() - start
            )

        try:
            from utils.web_search import WebSearcher

            web_searcher = WebSearcher()
            weather = web_searcher.fetch_weather_from_api(city)

            if weather and not weather.startswith("获取天气信息失败"):
                return ToolResult(
                    success=True,
                    data={"city": city, "weather": weather},
                    metadata={"source": "web_search"},
                    execution_time=time.time() - start,
                )
            else:
                return ToolResult(
                    success=False,
                    error=f"无法获取 {city} 的天气",
                    execution_time=time.time() - start,
                )
        except Exception as e:
            return ToolResult(
                success=False, error=f"天气查询失败: {str(e)}", execution_time=time.time() - start
            )


class CarbonCalcTool(BaseTool):
    """碳排放计算工具"""

    @property
    def name(self) -> str:
        return "carbon_calc"

    @property
    def description(self) -> str:
        return "计算不同出行方式的碳排放量，帮助用户选择低碳出行方案。"

    @property
    def parameters(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "distance_km",
                "type": "number",
                "description": "出行距离（公里）",
                "required": True,
            },
            {
                "name": "transport_mode",
                "type": "string",
                "description": "出行方式：driving（自驾）、transit（公交）、cycling（骑行）、walking（步行）",
                "required": True,
            },
        ]

    def execute(self, **kwargs) -> ToolResult:
        import time

        start = time.time()

        distance = kwargs.get("distance_km", 0)
        mode = kwargs.get("transport_mode", "transit")

        if distance <= 0:
            return ToolResult(
                success=False, error="距离必须大于0", execution_time=time.time() - start
            )

        # 碳排放系数 (kg CO2/人/km)
        emission_factors = {
            "driving": 0.16,  # 私家车
            "taxi": 0.18,  # 出租车
            "transit": 0.08,  # 公交/地铁
            "cycling": 0.0,  # 骑行
            "walking": 0.0,  # 步行
            "high_speed_rail": 0.06,  # 高铁
            "flight": 0.18,  # 飞机
        }

        factor = emission_factors.get(mode, 0.08)
        carbon_kg = distance * factor

        # 低碳建议
        suggestions = []
        if mode == "driving":
            suggestions.append("建议改为公交或骑行，减少碳排放")
        elif carbon_kg < 0.5:
            suggestions.append("这是低碳出行，继续保持！")

        return ToolResult(
            success=True,
            data={
                "distance_km": distance,
                "transport_mode": mode,
                "carbon_kg": round(carbon_kg, 3),
                "carbon_saved_kg": round(distance * 0.16 - carbon_kg, 3)
                if mode != "driving"
                else 0,
                "suggestions": suggestions,
            },
            execution_time=time.time() - start,
        )


class PublicTransitTool(BaseTool):
    """公共交通查询工具"""

    @property
    def name(self) -> str:
        return "public_transit"

    @property
    def description(self) -> str:
        return "查询公共交通路线（公交、地铁），返回低碳出行方案。"

    @property
    def parameters(self) -> List[Dict[str, Any]]:
        return [
            {"name": "origin", "type": "string", "description": "出发地", "required": True},
            {"name": "destination", "type": "string", "description": "目的地", "required": True},
        ]

    def execute(self, **kwargs) -> ToolResult:
        import time

        start = time.time()

        origin = kwargs.get("origin", "")
        destination = kwargs.get("destination", "")

        if not origin or not destination:
            return ToolResult(
                success=False, error="缺少出发地或目的地", execution_time=time.time() - start
            )

        api_key = os.environ.get("GAODE_API_KEY", "")
        if not api_key:
            return ToolResult(
                success=False,
                error="高德地图API未配置，请设置GAODE_API_KEY",
                execution_time=time.time() - start,
            )

        try:
            import urllib.request
            import urllib.parse
            import json

            # 地址转坐标
            def geocode(addr):
                url = "https://restapi.amap.com/v3/geocode/geo"
                params = {"key": api_key, "address": addr, "city": _DEFAULT_CITY}
                req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params))
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                if data.get("status") == "1" and data.get("geocodes"):
                    return data["geocodes"][0]["location"]
                return None

            origin_coord = geocode(origin)
            dest_coord = geocode(destination)
            if not origin_coord or not dest_coord:
                return ToolResult(
                    success=False,
                    error="地址解析失败，请提供更详细的地址",
                    execution_time=time.time() - start,
                )

            # 公交路线查询
            url = "https://restapi.amap.com/v3/direction/transit/integrated"
            params = {
                "key": api_key,
                "origin": origin_coord,
                "destination": dest_coord,
                "city": _DEFAULT_CITY,
                "datatype": "transit",
            }
            req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params))
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            if data.get("status") != "1" or not data.get("route"):
                return ToolResult(
                    success=False,
                    error="公交路线查询失败，请稍后重试",
                    execution_time=time.time() - start,
                )

            transits = data["route"].get("transits", [])
            if not transits:
                return ToolResult(
                    success=False, error="未找到公交路线方案", execution_time=time.time() - start
                )

            routes = []
            for t in transits[:5]:
                segments = []
                for seg in t.get("segments", []):
                    if seg.get("bus"):
                        buslines = seg["bus"]["buslines"]
                        for bl in buslines[:1]:
                            segments.append(f"公交{bl['name']}")
                    elif seg.get("metro"):
                        segments.append(f"地铁{seg['metro']['name']}")
                    elif seg.get("walking"):
                        steps = seg["walking"].get("steps", [])
                        if steps:
                            segments.append(f"步行{steps[0]['distance']}米")

                distance = int(t.get("distance", 0)) // 1000
                duration = int(t.get("duration", 0)) // 60
                carbon_kg = distance * 0.08  # 公交人均碳排放

                routes.append(
                    {
                        "type": "公交/地铁",
                        "line": " → ".join(segments) if segments else "公交",
                        "duration_min": duration,
                        "distance_km": distance,
                        "carbon_kg": round(carbon_kg, 3),
                        "cost_yuan": int(t.get("cost", 0)),
                    }
                )

            # 推荐低碳路线（优先骑行，其次公共交通）
            recommended = routes[0]
            for r in routes:
                if "步行" in r["line"] or "骑行" in r["line"]:
                    recommended = r
                    break

            return ToolResult(
                success=True,
                data={
                    "origin": origin,
                    "destination": destination,
                    "routes": routes,
                    "recommended": recommended,
                    "source": "高德地图API",
                },
                execution_time=time.time() - start,
            )

        except Exception as e:
            return ToolResult(
                success=False,
                error=f"公交路线查询失败: {str(e)}",
                execution_time=time.time() - start,
            )


class PolicyQueryTool(BaseTool):
    """政策查询工具"""

    @property
    def name(self) -> str:
        return "policy_query"

    @property
    def description(self) -> str:
        return "查询低碳环保相关政策，返回政策内容和解读。"

    @property
    def parameters(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "keyword",
                "type": "string",
                "description": "政策关键词，如：碳中和、新能源、减排",
                "required": True,
            }
        ]

    def execute(self, **kwargs) -> ToolResult:
        import time

        start = time.time()

        keyword = kwargs.get("keyword", "")
        if not keyword:
            return ToolResult(success=False, error="缺少关键词", execution_time=time.time() - start)

        try:
            from policy.updater import PolicyUpdater

            updater = PolicyUpdater()
            policies = updater.get_policies_by_keyword(keyword, limit=10)

            if policies:
                return ToolResult(
                    success=True,
                    data={"keyword": keyword, "policies": policies, "count": len(policies)},
                    execution_time=time.time() - start,
                )
            else:
                # 尝试获取最新政策作为兜底
                latest = updater.get_latest_policies(limit=5)
                return ToolResult(
                    success=False,
                    error=f"未找到与「{keyword}」相关的政策，最新政策：{[p['title'] for p in latest]}",
                    execution_time=time.time() - start,
                )
        except Exception as e:
            return ToolResult(
                success=False, error=f"政策查询失败: {str(e)}", execution_time=time.time() - start
            )


class ProfileUpdateTool(BaseTool):
    """用户画像更新工具"""

    @property
    def name(self) -> str:
        return "profile_update"

    @property
    def description(self) -> str:
        return "根据用户对话内容更新用户画像，记录低碳行为和偏好。"

    @property
    def parameters(self) -> List[Dict[str, Any]]:
        return [
            {"name": "user_id", "type": "string", "description": "用户ID", "required": True},
            {"name": "message", "type": "string", "description": "用户消息内容", "required": True},
            {
                "name": "intent_type",
                "type": "string",
                "description": "意图类型",
                "required": False,
                "default": "",
            },
        ]

    def execute(self, **kwargs) -> ToolResult:
        import time

        start = time.time()

        user_id = kwargs.get("user_id", "")
        message = kwargs.get("message", "")

        if not user_id:
            return ToolResult(success=False, error="缺少用户ID", execution_time=time.time() - start)

        try:
            from user_profile.dynamic_updater import get_profile_updater

            updater = get_profile_updater()

            # 简单的消息分析
            updates = self._analyze_message(message)

            return ToolResult(
                success=True,
                data={"user_id": user_id, "updates": updates},
                execution_time=time.time() - start,
            )
        except Exception as e:
            return ToolResult(
                success=False, error=f"画像更新失败: {str(e)}", execution_time=time.time() - start
            )

    def _analyze_message(self, message: str) -> Dict[str, Any]:
        """分析消息提取画像更新"""
        updates = {}

        # 检测环保相关关键词
        eco_keywords = {
            "骑行": "cycling_frequency",
            "公交": "public_transit_usage",
            "地铁": "metro_usage",
            "步行": "walking_frequency",
            "新能源": "new_energy_interest",
            "碳中和": "carbon_neutral_awareness",
            "垃圾分类": "waste_sorting",
            "节约": "resource_conservation",
            "减排": "emission_reduction",
        }

        found = []
        for keyword, field in eco_keywords.items():
            if keyword in message:
                found.append(field)

        if found:
            updates["eco_behaviors"] = found

        return updates


# ============ 组合 Skills 实现 ============


class LowCarbonTravelSkill(Skill):
    """低碳出行规划 Skill"""

    name = "low_carbon_travel"
    description = "为用户规划低碳、环保的出行方案，综合考虑天气、碳排放、公共交通等因素"
    category = "travel"
    # P10.A:Anthropic Skills 规范元数据
    version = "1.0.0"
    # P11.B:扩展 when_to_use — 加英文关键词 + 弱信号(出门/上班/上学)
    when_to_use = (
        "出行 / 通勤 / 公共交通 / 碳排放 / 公交 / 地铁 / 骑行 / 打车 / 天气 / 路线 / 出门 / 上班 / 上学 / 交通 / 自驾 / 拼车 / 高铁 / 飞机 / 电动车 / 单车 / 步行 / 徒步 / 公里 / 怎么去 / 怎么样去 / 最环保 / 最省碳 / 最绿色 / "
        "transit / commute / travel / carbon / route / weather / bike / cycle / drive / subway / bus / taxi / car / vehicle / emission / footprint / eco / low-carbon / train / flight / km / mile / ride"
    )
    allowed_tools: List[str] = ["weather_query", "carbon_calc", "public_transit"]

    @property
    def tools(self) -> List[BaseTool]:
        return [WeatherTool(), CarbonCalcTool(), PublicTransitTool()]

    def execute(self, context: SkillContext) -> ToolResult:
        import time

        start = time.time()

        destination = context.metadata.get("destination", "")
        user_id = context.user_id

        if not destination:
            return ToolResult(success=False, error="缺少目的地", execution_time=time.time() - start)

        results = {}

        # 1. 查询天气
        weather_tool = WeatherTool()
        weather_result = weather_tool.execute(city=destination)
        results["weather"] = weather_result.data if weather_result.success else None

        # 2. 获取公交路线
        origin = context.metadata.get("origin", _DEFAULT_CITY)
        transit_tool = PublicTransitTool()
        transit_result = transit_tool.execute(origin=origin, destination=destination)
        results["transit"] = transit_result.data if transit_result.success else None

        # 3. 计算骑行碳排放（如果有适合骑行的距离）
        distance = context.metadata.get("distance_km", 10)
        carbon_tool = CarbonCalcTool()
        carbon_result = carbon_tool.execute(distance_km=distance, transport_mode="cycling")
        results["carbon"] = carbon_result.data if carbon_result.success else None

        # 4. 生成建议
        suggestions = []
        if results.get("weather"):
            suggestions.append(f"目的地天气：{results['weather']}")
        if results.get("transit"):
            routes = results["transit"].get("routes", [])
            if routes:
                suggestions.append(
                    f"推荐路线：{routes[0].get('line', '')}，约{routes[0].get('duration_min', '')}分钟"
                )
        if results.get("carbon"):
            carbon_data = results["carbon"]
            suggestions.append(f"骑行{distance}公里碳排放仅{carbon_data.get('carbon_kg', 0)}kg")

        return ToolResult(
            success=True,
            data={
                "destination": destination,
                "weather": results.get("weather"),
                "transit_routes": results.get("transit"),
                "carbon_info": results.get("carbon"),
                "suggestions": suggestions,
            },
            execution_time=time.time() - start,
        )


class PolicyQuerySkill(Skill):
    """政策查询 Skill"""

    name = "policy_query"
    description = "查询和解读低碳环保相关政策，为用户提供专业的政策解读"
    category = "policy"
    # P10.A:Anthropic Skills 规范元数据
    version = "1.0.0"
    # P11.B:扩展 when_to_use — 加英文 + 政策文档类型(意见/通知/标准/指南/办法/要求/规定)
    when_to_use = (
        "政策 / 法规 / 条例 / 补贴 / 碳交易 / 配额 / ccer / cbam / 碳市场 / 监管 / 申报 / 意见 / 通知 / 标准 / 指南 / 办法 / 要求 / 规定 / 低碳补贴 / 激励 / 扶持 / 减排方法学 / 试点 / 清单 / 名录 / "
        "policy / regulation / law / subsidy / incentive / ccer / cbam / carbon market / compliance / carbon trade / allowance / carbon neutrality / emissions cap / emission standard / rule / directive / agreement / legislation"
    )
    allowed_tools: List[str] = ["policy_query"]

    @property
    def tools(self) -> List[BaseTool]:
        return [PolicyQueryTool()]

    def execute(self, context: SkillContext) -> ToolResult:
        import time

        start = time.time()

        keyword = context.message or context.metadata.get("keyword", "碳中和")
        user_id = context.user_id

        policy_tool = PolicyQueryTool()
        result = policy_tool.execute(keyword=keyword)

        if result.success:
            return ToolResult(success=True, data=result.data, execution_time=time.time() - start)
        else:
            return ToolResult(success=False, error=result.error, execution_time=time.time() - start)


class ProfileUpdateSkill(Skill):
    """用户画像管理 Skill"""

    name = "profile_update"
    description = "根据用户对话内容自动分析并更新用户画像，记录低碳行为偏好"
    category = "profile"
    # P10.A:Anthropic Skills 规范元数据
    version = "1.0.0"
    # P11.B:扩展 when_to_use — 加英文 + 加一笔 / 减碳目标
    when_to_use = (
        "画像 / 偏好 / 记录 / 关注 / 更新 / 修改 / 行为 / 记一笔 / 标记 / 兴趣 / 加一笔 / 减碳 / 我的目标 / 环保目标 / 行为日志 / 我的兴趣 / 我的关注 / "
        "profile / preference / record / behavior / log / update / interest / save / track / note / log my / save my / track my / add my"
    )
    allowed_tools: List[str] = ["profile_update"]

    @property
    def tools(self) -> List[BaseTool]:
        return [ProfileUpdateTool()]

    def execute(self, context: SkillContext) -> ToolResult:
        import time

        start = time.time()

        user_id = context.user_id
        message = context.message
        intent_type = context.intent_type

        if not user_id:
            return ToolResult(success=False, error="缺少用户ID", execution_time=time.time() - start)

        profile_tool = ProfileUpdateTool()
        result = profile_tool.execute(user_id=user_id, message=message, intent_type=intent_type)

        return ToolResult(
            success=result.success,
            data=result.data,
            error=result.error,
            execution_time=time.time() - start,
        )


# ============ 公共导出 ============

__all__ = [
    # Tools
    "WeatherTool",
    "CarbonCalcTool",
    "PublicTransitTool",
    "PolicyQueryTool",
    "ProfileUpdateTool",
    # Skills
    "LowCarbonTravelSkill",
    "PolicyQuerySkill",
    "ProfileUpdateSkill",
    # P12.4
    "EnergyPlanningSkill",
]
