"""
扩展工具集
A. 知识库检索工具
B. 碳足迹查询统计工具
C. 出行规划工具（高德真实路径 API；失败时不生成替代路线）
D. 报告导出工具
"""

import os
import sys
import json
import time
import ssl
import math
import urllib.parse  # P6.S.26 fix: 提前 import,内层 _gaode_route 也复用
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path

# Windows UTF-8
if sys.platform == "win32":
    import io

    if not isinstance(sys.stdout, io.TextIOWrapper) or sys.stdout.encoding != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from agent.tools.base import BaseTool, ToolResult
from agent.travel.carbon import assess_route_carbon
from observability import get_logger  # P6.S.26 fix: 结构化日志 + 自动 trace_id

_logger = get_logger(__name__)

try:
    from config_loader import get_default_city

    _DEFAULT_CITY = get_default_city()
except Exception:
    _DEFAULT_CITY = "北京"


# ============ A. 知识库检索工具 ============


class KnowledgeRetrievalTool(BaseTool):
    """知识库检索工具 — 直接调用 RAG Engine"""

    @property
    def name(self) -> str:
        return "knowledge_retrieval"

    @property
    def description(self) -> str:
        return "在知识库中检索与用户问题相关的内容，返回参考知识用于回答。适用于政策查询、环保知识、生活技巧等问题。"

    @property
    def parameters(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "query",
                "type": "string",
                "description": "用户的问题或查询关键词",
                "required": True,
            },
            {
                "name": "top_k",
                "type": "integer",
                "description": "返回结果数量，默认3",
                "required": False,
                "default": 3,
            },
        ]

    def execute(self, **kwargs) -> ToolResult:
        start = time.time()
        query = kwargs.get("query", "")
        top_k = kwargs.get("top_k", 3)

        if not query:
            return ToolResult(
                success=False, error="查询内容不能为空", execution_time=time.time() - start
            )

        try:
            from rag.rag_engine import RAGEngine, RAGConfig

            config = RAGConfig(
                enabled=True,
                provider="sentence-transformers",
                persist_directory=str(Path(__file__).parent.parent.parent / "data" / "vector_db"),
            )
            rag_engine = RAGEngine(config)
            project_root = Path(__file__).parent.parent.parent
            rag_engine.initialize(str(project_root / "knowledge_base"))

            results = rag_engine.retrieve(query, top_k=top_k)

            if not results:
                return ToolResult(
                    success=True,
                    data={"query": query, "results": [], "message": "未找到相关内容"},
                    execution_time=time.time() - start,
                )

            formatted = []
            for r in results:
                formatted.append(
                    {
                        "title": r.metadata.get("title", "") if r.metadata else "",
                        "source": r.metadata.get("source", "") if r.metadata else "",
                        "source_url": r.metadata.get("source_url", "") if r.metadata else "",
                        "evidence_status": r.metadata.get("evidence_status", "unverified") if r.metadata else "unverified",
                        "content": r.content[:300] if len(r.content) > 300 else r.content,
                        "score": r.score if hasattr(r, "score") else 0,
                    }
                )

            return ToolResult(
                success=True,
                data={"query": query, "results": formatted, "count": len(formatted)},
                execution_time=time.time() - start,
            )
        except Exception as e:
            return ToolResult(
                success=False, error=f"知识检索失败: {str(e)}", execution_time=time.time() - start
            )


# ============ B. 碳足迹查询统计工具 ============


class CarbonFootprintTool(BaseTool):
    """碳足迹查询统计工具 — 查询用户累计碳减排数据"""

    @property
    def name(self) -> str:
        return "carbon_footprint_query"

    @property
    def description(self) -> str:
        return "查询用户的碳足迹统计，包括累计碳排放、减排量、分类对比、全国排名等。帮助用户了解自己的低碳生活成效。"

    @property
    def parameters(self) -> List[Dict[str, Any]]:
        return [
            {"name": "user_id", "type": "string", "description": "用户ID", "required": True},
            {
                "name": "period",
                "type": "string",
                "description": "统计周期：week/month/year/all，默认month",
                "required": False,
                "default": "month",
            },
            {
                "name": "category",
                "type": "string",
                "description": "分类筛选：出行/用电/饮食/消费，默认全部",
                "required": False,
                "default": "all",
            },
        ]

    def execute(self, **kwargs) -> ToolResult:
        start = time.time()
        user_id = kwargs.get("user_id", "")
        period = kwargs.get("period", "month")
        category = kwargs.get("category", "all")

        if not user_id:
            return ToolResult(
                success=False, error="user_id不能为空", execution_time=time.time() - start
            )

        try:
            from user_profile.behavior_tracker import get_tracker
            from user_profile.carbon_footprint import CarbonFootprintCalculator

            tracker = get_tracker()
            calculator = CarbonFootprintCalculator()

            # 解析周期
            days_map = {"week": 7, "month": 30, "year": 365, "all": 9999}
            days = days_map.get(period, 30)

            # 获取月报告
            report = calculator.get_monthly_report()

            # 获取用户行为记录
            breakdown = calculator.get_category_breakdown(days)

            # 计算减排成就
            total_reduction = calculator.get_total_reduction(days)
            tree_equivalent = total_reduction / 21  # 吸收1kg CO2需要种21棵树

            # 出行分类统计
            travel_breakdown = {}
            if category in ["all", "出行"]:
                travel_breakdown = self._get_travel_stats(user_id, days)

            # 饮食分类统计
            diet_breakdown = {}
            if category in ["all", "饮食"]:
                diet_breakdown = self._get_diet_stats(user_id, days)

            data = {
                "user_id": user_id,
                "period": period,
                "total_emission_kg": report.get("总排放_kg_CO2", 0),
                "total_reduction_kg": report.get("总减排_kg_CO2", 0),
                "net_emission_kg": report.get("净排放_kg_CO2", 0),
                "grade": report.get("评级", "N/A"),
                "comparison": report.get("对比全国平均", "N/A"),
                "category_breakdown": breakdown,
                "travel_breakdown": travel_breakdown,
                "diet_breakdown": diet_breakdown,
                "achievements": {
                    "total_reduction_kg": round(total_reduction, 2),
                    "tree_equivalent": round(tree_equivalent, 1),
                    "rank_percentile": self._calc_percentile(total_reduction),
                },
                "suggestions": calculator.get_suggestions(),
            }

            return ToolResult(success=True, data=data, execution_time=time.time() - start)

        except Exception as e:
            return ToolResult(
                success=False, error=f"碳足迹查询失败: {str(e)}", execution_time=time.time() - start
            )

    def _get_travel_stats(self, user_id: str, days: int) -> Dict:
        """获取出行分类统计"""
        try:
            import sqlite3
            from datetime import datetime, timedelta

            db_path = Path(__file__).parent.parent.parent / "data" / "behavior_tracker.db"
            if not db_path.exists():
                return {}

            conn = sqlite3.connect(str(db_path))
            c = conn.cursor()

            cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            c.execute(
                """
                SELECT action, SUM(value) as total_km, SUM(carbon_kg) as total_carbon
                FROM behaviors
                WHERE user_id = ? AND category = '出行' AND date >= ?
                GROUP BY action
            """,
                (user_id, cutoff),
            )

            results = {}
            for row in c.fetchall():
                results[row[0]] = {"distance_km": row[1], "carbon_kg": abs(row[2])}

            conn.close()
            return results
        except Exception:
            return {}

    def _get_diet_stats(self, user_id: str, days: int) -> Dict:
        """获取饮食分类统计"""
        try:
            import sqlite3
            from datetime import datetime, timedelta

            db_path = Path(__file__).parent.parent.parent / "data" / "behavior_tracker.db"
            if not db_path.exists():
                return {}

            conn = sqlite3.connect(str(db_path))
            c = conn.cursor()

            cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            c.execute(
                """
                SELECT action, COUNT(*) as times, SUM(value) as total_kg
                FROM behaviors
                WHERE user_id = ? AND category = '饮食' AND date >= ?
                GROUP BY action
            """,
                (user_id, cutoff),
            )

            results = {}
            for row in c.fetchall():
                results[row[0]] = {"times": row[1], "weight_kg": row[2]}

            conn.close()
            return results
        except Exception:
            return {}

    def _calc_percentile(self, reduction_kg: float) -> str:
        """计算减排量相当于全国前百分之多少"""
        # 简化估算：月减排>10kg相当于全国前30%，>20kg前10%，>50kg前1%
        if reduction_kg > 50:
            return "前1%"
        elif reduction_kg > 20:
            return "前10%"
        elif reduction_kg > 10:
            return "前30%"
        elif reduction_kg > 5:
            return "前50%"
        else:
            return "后50%"


# ============ C. 出行规划工具（高德真实路径 API） ============


class TravelPlanningTool(BaseTool):
    """出行规划工具 — 查询真实路线并标注碳排证据状态。"""

    @property
    def name(self) -> str:
        return "travel_planning"

    @property
    def description(self) -> str:
        return ("规划低碳出行方案，输入出发地和目的地，返回公交/地铁/骑行/自驾真实路线；"
                "碳排仅在数据与核算边界可核验时展示，信息不足时明确标为不可核验。"
                "出发地填'当前位置/我家/这里'时，系统会自动用用户实时定位坐标解析，无需用户再提供具体地址。")

    @property
    def parameters(self) -> List[Dict[str, Any]]:
        return [
            {"name": "origin", "type": "string", "description": "出发地(可填'当前位置/我家/这里',系统自动用用户实时定位解析)", "required": True},
            {"name": "destination", "type": "string", "description": "目的地", "required": True},
            {
                "name": "mode",
                "type": "string",
                "description": "偏好方式：transit(公交地铁)/cycling(骑行)/walking(步行)/driving(自驾)/all，默认all",
                "required": False,
                "default": "all",
            },
        ]

    def execute(self, **kwargs) -> ToolResult:
        start = time.time()
        origin = kwargs.get("origin", "")
        destination = kwargs.get("destination", "")
        mode = kwargs.get("mode", "all")
        user_id = kwargs.get("user_id", "")
        city = kwargs.get("city", "")  # 用户真实城市(实时定位/画像解析),用作 geocode 消歧
        location = kwargs.get("location", None)  # 用户真实定位 dict(含 lat/lng/city),精确消歧/起点
        if location is None:
            location = {}

        # P6.S.26 fix: 实例级限流标志(每次 execute 前重置)
        self._last_was_rate_limited = False
        self._last_quota_info = ""

        if not origin or not destination:
            return ToolResult(
                success=False, error="出发地和目的地不能为空", execution_time=time.time() - start
            )

        # 解析 geocode 城市提示:city > location.city > 画像 region > 默认城市。
        # 用于消歧"国贸"这类无城市名的 POI,避免被 geocode 到远处(如新疆)。
        geocode_city = (city or "").strip()
        if not geocode_city and location:
            geocode_city = (location.get("city") or "").strip()
        if not geocode_city and user_id:
            try:
                from utils.geolocate import best_location
                geo = best_location(handler=None, user_id=user_id)
                if geo and geo.city:
                    geocode_city = geo.city
            except Exception:
                geocode_city = ""
        if not geocode_city:
            geocode_city = _DEFAULT_CITY
        # 记住用户真实定位(供"当前位置"起点、目的地距离校验用)
        self._user_location = location or {}

        api_key = os.environ.get("GAODE_API_KEY", "")
        if not api_key:
            _logger.warning(
                "TravelPlanning 未配置 GAODE_API_KEY origin=%r destination=%r",
                origin, destination,
            )
            return ToolResult(
                success=False,
                error="真实路线服务尚未配置，无法生成可验证的出行方案。请配置高德 Web 服务 API Key 后重试。",
                data={"code": "ROUTE_PROVIDER_NOT_CONFIGURED", "routes": [],
                      "source": "高德地图 Web 服务 API"},
                execution_time=time.time() - start,
            )
        else:
            result = self._gaode_route(origin, destination, api_key, geocode_city=geocode_city)
            if not result:
                _logger.warning(
                    "TravelPlanning 高德查询失败 origin=%r destination=%r api_key_configured=%s",
                    origin, destination, bool(api_key),
                )
                code = "ROUTE_PROVIDER_RATE_LIMITED" if self._last_was_rate_limited else "ROUTE_UNAVAILABLE"
                detail = ("路线服务达到调用限制" if self._last_was_rate_limited else
                          "没有取得可验证的路线，请核对起终点或稍后重试")
                return ToolResult(success=False, error=detail,
                    data={"code": code, "routes": [], "source": "高德地图 Web 服务 API",
                          "provider_detail": self._last_quota_info[:120]},
                    execution_time=time.time() - start)

        # 获取出发地天气(影响骑行/步行评分)
        weather_info = self._fetch_weather_at(
            result.get("origin_coord"), geocode_city or _DEFAULT_CITY
        )
        result["weather"] = weather_info
        mode_types = {
            "transit": {"公交+地铁", "公交", "地铁"}, "cycling": {"骑行"},
            "walking": {"步行"}, "driving": {"自驾"}, "all": None,
        }
        allowed = mode_types.get(mode)
        if allowed is not None:
            result["routes"] = [r for r in result["routes"] if r.get("type") in allowed]
        if not result["routes"]:
            return ToolResult(success=False, error="所选出行方式没有取得真实路线。",
                data={**result, "code": "MODE_ROUTE_UNAVAILABLE"},
                execution_time=time.time() - start)

        # 多因素评分: 碳排 + 费用 + 时长 + 天气
        weights = kwargs.get("weights") or {
            "carbon": 0.4,
            "cost": 0.2,
            "duration": 0.2,
            "weather": 0.2,
        }
        result["recommended"] = self._recommend_route(result["routes"], weather_info, weights)
        result["weights"] = weights

        # 真实高德路径用此 source;估算降级路径已在上方设置自己的 source,setdefault 不覆盖
        result.setdefault("source", "高德地图 Web 服务 API")
        carbon_known = sum(r.get("carbon_kg") is not None for r in result["routes"])
        result["data_quality"] = {
            "route_geometry": "provider_observed",
            "distance_duration": "provider_observed",
            "fare": "provider_observed_or_unknown",
            "carbon": ("boundary_limited_or_unavailable_without_activity_data"),
            "carbon_routes_available": carbon_known,
            "carbon_routes_total": len(result["routes"]),
            "weather": "Open-Meteo observed" if weather_info else "unavailable",
        }
        return ToolResult(success=True, data=result, execution_time=time.time() - start)

    def _gaode_route(
        self, origin: str, destination: str, api_key: str, geocode_city: Optional[str] = None
    ) -> Optional[Dict]:
        """调用高德公交路线 API

        geocode_city: geocode 时的城市提示(来自用户真实定位/画像),用于消歧"国贸"这类
        无城市名的 POI,避免被解析到远处。默认 _DEFAULT_CITY。
        """
        geocode_city = geocode_city or _DEFAULT_CITY
        try:
            import urllib.request

            # 地址 → 坐标
            # P6.S.26 fix: fallback 顺序反转 — 先 city=None(全国搜一次命中更准),
            # 没结果再用 geocode_city(用户真实城市)兜底。避免限流时二次调用。
            # fix(歧义名解析): 无城市的 POI(如"国贸")被 geocode 到远处(如新疆)时,
            # 用"起终点相距 >300km"或"距用户坐标 >150km"做校验,换用户城市重试。
            def _coord_dist(c1, c2):
                try:
                    lng1, lat1 = (float(x) for x in c1.split(","))
                    lng2, lat2 = (float(x) for x in c2.split(","))
                    return math.hypot(lng1 - lng2, lat1 - lat2) * 111.0  # 度 → km
                except Exception:
                    return 0.0

            user_loc = getattr(self, "_user_location", None) or {}
            u_lng = user_loc.get("lng")
            u_lat = user_loc.get("lat")

            # 起点是"当前位置/我家/这里/出发地"等 → 直接用用户真实坐标,不 geocode
            origin_is_self = origin in ("当前位置", "我家", "这里", "出发地", "出发", "家", "home")
            if origin_is_self and u_lng and u_lat:
                origin_coord = f"{u_lng},{u_lat}"
            else:
                # 先全国搜(支持跨城),无结果再用用户城市兜底
                origin_coord = self._gaode_geocode(origin, api_key, city=None) or \
                               self._gaode_geocode(origin, api_key, city=geocode_city)

            # 目的地同:先全国搜(跨城"北京→上海"必须 city=None),无结果再落回用户城市
            dest_coord = self._gaode_geocode(destination, api_key, city=None) or \
                         self._gaode_geocode(destination, api_key, city=geocode_city)

            # 距离校验:起终点相距 >300km,或目的地距用户坐标 >150km → 很可能是歧义名解析到远处。
            # 用用户真实城市重试,取更短的组合。
            _too_far = (
                (origin_coord and dest_coord and _coord_dist(origin_coord, dest_coord) > 300.0)
                or (dest_coord and u_lng and u_lat and _coord_dist(dest_coord, f"{u_lng},{u_lat}") > 150.0)
            )
            if _too_far:
                better_dest = self._gaode_geocode(destination, api_key, city=geocode_city)
                if better_dest and _coord_dist(origin_coord or f"{u_lng},{u_lat}", better_dest) < \
                        (_coord_dist(origin_coord, dest_coord) if origin_coord and dest_coord else 1e9) * 0.5:
                    dest_coord = better_dest
                if origin_coord and dest_coord and _coord_dist(origin_coord, dest_coord) > 300.0:
                    better_origin = self._gaode_geocode(origin, api_key, city=geocode_city)
                    if better_origin and _coord_dist(better_origin, dest_coord) < \
                            _coord_dist(origin_coord, dest_coord) * 0.5:
                        origin_coord = better_origin

            if not origin_coord or not dest_coord:
                # P6.S.26 fix: 显式记录 geocode 失败,便于排查
                _logger.warning(
                    "TravelPlanning geocode failed origin=%r dest=%r origin_coord=%r dest_coord=%r",
                    origin, destination, origin_coord, dest_coord,
                )
                return None

            # 公交路线
            # fix(双重编码): 坐标直接交 urlencode 统一编码。原实现先 quote(coord) 再 urlencode,
            # 导致逗号被二次编码成 %252C,高德解析不出坐标 → status!=1 → 误判"高德不可用"而降级估算。
            url = "https://restapi.amap.com/v3/direction/transit/integrated"
            params = {
                "key": api_key,
                "origin": origin_coord,
                "destination": dest_coord,
                "city": geocode_city,
                "datatype": "transit",
            }
            url += "?" + urllib.parse.urlencode(params)

            try:
                data = self._read_json(url)
            except Exception as exc:
                _logger.warning("TravelPlanning transit route unavailable: %s", exc)
                data = {}
            if data and data.get("status") != "1":
                info = str(data.get("info", ""))
                if any(x in info.upper() for x in ("LIMIT", "QUOTA", "CUQPS")):
                    self._last_was_rate_limited = True
                    self._last_quota_info = info
            route = data.get("route") or {}
            transits = route.get("transits", [])

            formatted_routes = []
            for t in transits[:3]:
                line_info = []
                # P6.S.24 + Bug1 fix: polyline 真数据在嵌套层(bus.buslines[].polyline / walking.steps[].polyline)
                polyline_parts = []
                for seg in t.get("segments", []):
                    if seg.get("bus") and seg["bus"].get("buslines"):
                        line_info.append(f"公交{seg['bus']['buslines'][0]['name']}")
                        # busline 自身就有完整 polyline
                        for bl in seg["bus"]["buslines"]:
                            if bl.get("polyline"):
                                polyline_parts.append(bl["polyline"])
                    elif seg.get("metro"):
                        line_info.append(f"地铁{seg['metro']['name']}")
                        # metro 也可能有 buslines 嵌套
                        if seg["metro"].get("buslines"):
                            for bl in seg["metro"]["buslines"]:
                                if bl.get("polyline"):
                                    polyline_parts.append(bl["polyline"])
                    elif seg.get("walking") and seg["walking"].get("steps"):
                        line_info.append(f"步行{seg['walking']['steps'][0].get('distance', 0)}米")
                        # walking 各 step 都有 polyline
                        for step in seg["walking"]["steps"]:
                            if step.get("polyline"):
                                polyline_parts.append(step["polyline"])

                # P6.S.15: 详细分段步骤(步行X米 → 乘X线(站→站,N站) → ...),供 LLM/前端给出"具体怎么走"
                steps = []
                for seg in t.get("segments", []):
                    walk = seg.get("walking") or {}
                    w_steps = walk.get("steps") or []
                    if w_steps:
                        dist = sum(float(s.get("distance", 0) or 0) for s in w_steps)
                        instr = w_steps[0].get("instruction", "") or ""
                        steps.append(f"步行{int(dist)}米" + (f"({instr})" if instr else ""))
                    bus = seg.get("bus") or {}
                    for bl in bus.get("buslines", []) or []:
                        name = bl.get("name", "公交")
                        dep = (bl.get("departure_stop") or {}).get("name", "")
                        arr = (bl.get("arrival_stop") or {}).get("name", "")
                        via = bl.get("via_num", 0)
                        try:
                            via_n = int(via)
                        except (TypeError, ValueError):
                            via_n = 0
                        steps.append(f"乘坐{name}({dep}→{arr}{',' + str(via_n) + '站' if via_n else ''})")
                    metro = seg.get("metro") or {}
                    if metro and metro.get("name"):
                        dep = (metro.get("departure_stop") or {}).get("name", "")
                        arr = (metro.get("arrival_stop") or {}).get("name", "")
                        via = metro.get("via_num", 0)
                        try:
                            via_n = int(via)
                        except (TypeError, ValueError):
                            via_n = 0
                        steps.append(f"乘坐{metro['name']}({dep}→{arr}{',' + str(via_n) + '站' if via_n else ''})")

                # Bug1 + Bug19 fix: 高德返回的 cost 可能是 [] / {} / "3.0" 多种类型
                # 优先从顶层 cost 读取,若为空数组则从 segments 累加 cost(公交+地铁通常每段都有 cost)
                cost_raw = t.get("cost", 0)
                cost_yuan = 0
                if isinstance(cost_raw, (list, dict)):
                    # 顶层 cost 空,尝试从 segments 累加
                    seg_cost = 0.0
                    for seg in t.get("segments", []):
                        if isinstance(seg.get("cost"), (int, float, str)):
                            try:
                                seg_cost += float(seg["cost"])
                            except (TypeError, ValueError):
                                pass
                        # buslines/metro 内部 buslines 也有 cost
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
                    cost_yuan = round(seg_cost, 1) if seg_cost > 0 else 0
                else:
                    try:
                        cost_yuan = round(float(cost_raw), 1)
                    except (TypeError, ValueError):
                        cost_yuan = 0

                # P6.S.26 fix: 保留 1 位小数,避免 <1km 段显示 0.0km
                # duration 高德返秒,distance 高德返米
                duration = round(float(t.get("duration", 0)) / 60, 1)
                distance = round(float(t.get("distance", 0)) / 1000, 1)
                # P6.S.24: 拼接 polyline(各段用 ; 分隔,前端解码)
                polyline = ";".join(polyline_parts) if polyline_parts else None

                formatted_routes.append(
                    {
                        "type": "公交+地铁",
                        "line": " → ".join(line_info) if line_info else "公交",
                        "steps": steps,            # P6.S.15: 详细分段步骤(步行/乘X线/换乘)
                        "duration_min": duration,
                        "distance_km": distance,
                        **assess_route_carbon("公交+地铁"),
                        "cost_yuan": cost_yuan if cost_yuan > 0 else None,
                        "polyline": polyline,    # Bug1 fix: 嵌套层提取
                        "from": origin,
                        "to": destination,
                        "route_source": "高德公交换乘路径规划 API",
                        "fare_source": "高德返回票价" if cost_yuan > 0 else "unavailable",
                    }
                )

            # 骑行路线
            cycling_url = "https://restapi.amap.com/v4/direction/bicycling"
            cycling_params = {
                "key": api_key,
                "origin": origin_coord,           # 只经 urlencode 编码一次,避免逗号二次编码成 %252C
                "destination": dest_coord,
            }
            cycling_url += "?" + urllib.parse.urlencode(cycling_params)

            cycling_result = None
            try:
                cycling_data = self._read_json(cycling_url)
                if str(cycling_data.get("errcode")) == "0" and cycling_data.get("data"):
                    paths = cycling_data["data"].get("paths", [])
                    if paths:
                        p = paths[0]
                        # P6.S.26 fix: 距离/时长保留 1 位小数
                        cycling_result = {
                            "type": "骑行",
                            "distance_km": round(float(p.get("distance", 0)) / 1000, 1),
                            "duration_min": round(float(p.get("duration", 0)) / 60, 1),
                            **assess_route_carbon("骑行"),
                            "cost_yuan": 0,
                            "polyline": ";".join(s.get("polyline", "") for s in p.get("steps", []) if s.get("polyline")),
                            "steps": [s.get("instruction") for s in p.get("steps", []) if s.get("instruction")],
                            "route_source": "高德骑行路径规划 API",
                            "from": origin,
                            "to": destination,
                        }
            except Exception:
                # 跨城骑行(>50km)通常没有数据,不报错
                pass

            all_routes = formatted_routes
            if cycling_result:
                all_routes.append(cycling_result)

            driving = self._gaode_simple_route(
                "https://restapi.amap.com/v3/direction/driving", origin_coord,
                dest_coord, api_key, "自驾",
                params={"extensions": "base", "strategy": "10"},
            )
            if driving:
                all_routes.append(driving)
            walking = self._gaode_simple_route(
                "https://restapi.amap.com/v3/direction/walking", origin_coord,
                dest_coord, api_key, "步行",
            )
            if walking and walking["distance_km"] <= 10:
                all_routes.append(walking)

            navigation_modes = {"自驾": "car", "公交+地铁": "bus", "公交": "bus",
                                "地铁": "bus", "骑行": "ride", "步行": "walk"}
            for item in all_routes:
                nav = {
                    "from": f"{origin_coord},{origin}", "to": f"{dest_coord},{destination}",
                    "mode": navigation_modes.get(item.get("type"), "car"),
                    "policy": "1", "src": "green-agent", "coordinate": "gaode",
                    "callnative": "1",
                }
                item["navigation_url"] = "https://uri.amap.com/navigation?" + urllib.parse.urlencode(nav)

            # P6.S.24: 在 response 顶层附上 origin/dest 坐标,供前端 Leaflet marker 用
            def _coord_to_latlng(coord_str):
                """高德坐标 'lng,lat' → {lat, lng}"""
                if not coord_str or "," not in coord_str:
                    return None
                try:
                    lng, lat = coord_str.split(",", 1)
                    return {"lat": float(lat), "lng": float(lng)}
                except (ValueError, TypeError):
                    return None

            return {
                "origin": origin,
                "destination": destination,
                "origin_coord": _coord_to_latlng(origin_coord),
                "destination_coord": _coord_to_latlng(dest_coord),
                "routes": all_routes,
            }

        except Exception as e:
            # P6.S.26 fix: 用结构化 logger 替代 print,带 trace_id + 上下文
            # (原 print 无 trace_id 串不到 LLM 调用,排查极困难)
            _logger.error(
                "TravelPlanning 出行规划失败 origin=%r destination=%r api_key_configured=%s error=%s: %s",
                origin, destination, bool(api_key), type(e).__name__, e,
                exc_info=True,
            )
            return None

    def _gaode_geocode(
        self, address: str, api_key: str, city: Optional[str] = None
    ) -> Optional[str]:
        """地址转坐标(city=None 时让高德自动判断,适用于跨城查询)"""
        try:
            import urllib.request

            url = "https://restapi.amap.com/v3/geocode/geo"
            params = {"key": api_key, "address": address}
            if city:
                params["city"] = city
            url += "?" + urllib.parse.urlencode(params)

            data = self._read_json(url)

            if data.get("status") == "1" and data.get("geocodes"):
                return data["geocodes"][0]["location"]
            # P6.S.26 fix: 高德明确返 status=0 时也记 warning(配额/拼写错误)
            info = data.get("info", "")
            # 检测高德 QPS 限流 — 设实例标志供 execute() 透传
            if info and ("CUQPS" in info or "LIMIT" in info or "限流" in info or "QUOTA" in info.upper()):
                self._last_was_rate_limited = True
                self._last_quota_info = info
            _logger.warning(
                "TravelPlanning geocode status!=1 address=%r city=%r response_status=%s info=%s",
                address, city, data.get("status"), info,
            )
        except Exception as e:
            # P6.S.26 fix: 结构化日志替代静默 pass
            _logger.warning(
                "TravelPlanning geocode exception address=%r city=%r error=%s: %s",
                address, city, type(e).__name__, e,
            )
        return None

    def _gaode_simple_route(self, endpoint, origin, destination, api_key,
                            route_type, params=None):
        """Read a walking/driving path directly from Amap; never infer it from another mode."""
        try:
            import urllib.request
            query = {"key": api_key, "origin": origin, "destination": destination}
            query.update(params or {})
            payload = self._read_json(endpoint + "?" + urllib.parse.urlencode(query))
            if payload.get("status") != "1":
                return None
            path = ((payload.get("route") or {}).get("paths") or [None])[0]
            if not path:
                return None
            steps = path.get("steps") or []
            distance = round(float(path.get("distance", 0)) / 1000, 1)
            return {
                "type": route_type, "line": "全程" + route_type,
                "distance_km": distance,
                "duration_min": round(float(path.get("duration", 0)) / 60, 1),
                **assess_route_carbon(route_type),
                "cost_yuan": None,
                "polyline": ";".join(s.get("polyline", "") for s in steps if s.get("polyline")),
                "steps": [s.get("instruction") for s in steps if s.get("instruction")],
                "route_source": "高德" + route_type + "路径规划 API",
                "cost_note": "未取得可核验费用，不展示估算金额",
            }
        except Exception as exc:
            _logger.warning("TravelPlanning %s route unavailable: %s", route_type, exc)
            return None

    @staticmethod
    def _read_json(url: str, attempts: int = 2) -> Dict:
        """Read provider JSON with bounded retries; never substitute local data."""
        import urllib.request

        last_error = None
        insecure = os.environ.get("INSECURE_SKIP_VERIFY", "").lower() in {"1", "true", "yes"}
        context = ssl._create_unverified_context() if insecure else None
        for attempt in range(attempts):
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "green-agent/1.0"})
                kwargs = {"timeout": 8}
                if context is not None:
                    kwargs["context"] = context
                with urllib.request.urlopen(request, **kwargs) as response:
                    return json.loads(response.read().decode("utf-8"))
            except Exception as exc:
                last_error = exc
                if attempt + 1 < attempts:
                    time.sleep(0.2 * (attempt + 1))
        raise last_error or OSError("provider request failed")

    def _fetch_weather_at(self, coord: Optional[Dict], city: str) -> Optional[Dict]:
        """Use the resolved origin coordinate, avoiding a second ambiguous city lookup."""
        if not coord:
            return self._fetch_weather(city)
        try:
            import urllib.request
            url = ("https://api.open-meteo.com/v1/forecast?latitude=" +
                   urllib.parse.quote(str(coord["lat"])) + "&longitude=" +
                   urllib.parse.quote(str(coord["lng"])) + "&current_weather=true")
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            cw = data.get("current_weather") or {}
            from utils.web_search import WebSearcher
            code = cw.get("weathercode", 0)
            return {"city": city, "temp_c": cw.get("temperature"),
                    "wind_kmh": cw.get("windspeed"), "weathercode": code,
                    "description": WebSearcher._WEATHER_CODE_CN.get(code, f"代码{code}"),
                    "source": "Open-Meteo current weather", "coordinate": coord}
        except Exception:
            return None

    def _fetch_weather(self, city: str) -> Optional[Dict]:
        """获取天气(失败返回 None,不阻塞推荐)"""
        try:
            from utils.web_search import WebSearcher

            ws = WebSearcher()
            # 直接拿原始字段而非格式化字符串(用 Open-Meteo 的两步调用)
            import urllib.request
            import urllib.parse
            import json as _json

            geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote(city)}&count=1&language=zh"
            req = urllib.request.Request(geo_url, headers=ws.session_headers)
            with urllib.request.urlopen(req, timeout=5) as resp:
                geo = _json.loads(resp.read().decode("utf-8"))
            results = geo.get("results") or []
            if not results:
                return None
            lat, lon = results[0]["latitude"], results[0]["longitude"]
            w_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
            req2 = urllib.request.Request(w_url, headers=ws.session_headers)
            with urllib.request.urlopen(req2, timeout=5) as resp2:
                data = _json.loads(resp2.read().decode("utf-8"))
            cw = data.get("current_weather") or {}
            code = cw.get("weathercode", 0)
            return {
                "city": city,
                "temp_c": cw.get("temperature"),
                "wind_kmh": cw.get("windspeed"),
                "weathercode": code,
                "description": ws._WEATHER_CODE_CN.get(code, f"代码{code}"),
            }
        except Exception:
            return None

    def _weather_penalty(self, route_type: str, weather: Optional[Dict]) -> tuple:
        """计算天气对路线的不适程度 (penalty 0-1, reason 字符串).
        仅对露天模式(骑行/步行)生效;公交/自驾/地铁不受天气影响."""
        if not weather or route_type not in ("骑行", "步行"):
            return 0.0, ""

        reasons = []
        penalty = 0.0

        code = weather.get("weathercode", 0)
        desc = weather.get("description", "")
        # WMO 降水细分: 轻降水可骑(提示),中重度过滤
        if code in (51, 53, 56):  # 毛毛雨/轻冻雨
            penalty += 0.35
            reasons.append(f"轻度降水({desc})")
        elif code in (55, 61, 80):  # 浓密毛毛雨/小雨/小阵雨
            penalty += 0.5
            reasons.append(desc)
        elif code in (57, 63, 65, 66, 67, 81, 82):  # 中重度雨/冻雨/阵雨
            penalty += 0.7
            reasons.append(desc)
        elif 71 <= code <= 77 or 85 <= code <= 86:  # 降雪
            penalty += 0.7
            reasons.append(desc)
        elif 95 <= code <= 99:  # 雷暴
            penalty += 0.9
            reasons.append(desc)
        elif code in (45, 48):  # 雾
            penalty += 0.3
            reasons.append("雾天能见度低")

        wind = weather.get("wind_kmh") or 0
        if wind >= 40:
            penalty += 0.3
            reasons.append(f"大风{wind}km/h")
        elif wind >= 25:
            penalty += 0.15
            reasons.append(f"风力较大{wind}km/h")

        temp = weather.get("temp_c")
        if temp is not None:
            if temp >= 35:
                penalty += 0.25
                reasons.append(f"高温{temp}°C")
            elif temp <= 0:
                penalty += 0.2
                reasons.append(f"低温{temp}°C")

        return min(penalty, 1.0), "、".join(reasons)

    def _recommend_route(
        self, routes: List[Dict], weather: Optional[Dict] = None, weights: Optional[Dict] = None
    ) -> Dict:
        """多因素评分: 碳排 + 费用 + 时长 + 天气适宜度.
        每个因素归一化到 [0,1](越大越好),加权求和;
        天气扣分仅对骑行/步行生效."""
        if not routes:
            return {}
        weights = weights or {"carbon": 0.4, "cost": 0.2, "duration": 0.2, "weather": 0.2}

        known_carbons = [float(r["carbon_kg"]) for r in routes
                         if r.get("carbon_kg") is not None]
        max_carbon = max(known_carbons) if known_carbons else 1.0
        max_carbon = max_carbon or 1.0
        known_costs = [float(r["cost_yuan"]) for r in routes if r.get("cost_yuan") is not None]
        # All known fares may legitimately be zero (walking/cycling).  Keep the
        # denominator non-zero while preserving a perfect score for those modes.
        max_cost = max(known_costs) if known_costs else 1.0
        max_cost = max_cost or 1.0
        max_dur = max((r.get("duration_min") or 0) for r in routes) or 1.0

        for r in routes:
            carbon_score = (None if r.get("carbon_kg") is None else
                            1.0 - float(r["carbon_kg"]) / max_carbon)
            # Unknown fare is neutral. It must not beat a known route as if it were free.
            cost_score = (0.5 if r.get("cost_yuan") is None else
                          1.0 - float(r["cost_yuan"]) / max_cost)
            dur_score = 1.0 - (r.get("duration_min") or 0) / max_dur
            penalty, reason = self._weather_penalty(r.get("type", ""), weather)
            weather_score = 1.0 - penalty

            dimension_scores = {
                "carbon": carbon_score,
                "cost": cost_score,
                "duration": dur_score,
                "weather": weather_score,
            }
            available_weight = sum(
                float(weights.get(name, 0)) for name, score in dimension_scores.items()
                if score is not None
            ) or 1.0
            effective_weights = {
                name: (round(float(weights.get(name, 0)) / available_weight, 4)
                       if score is not None else 0.0)
                for name, score in dimension_scores.items()
            }
            total = sum(
                float(score) * effective_weights[name]
                for name, score in dimension_scores.items() if score is not None
            )
            # 打磨: 长途骑行降分(>8km 别推荐全程骑),首末段步行过长(<1km)也降分(建议骑行接驳)
            rtype = r.get("type", "")
            dist = r.get("distance_km", 0) or 0
            line = r.get("line", "") or ""
            if rtype == "骑行" and dist > 8:
                total *= 0.6
                r["_hint"] = f"全程骑行{dist:.0f}km较远,体力要求高"
            if rtype in ("公交+地铁", "公交", "地铁"):
                import re as _re
                m_walk = _re.search(r"步行(\d+(?:\.\d+)?)米", line)
                if m_walk and float(m_walk.group(1)) > 1000:
                    total *= 0.75
                    r["_hint"] = f"首末段步行{float(m_walk.group(1))/1000:.1f}km较长,可考虑共享单车接驳"
            r["score"] = round(total, 3)
            r["score_breakdown"] = {
                "carbon": None if carbon_score is None else round(carbon_score, 2),
                "cost": round(cost_score, 2),
                "duration": round(dur_score, 2),
                "weather": round(weather_score, 2),
            }
            r["effective_weights"] = effective_weights
            r["score_note"] = (
                "仅使用有数据的维度并重新归一化权重；未知值未按零处理"
            )
            if reason:
                r["weather_note"] = reason
            # 严重不良天气(penalty>0.5)硬过滤露天模式,避免推荐危险出行
            r["_disqualified"] = penalty > 0.5

        candidates = [r for r in routes if not r.get("_disqualified")] or routes
        best = max(candidates, key=lambda x: x.get("score", 0))
        # 清理临时标记
        for r in routes:
            r.pop("_disqualified", None)
        return best


# ============ D. 报告导出工具 ============


class ReportExportTool(BaseTool):
    """报告导出工具 — 生成 Markdown 格式低碳生活报告"""

    @property
    def name(self) -> str:
        return "report_export"

    @property
    def description(self) -> str:
        return "为用户生成低碳生活报告（Markdown格式），包含碳足迹统计、减排成就、行为记录分析等内容，可用于分享或存档。"

    @property
    def parameters(self) -> List[Dict[str, Any]]:
        return [
            {"name": "user_id", "type": "string", "description": "用户ID", "required": True},
            {
                "name": "period",
                "type": "string",
                "description": "报告周期：week/month/year，默认month",
                "required": False,
                "default": "month",
            },
            {
                "name": "include_achievements",
                "type": "boolean",
                "description": "是否包含成就徽章，默认True",
                "required": False,
                "default": True,
            },
        ]

    def execute(self, **kwargs) -> ToolResult:
        start = time.time()
        user_id = kwargs.get("user_id", "")
        period = kwargs.get("period", "month")
        include_achievements = kwargs.get("include_achievements", True)

        if not user_id:
            return ToolResult(
                success=False, error="user_id不能为空", execution_time=time.time() - start
            )

        try:
            from user_profile.behavior_tracker import get_tracker
            from user_profile.user_profile import UserProfileManager

            tracker = get_tracker()
            profile_mgr = UserProfileManager()
            profile = profile_mgr.get_profile(user_id)

            # 获取数据
            days_map = {"week": 7, "month": 30, "year": 365}
            days = days_map.get(period, 30)
            period_label = {"week": "近7天", "month": "近30天", "year": "近1年"}.get(
                period, "近30天"
            )

            # 碳足迹
            from user_profile.carbon_footprint import CarbonFootprintCalculator

            calculator = CarbonFootprintCalculator()
            report = calculator.get_monthly_report()
            breakdown = calculator.get_category_breakdown(days)
            total_reduction = calculator.get_total_reduction(days)

            # 用户信息
            basic_info = profile.get("basic_info", {}) if profile else {}
            eco_profile = profile.get("eco_profile", {}) if profile else {}
            knowledge_level = eco_profile.get("knowledge_level", "intermediate")
            behavior_stage = eco_profile.get("behavior_stage", "意向")

            # 成就
            achievements = {}
            if include_achievements:
                try:
                    ach = tracker.get_achievements(user_id)
                    if isinstance(ach, dict):
                        achievements = ach
                except Exception:
                    pass

            # 生成 Markdown
            md = self._build_markdown(
                user_id=user_id,
                period_label=period_label,
                profile=profile,
                report=report,
                breakdown=breakdown,
                total_reduction=total_reduction,
                achievements=achievements,
                knowledge_level=knowledge_level,
                behavior_stage=behavior_stage,
            )

            # 保存文件
            reports_dir = Path(__file__).parent.parent.parent / "data" / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)
            filename = f"低碳报告_{user_id}_{datetime.now().strftime('%Y%m%d')}.md"
            filepath = reports_dir / filename

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(md)

            return ToolResult(
                success=True,
                data={
                    "user_id": user_id,
                    "period": period_label,
                    "filename": filename,
                    "filepath": str(filepath),
                    "content_preview": md[:500],
                    "summary": {
                        "total_emission_kg": report.get("总排放_kg_CO2", 0),
                        "total_reduction_kg": report.get("总减排_kg_CO2", 0),
                        "grade": report.get("评级", "N/A"),
                    },
                },
                execution_time=time.time() - start,
            )

        except Exception as e:
            return ToolResult(
                success=False, error=f"报告生成失败: {str(e)}", execution_time=time.time() - start
            )

    def _build_markdown(
        self,
        user_id: str,
        period_label: str,
        profile: Dict,
        report: Dict,
        breakdown: Dict,
        total_reduction: float,
        achievements: Dict,
        knowledge_level: str,
        behavior_stage: str,
    ) -> str:
        """构建 Markdown 报告内容"""

        level_map = {"beginner": "入门", "intermediate": "了解", "advanced": "精通"}
        level_cn = level_map.get(knowledge_level, "了解")

        lines = [
            "# 🌿 绿色低碳生活报告",
            "",
            f"**用户ID**: `{user_id}`",
            f"**报告周期**: {period_label}",
            f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
            "---",
            "",
            "## 📊 碳足迹总览",
            "",
            "|指标 | 数值 |",
            "|------|------|",
            f"| 总排放 | {report.get('总排放_kg_CO2', 0):.1f} kg CO₂ |",
            f"| 总减排 | {report.get('总减排_kg_CO2', 0):.1f} kg CO₂ |",
            f"| 净排放 | {report.get('净排放_kg_CO2', 0):.1f} kg CO₂ |",
            f"| 评级 | {report.get('评级', 'N/A')} |",
            f"| 对比全国平均 | {report.get('对比全国平均', 'N/A')} |",
            "",
        ]

        # 分类排放
        if breakdown:
            lines.extend(
                [
                    "## 📈分类排放统计",
                    "",
                    "| 类别 | 排放量(kg CO₂) |",
                    "|------|----------------|",
                ]
            )
            for cat, val in breakdown.items():
                lines.append(f"| {cat} | {val:.1f} |")
            lines.append("")

        # 减排成就
        if total_reduction > 0:
            tree_equivalent = total_reduction / 21
            lines.extend(
                [
                    "##🏆 减排成就",
                    "",
                    f"-累计减排 **{total_reduction:.1f} kg CO₂**",
                    f"- 相当于种植 **{tree_equivalent:.1f} 棵树**（每年吸收量）",
                    f"- 环保认知水平：{level_cn}",
                    f"- 行为阶段：{behavior_stage}",
                    "",
                ]
            )

        # 用户画像
        if profile:
            basic = profile.get("basic_info", {})
            if basic:
                lines.extend(
                    [
                        "## 👤 用户画像",
                        "",
                        f"- 地区：{basic.get('region', '未知')}",
                        f"- 年龄段：{basic.get('age_group', '未知')}",
                        f"- 环保认知：{level_cn}",
                        f"- 行为阶段：{behavior_stage}",
                        "",
                    ]
                )

        # 行为建议
        suggestions = report.get("suggestions", [])
        if suggestions:
            lines.extend(
                [
                    "## 💡 改进建议",
                    "",
                ]
            )
            for s in suggestions[:3]:
                action = s.get("action", "")
                potential = s.get("减排潜力", "")
                lines.append(f"- **{action}**：{potential}")
            lines.append("")

        lines.extend(
            [
                "---",
                "",
                "*本报告由绿色低碳智能体自动生成*",
                f"*报告周期：{period_label}*",
            ]
        )

        return "\n".join(lines)
