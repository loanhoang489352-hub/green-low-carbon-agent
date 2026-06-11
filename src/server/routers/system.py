"""
系统路由: 健康检查、根路径、metrics
P5-E: /api/health 真探活,新增 /api/ready
"""
import os
from pathlib import Path


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
        handler.send_json({
            "ok": payload["status"] != HealthStatus.DOWN,
            "service": "绿色低碳智能体",
            "version": "2.0",
            "langgraph": os.environ.get("USE_LANGGRAPH", "false") == "true",
            "health": payload,
        }, status=http_status)

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
        handler.send_json({
            "ok": True,
            "service": "绿色低碳智能体",
            "metrics": summary,
        })

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

    def knowledge_stats(handler):
        agent = handler.agent
        stats = agent.get_knowledge_stats()
        handler.send_json(stats)

    def rag_stats(handler):
        agent = handler.agent
        handler.send_json({
            "rag_enabled": getattr(agent, "rag_enabled", False),
            "engine": "ok" if getattr(agent, "rag_engine", None) else "not_initialized",
        })

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
                handler.send_json({
                    "state": "idle",
                    "progress": 0,
                    "total": 0,
                    "message": "rag engine not initialized",
                })
                return
            handler.send_json(engine.get_rebuild_status())
        except Exception as e:
            handler.send_json({"state": "error", "message": str(e)}, status=500)

    def policy_latest(handler):
        updater = handler.policy_updater
        policies = updater.get_latest_policies(limit=10)
        handler.send_json({"policies": policies})

    def policy_summary(handler):
        updater = handler.policy_updater
        summary = updater.get_summary()
        handler.send_json({"summary": summary})

    registry.add_route("GET", "/", index, auth_required=False, description="Web 入口")
    registry.add_route("GET", "/index.html", index, auth_required=False, description="Web 入口")
    registry.add_route("GET", "/i18n.js", i18n_js, auth_required=False, description="P6.L: i18n 静态 JS")
    registry.add_route("GET", "/api/health", health, auth_required=False, description="健康检查(P5-E 真探活)")
    registry.add_route("GET", "/api/ready", ready, auth_required=False, description="K8s readiness probe(P5-E)")
    registry.add_route("GET", "/api/metrics", metrics, auth_required=False, description="LLM 调用指标(P5-B)")
    registry.add_route("GET", "/api/knowledge/stats", knowledge_stats, auth_required=False, description="知识库统计")
    registry.add_route("GET", "/api/rag/stats", rag_stats, auth_required=False, description="RAG 状态")
    registry.add_route("GET", "/api/rag/status", rag_status, auth_required=False, description="RAG 异步重建进度(P5-H.C)")
    registry.add_route("GET", "/api/policy/latest", policy_latest, auth_required=False, description="最新政策")
    registry.add_route("GET", "/api/policy/summary", policy_summary, auth_required=False, description="政策摘要")
