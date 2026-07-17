"""
系统路由: 健康检查、根路径、metrics
P5-E: /api/health 真探活,新增 /api/ready
"""

import os
from pathlib import Path
from urllib.parse import urlparse, parse_qs


def register_system_routes(registry) -> None:
    """注册系统相关路由"""

    from server.errors import APIError, HealthStatus

    def health(handler):
        """
        GET /api/health - 真探活(P5-E)

        查 accounts.db / user_profiles.db / vector store / scheduler / metrics / 磁盘
        整体 status: ok / degraded / down
        HTTP 状态: 200(ok/degraded) 或 503(down)
        """
        from server.health import health_probe

        payload = health_probe()
        http_status = 200 if payload["status"] != HealthStatus.DOWN else 503
        handler.send_json(
            {
                "ok": payload["status"] != HealthStatus.DOWN,
                "service": "绿色低碳智能体",
                "version": "2.0",
                "langgraph": os.environ.get("USE_LANGGRAPH", "false") == "true",
                "health": payload,
            },
            status=http_status,
        )

    def ready(handler):
        """
        GET /api/ready - K8s readiness probe(P5-E)

        只查 accounts.db,确认服务能接流量
        """
        from server.health import readiness_probe

        payload = readiness_probe()
        handler.send_json(payload, status=200 if payload["ready"] else 503)

    def metrics(handler):
        """
        GET /api/metrics - LLM 调用指标 (P5-B) + Query Cache 指标 (P6.C)

        返回:
        - LLM 聚合:total_calls / error_rate / avg/P50/P95/P99 latency / total_tokens
        - 按 provider 分组
        - history_size (历史保留数)
        - query_cache: hits / misses / sets / invalidations / hit_rate / size / ttl_seconds
        """
        from observability import get_metrics_collector

        summary = get_metrics_collector().summary()
        # P6.C: 加 query_cache 指标
        try:
            from agent.cache import get_query_cache

            summary["query_cache"] = get_query_cache().stats()
        except Exception as e:
            summary["query_cache"] = {"error": str(e)}
        handler.send_json(
            {
                "ok": True,
                "service": "绿色低碳智能体",
                "metrics": summary,
            }
        )

    def index(handler):
        html_path = Path(__file__).resolve().parent.parent.parent / "web" / "index.html"
        if not html_path.exists():
            html_path = handler.project_root / "web" / "index.html"
        if html_path.exists():
            content = html_path.read_text(encoding="utf-8")
            handler.send_response(200)
            handler.send_header("Content-type", "text/html; charset=utf-8")
            handler.end_headers()
            handler.wfile.write(content.encode("utf-8"))
        else:
            raise APIError("NOT_FOUND", "HTML file not found")

    def i18n_js(handler):
        """P6.L: 提供 web/i18n.js 静态文件(浏览器加载用)"""
        js_path = Path(__file__).resolve().parent.parent.parent / "web" / "i18n.js"
        if not js_path.exists():
            js_path = handler.project_root / "web" / "i18n.js"
        if js_path.exists():
            content = js_path.read_text(encoding="utf-8")
            handler.send_response(200)
            handler.send_header("Content-type", "application/javascript; charset=utf-8")
            handler.send_header("Cache-Control", "public, max-age=3600")
            handler.end_headers()
            handler.wfile.write(content.encode("utf-8"))
        else:
            raise APIError("NOT_FOUND", "i18n.js not found")

    def travel_map_js(handler):
        """Bug14: 提供 web/travel-map.js 静态文件(出行地图模块)

        之前前端 script 引用 404,导致 renderTravelMap 永远不加载 → 地图空白
        这里加上服务端路由,显式设 Cache-Control: no-cache 防止浏览器缓存旧版
        """
        js_path = Path(__file__).resolve().parent.parent.parent / "web" / "travel-map.js"
        if not js_path.exists():
            js_path = handler.project_root / "web" / "travel-map.js"
        if js_path.exists():
            content = js_path.read_text(encoding="utf-8")
            handler.send_response(200)
            handler.send_header("Content-type", "application/javascript; charset=utf-8")
            # Bug14: 强制不缓存,确保用户拿到最新版
            handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            handler.send_header("Pragma", "no-cache")
            handler.send_header("Expires", "0")
            handler.end_headers()
            handler.wfile.write(content.encode("utf-8"))
        else:
            raise APIError("NOT_FOUND", "travel-map.js not found")

    def knowledge_stats(handler):
        agent = handler.agent
        stats = agent.get_knowledge_stats()
        handler.send_json(stats)

    def rag_stats(handler):
        agent = handler.agent
        handler.send_json(
            {
                "rag_enabled": getattr(agent, "rag_enabled", False),
                "engine": "ok" if getattr(agent, "rag_engine", None) else "not_initialized",
            }
        )

    def rag_status(handler):
        """P5-H.C: 查 RAG 异步重建进度

        响应字段:
        - state: idle / running / done / error
        - progress: 0-100
        - total: 已索引文档块数(done 时)
        - message: 当前阶段描述或错误信息
        - started_at: 任务开始时间(若有)
        """
        try:
            from rag.rag_engine import get_rag_engine

            engine = get_rag_engine()
            if engine is None or not getattr(engine, "_initialized", False):
                handler.send_json(
                    {
                        "state": "idle",
                        "progress": 0,
                        "total": 0,
                        "message": "rag engine not initialized",
                    }
                )
                return
            handler.send_json(engine.get_rebuild_status())
        except Exception as e:
            handler.send_json({"state": "error", "message": str(e)}, status=500)

    def tools_skills_status(handler):
        """P6.S.15: 列出所有已注册的 tools + skills(用于调试和验证)

        响应:
        - tools: [{name, description, category, tags}, ...]
        - skills: [{name, description, category, tools: [...]}, ...]
        """
        try:
            from agent.tools import get_registry as get_tool_registry
            from agent.skills import get_skill_executor

            tool_reg = get_tool_registry()
            tools_list = []
            for name in tool_reg.list_all():
                meta = tool_reg.get_metadata(name)
                tools_list.append(
                    {
                        "name": name,
                        "description": meta.description if meta else "",
                        "category": meta.category if meta else "",
                        "tags": meta.tags if meta else [],
                    }
                )
            skill_exec = get_skill_executor()
            skills_list = []
            for name in skill_exec.list_all():
                skill = skill_exec.get(name)  # P6.S.15: SkillExecutor.get() not get_skill
                if skill:
                    skills_list.append(
                        {
                            "name": name,
                            "description": getattr(skill, "description", ""),
                            "category": getattr(skill, "category", ""),
                            "tools": [t.name for t in skill.tools],
                        }
                    )
                else:
                    skills_list.append({"name": name})
            handler.send_json(
                {
                    "tools_count": len(tools_list),
                    "skills_count": len(skills_list),
                    "tools": tools_list,
                    "skills": skills_list,
                }
            )
        except Exception as e:
            handler.send_json({"error": str(e)}, status=500)

    def mcp_status(handler):
        """P6.S.16: 列出所有 MCP server 状态 + 它们提供的 tool

        响应:
        - servers: [{name, status, command, tools_count, error}, ...]
        - tools: [{key, server, name, description}, ...]
        """
        try:
            from mcp import get_mcp_registry

            reg = get_mcp_registry()
            handler.send_json(reg.status())
        except Exception as e:
            handler.send_json({"error": str(e), "servers": [], "tools": []}, status=200)

    def geolocate_status(handler):
        """P6.S.22: 调试端点 — 查看当前位置定位结果(3 层 fallback)"""
        try:
            from utils.geolocate import best_location
            from urllib.parse import urlparse, parse_qs

            qs = parse_qs(urlparse(handler.path).query)
            user_id = qs.get("user_id", ["anonymous"])[0]
            geo = best_location(handler=handler, user_id=user_id)
            handler.send_json({"ok": True, "location": geo.to_dict()})
        except Exception as e:
            handler.send_json({"ok": False, "error": str(e)[:200]}, status=200)

    def geolocate_set_browser(handler, data):
        """P6.S.22: 前端浏览器定位回调(用户授权后调此)"""
        try:
            lat = float(data.get("lat", 0))
            lng = float(data.get("lng", 0))
            city = data.get("city", "")
            region = data.get("region", "")
            country = data.get("country", "中国")
            if lat and lng:
                handler._browser_location = {
                    "lat": lat,
                    "lng": lng,
                    "city": city,
                    "region": region,
                    "country": country,
                }
                handler.send_json({"ok": True, "stored": True})
            else:
                handler.send_json({"ok": False, "error": "lat/lng required"}, status=400)
        except Exception as e:
            handler.send_json({"ok": False, "error": str(e)[:200]}, status=200)

    def staticmap(handler):
        """Bug15: 服务端代理高德静态地图 API(避免 API key 暴露前端)

        GET /api/staticmap?bbox=lng1,lat1,lng2,lat2&size=600x400&markers=...
        """
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(handler.path).query)
        bbox = qs.get("bbox", [""])[0]  # lng1,lat1,lng2,lat2
        size = qs.get("size", ["600*400"])[0]  # 高德格式: 600*400
        markers = qs.get("markers", [""])[0]  # mid,color,letter:lng,lat;...
        paths = qs.get("paths", [""])[0]  # weight,color,lng1,lat1;lng2,lat2;...
        zoom = qs.get("zoom", ["11"])[0]
        scale = qs.get("scale", ["1"])[0]
        # 校验 bbox 格式(必须 4 个数字)
        try:
            parts = [float(x) for x in bbox.split(",")]
            if len(parts) != 4:
                raise ValueError("bbox 必须 4 个数字")
        except Exception:
            handler.send_json({"ok": False, "error": "invalid bbox"}, status=400)
            return

        gaode_key = os.environ.get("GAODE_API_KEY", "")
        if not gaode_key:
            handler.send_json({"ok": False, "error": "GAODE_API_KEY 未配置"}, status=500)
            return

        # 构造高德静态地图 URL
        params = {
            "key": gaode_key,
            "location": bbox,  # lng,lat;lng,lat
            "zoom": zoom,
            "size": size,
            "scale": scale,
        }
        if markers:
            params["markers"] = markers
        if paths:
            params["paths"] = paths
        from urllib.parse import urlencode
        amap_url = "https://restapi.amap.com/v3/staticmap?" + urlencode(params)

        try:
            import urllib.request
            req = urllib.request.Request(amap_url, headers={"User-Agent": "green-agent/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read()
                ctype = resp.headers.get("Content-Type", "image/png")
            handler.send_response(200)
            handler.send_header("Content-Type", ctype)
            handler.send_header("Cache-Control", "public, max-age=3600")  # 1h 缓存
            handler.send_header("Access-Control-Allow-Origin", "*")
            handler.end_headers()
            handler.wfile.write(data)
        except Exception as e:
            handler.send_json({"ok": False, "error": f"高德静态图获取失败:{e}"}, status=502)

    def policy_latest(handler):
        updater = handler.policy_updater
        # P6.S.8: 解析 ?limit=N 查询参数(前端传 20,避免硬编码 10 截断)
        try:
            limit = int(parse_qs(urlparse(handler.path).query).get("limit", ["10"])[0])
        except (ValueError, TypeError):
            limit = 10
        limit = max(1, min(limit, 50))  # 上限 50,防恶意大值
        policies = updater.get_latest_policies(limit=limit)
        # P6.S.7: 直返数组(前端 loadPolicies 期望数组)
        handler.send_json(policies)

    def policy_summary(handler):
        updater = handler.policy_updater
        summary = updater.get_summary()
        handler.send_json({"summary": summary})

    registry.add_route("GET", "/", index, auth_required=False, description="Web 入口")
    registry.add_route("GET", "/index.html", index, auth_required=False, description="Web 入口")
    registry.add_route(
        "GET", "/i18n.js", i18n_js, auth_required=False, description="P6.L: i18n 静态 JS"
    )
    registry.add_route(
        "GET", "/travel-map.js", travel_map_js, auth_required=False, description="Bug14: 出行地图 JS 静态文件"
    )
    registry.add_route(
        "GET", "/api/health", health, auth_required=False, description="健康检查(P5-E 真探活)"
    )
    registry.add_route(
        "GET", "/api/ready", ready, auth_required=False, description="K8s readiness probe(P5-E)"
    )
    registry.add_route(
        "GET", "/api/metrics", metrics, auth_required=False, description="LLM 调用指标(P5-B)"
    )
    registry.add_route(
        "GET",
        "/api/knowledge/stats",
        knowledge_stats,
        auth_required=False,
        description="知识库统计",
    )
    registry.add_route(
        "GET", "/api/rag/stats", rag_stats, auth_required=False, description="RAG 状态"
    )
    registry.add_route(
        "GET",
        "/api/rag/status",
        rag_status,
        auth_required=False,
        description="RAG 异步重建进度(P5-H.C)",
    )
    registry.add_route(
        "GET",
        "/api/tools-skills",
        tools_skills_status,
        auth_required=False,
        description="P6.S.15: 已注册 tools + skills 列表",
    )
    registry.add_route(
        "GET",
        "/api/mcp/status",
        mcp_status,
        auth_required=False,
        description="P6.S.16: MCP server 状态 + tool 列表",
    )
    registry.add_route(
        "GET",
        "/api/geolocate",
        geolocate_status,
        auth_required=False,
        description="P6.S.22: 当前位置定位(3 层 fallback)",
    )
    registry.add_route(
        "GET", "/api/staticmap", staticmap, auth_required=False, description="Bug15: 高德静态地图代理"
    )
    registry.add_route(
        "POST",
        "/api/geolocate",
        geolocate_set_browser,
        auth_required=False,
        description="P6.S.22: 设置浏览器定位",
    )
    registry.add_route(
        "GET", "/api/policy/latest", policy_latest, auth_required=False, description="最新政策"
    )
    registry.add_route(
        "GET", "/api/policy/summary", policy_summary, auth_required=False, description="政策摘要"
    )
