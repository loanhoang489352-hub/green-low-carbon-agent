"""
系统路由: 健康检查、根路径
"""
import os
from pathlib import Path


def register_system_routes(registry) -> None:
    """注册系统相关路由"""

    def health(handler):
        handler.send_json({
            "status": "ok",
            "service": "绿色低碳智能体",
            "version": "2.0",
            "langgraph": os.environ.get("USE_LANGGRAPH", "false") == "true",
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
            handler.send_error(404, "HTML file not found")

    def knowledge_stats(handler):
        try:
            agent = handler.agent
            stats = agent.get_knowledge_stats()
            handler.send_json(stats)
        except Exception as e:
            handler.send_json({"error": str(e)}, status=500)

    def rag_stats(handler):
        try:
            agent = handler.agent
            handler.send_json({
                "rag_enabled": getattr(agent, "rag_enabled", False),
                "engine": "ok" if getattr(agent, "rag_engine", None) else "not_initialized",
            })
        except Exception as e:
            handler.send_json({"error": str(e)}, status=500)

    def policy_latest(handler):
        try:
            updater = handler.policy_updater
            policies = updater.get_latest_policies(limit=10)
            handler.send_json({"policies": policies})
        except Exception as e:
            handler.send_json({"error": str(e)}, status=500)

    def policy_summary(handler):
        try:
            updater = handler.policy_updater
            summary = updater.get_summary()
            handler.send_json({"summary": summary})
        except Exception as e:
            handler.send_json({"error": str(e)}, status=500)

    registry.add_route("GET", "/", index, auth_required=False, description="Web 入口")
    registry.add_route("GET", "/index.html", index, auth_required=False, description="Web 入口")
    registry.add_route("GET", "/api/health", health, auth_required=False, description="健康检查")
    registry.add_route("GET", "/api/knowledge/stats", knowledge_stats, auth_required=False, description="知识库统计")
    registry.add_route("GET", "/api/rag/stats", rag_stats, auth_required=False, description="RAG 状态")
    registry.add_route("GET", "/api/policy/latest", policy_latest, auth_required=False, description="最新政策")
    registry.add_route("GET", "/api/policy/summary", policy_summary, auth_required=False, description="政策摘要")
