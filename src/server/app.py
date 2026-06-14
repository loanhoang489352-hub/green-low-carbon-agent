"""
应用工厂
将 RequestHandler 改造为通过 RouterRegistry 分发
P5-D: _dispatch 接入 with_auth 中间件
P5-E: _dispatch 接入 APIError,异常不再泄栈
"""
import json
import logging
import os
import sys
import uuid
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, parse_qs

from .errors import APIError
from .router import Route, get_registry, is_auth_enabled
from .routers import register_all_routes

_log = logging.getLogger("server.app")

# 确保 src 在路径中
script_path = Path(__file__).resolve()
SRC_DIR = script_path.parent.parent
PROJECT_ROOT = SRC_DIR.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


MAX_BODY_SIZE = 2_000_000
DEFAULT_CORS_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000,http://localhost:8000"


def _is_rate_limit_enabled() -> bool:
    """P5-I.B: 限流开关(默认开;RATE_LIMIT_ENABLED=false 关闭)"""
    return os.environ.get("RATE_LIMIT_ENABLED", "true").lower() in ("1", "true", "yes", "on")


def _audit_action_for(path: str) -> str:
    """路径 → 审计 action 标识"""
    # /api/auth/login → "auth.login"
    if path.startswith("/api/auth/login"):
        return "auth.login"
    if path.startswith("/api/auth/register"):
        return "auth.register"
    if path.startswith("/api/auth/logout"):
        return "auth.logout"
    if path.startswith("/api/chat/enhanced"):
        return "chat.enhanced"
    if path.startswith("/api/chat"):
        return "chat.basic"
    if path.startswith("/api/feedback"):
        return "feedback.submit"
    if path.startswith("/api/profile"):
        return "profile.update"
    if path.startswith("/api/onboarding"):
        return "onboarding"
    if path.startswith("/api/policy/sync"):
        return "policy.sync"
    if path.startswith("/api/knowledge/reload"):
        return "knowledge.reload"
    if path.startswith("/api/memory"):
        return "memory.read"
    return f"endpoint.{path.strip('/').replace('/', '.')}"


_AUDITED_PATHS = (
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/logout",
    "/api/chat/enhanced",
    "/api/feedback",
    "/api/profile",
    "/api/onboarding",
    "/api/policy/sync",
    "/api/knowledge/reload",
)


def _is_audit_endpoint(path: str, method: str) -> bool:
    """只对敏感端点写审计(避免 audit_log 爆炸)"""
    if method == "GET":
        return False
    return any(path.startswith(p) for p in _AUDITED_PATHS)


class RoutedRequestHandler(BaseHTTPRequestHandler):
    """通过 RouterRegistry 分发的请求处理器"""

    project_root = PROJECT_ROOT

    def _cors_origin(self) -> str:
        allowed = os.environ.get("CORS_ORIGINS", DEFAULT_CORS_ORIGINS)
        origins = [o.strip() for o in allowed.split(",") if o.strip()]
        if not origins:
            return "http://127.0.0.1:8000"
        return ",".join(origins)

    def send_json(self, data, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", self._cors_origin())
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", self._cors_origin())
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _read_body(self) -> str:
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > MAX_BODY_SIZE:
            raise APIError("BODY_TOO_LARGE", f"Body too large (max {MAX_BODY_SIZE})")
        if content_length < 0:
            raise APIError("BAD_REQUEST", "Invalid Content-Length")
        return self.rfile.read(content_length).decode("utf-8") if content_length else ""

    def _dispatch(self, method: str):
        parsed = urlparse(self.path)
        path = parsed.path
        body = ""
        data: dict = {}
        try:
            body = self._read_body() if method == "POST" else ""
            if body:
                try:
                    data = json.loads(body)
                except Exception as e:
                    raise APIError("BAD_REQUEST", f"Invalid JSON: {e}")
        except APIError as ae:
            self.send_json(ae.to_dict(), status=ae.status)
            return

        # P5-I.B: IP 限流(早于鉴权,防暴力破解)
        if _is_rate_limit_enabled():
            from server.middleware.rate_limit import get_rate_limiter
            allowed, retry_after = get_rate_limiter().check(self)
            if not allowed:
                # 限流也写一条审计
                try:
                    from server.middleware.audit import record_audit
                    record_audit(
                        action="ratelimit.exceeded",
                        target=f"{method} {path}",
                        ip=self.client_address[0] if self.client_address else None,
                        user_agent=self.headers.get("User-Agent") if hasattr(self, "headers") else None,
                        status_code=429,
                        detail=f"retry_after={retry_after}",
                    )
                except Exception:
                    pass
                self.send_json({
                    "code": "RATE_LIMITED",
                    "message": "请求过于频繁",
                    "retry_after": retry_after,
                }, status=429)
                return

        registry = get_registry()
        route = registry.find(method, path)
        if route is None:
            ae = APIError("NOT_FOUND", f"Not Found: {method} {path}")
            self.send_json(ae.to_dict(), status=ae.status)
            return

        # P5-D: 鉴权中间件
        auth_failed = False
        identity = None
        if route.auth_required and is_auth_enabled():
            try:
                from auth.account_manager import AccountManager
                if not hasattr(self.__class__, "_auth_account_mgr"):
                    self.__class__._auth_account_mgr = AccountManager()
                mgr = self.__class__._auth_account_mgr
                identity = mgr.verify_token(self.headers, data)
            except Exception:
                identity = None
            if identity is None:
                auth_failed = True
                # 鉴权失败也写审计
                try:
                    from server.middleware.audit import record_audit
                    record_audit(
                        action="auth.unauthorized",
                        target=f"{method} {path}",
                        ip=self.client_address[0] if self.client_address else None,
                        user_agent=self.headers.get("User-Agent") if hasattr(self, "headers") else None,
                        status_code=401,
                    )
                except Exception:
                    pass
                # P6.H: 根据 Accept-Language 头选 locale
                accept_lang = self.headers.get("Accept-Language") if hasattr(self, "headers") else None
                try:
                    from i18n import get_locale_from_header, set_locale
                    set_locale(get_locale_from_header(accept_lang))
                except Exception:
                    pass
                ae = APIError("UNAUTHORIZED")  # 不传 message,自动按 locale 翻译
                self.send_json(ae.to_dict(), status=ae.status)
                return
            self.current_user = identity

        # P5-E: 业务异常走 APIError,未知异常兜底 INTERNAL
        # P6.S.20: 端点延迟埋点(从 dispatch 开始到完成)
        import time
        _t0 = time.time()
        try:
            if method == "GET":
                route.handler(self)
            else:
                route.handler(self, data)
            # P6.S.20: 记端点延迟
            try:
                from observability.metrics import get_metrics_collector
                get_metrics_collector().record_endpoint_latency(
                    path, round((time.time() - _t0) * 1000, 2),
                )
            except Exception:
                pass
            # P5-I.B: 成功后审计(仅敏感端点)
            if _is_audit_endpoint(path, method):
                try:
                    from server.middleware.audit import record_audit
                    record_audit(
                        action=_audit_action_for(path),
                        user_id=(identity or {}).get("user_id"),
                        target=path,
                        ip=self.client_address[0] if self.client_address else None,
                        user_agent=self.headers.get("User-Agent") if hasattr(self, "headers") else None,
                        status_code=200,
                    )
                except Exception:
                    pass
        except APIError as ae:
            self.send_json(ae.to_dict(), status=ae.status)
            # 审计
            try:
                from server.middleware.audit import record_audit
                record_audit(
                    action=_audit_action_for(path),
                    user_id=(identity or {}).get("user_id"),
                    target=path,
                    ip=self.client_address[0] if self.client_address else None,
                    user_agent=self.headers.get("User-Agent") if hasattr(self, "headers") else None,
                    status_code=ae.status,
                    detail=str(ae.message)[:200] if hasattr(ae, "message") else None,
                )
            except Exception:
                pass
        except Exception as e:
            _log.exception(
                "Unhandled exception in handler %s %s",
                method, path,
                extra={"path": path, "method": method, "trace_id": getattr(self, "current_user", {}).get("trace_id", "-") if False else "-"},
            )
            ae = APIError("INTERNAL", "服务暂时不可用")
            self.send_json(ae.to_dict(), status=ae.status)
            # 异常审计
            try:
                from server.middleware.audit import record_audit
                record_audit(
                    action=_audit_action_for(path),
                    user_id=(identity or {}).get("user_id"),
                    target=path,
                    ip=self.client_address[0] if self.client_address else None,
                    user_agent=self.headers.get("User-Agent") if hasattr(self, "headers") else None,
                    status_code=500,
                    detail=f"unhandled: {type(e).__name__}",
                )
            except Exception:
                pass

    def do_GET(self):
        _inflight_begin()
        try:
            self._dispatch("GET")
        finally:
            _inflight_end()

    def do_POST(self):
        _inflight_begin()
        try:
            self._dispatch("POST")
        finally:
            _inflight_end()

    def log_message(self, format, *args):
        print(f"[HTTP] {args[0]}")


# ========== P5-J: 优雅退出 — inflight 计数器 ==========

import threading as _threading_mod
_INFLIGHT_COUNT = 0
_INFLIGHT_LOCK = _threading_mod.Lock()


def _inflight_begin() -> None:
    """请求开始(inflight + 1)"""
    global _INFLIGHT_COUNT
    with _INFLIGHT_LOCK:
        _INFLIGHT_COUNT += 1


def _inflight_end() -> None:
    """请求结束(inflight - 1)"""
    global _INFLIGHT_COUNT
    with _INFLIGHT_LOCK:
        _INFLIGHT_COUNT -= 1


def get_inflight_count() -> int:
    """当前在处理的请求数"""
    with _INFLIGHT_LOCK:
        return _INFLIGHT_COUNT


def wait_for_inflight_drain(timeout_s: float = 10.0, poll_interval_s: float = 0.1) -> bool:
    """
    P5-J: 等待 inflight 请求处理完毕(给 SIGTERM 优雅退出用)

    返回: True = 全部完成 / False = 超时仍有未完成
    """
    import time
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if get_inflight_count() == 0:
            return True
        time.sleep(poll_interval_s)
    return get_inflight_count() == 0


def create_handler():
    """工厂:返回带全局代理的 RequestHandler 子类"""
    class HandlerWithGlobals(RoutedRequestHandler):
        @property
        def agent(self):
            from main import get_agent
            return get_agent()

        @property
        def policy_updater(self):
            from main import get_policy_updater
            return get_policy_updater()

        @property
        def feedback_manager(self):
            from main import get_feedback_manager
            return get_feedback_manager()

        @property
        def account_manager(self):
            from main import get_account_manager
            return get_account_manager()

    return HandlerWithGlobals


def init_app():
    """初始化应用:注册所有路由 + 启动订阅 + 启动调度器

    启动骨架(P4-A):
    1. 注册反馈事件订阅(feedback → 画像回流)
    2. 注册 RAG 知识更新订阅(KNOWLEDGE_UPDATED → RAG 重建)
    3. 启动 APScheduler 后台调度
    4. 初始化所有 SQLite Schema(幂等)
    5. P6.S.15: 注册所有 tools + skills(之前从未注册,Registry 是空的)
    """
    from paths import ensure_data_dirs
    from db_schema import init_all_schemas
    ensure_data_dirs()
    init_all_schemas()

    registry = get_registry()
    register_all_routes(registry)

    # P6.S.15: 注册所有 tools + skills
    _register_all_tools_and_skills()

    # P6.S.16: 启动 MCP 客户端连接(异步后台线程)
    _start_mcp_registry()

    _register_event_subscribers()
    _start_scheduler_safe()

    return create_handler()


def _register_all_tools_and_skills() -> None:
    """P6.S.15: 把所有 Tool 和 Skill 注册到全局 Registry

    之前 builtin.py 里的 LowCarbonTravelSkill / WeatherTool / CarbonCalcTool /
    PublicTransitTool / PolicyQueryTool / ProfileUpdateTool 都定义了但
    从未注册到 ToolRegistry,导致 Registry 始终空。SkillExecutor 也找不到
    任何 skill。

    启动时一次注册,以后所有代码可通过 get_registry() / get_skill_executor() 访问。
    """
    try:
        from agent.tools import get_registry as get_tool_registry
        from agent.tools.extended import (
            TravelPlanningTool,
            KnowledgeRetrievalTool,
            CarbonFootprintTool,
            ReportExportTool,
        )
        from agent.tools.registry import ToolMetadata

        tool_reg = get_tool_registry()
        # 注册到全局 tool registry(失败不阻塞启动)
        for ToolCls, category, tags in [
            (TravelPlanningTool, "travel", ["navigation", "carbon", "weather"]),
            (KnowledgeRetrievalTool, "knowledge", ["rag", "search"]),
            (CarbonFootprintTool, "carbon", ["calculation", "footprint"]),
            (ReportExportTool, "report", ["export", "pdf"]),
        ]:
            try:
                tool_inst = ToolCls()
                meta = ToolMetadata(
                    name=tool_inst.name,
                    description=tool_inst.description,
                    category=category,
                    tags=tags,
                    version="1.0",
                )
                tool_reg.register(tool_inst, meta, overwrite=True)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(
                    "[P6.S.15] tool 注册失败 %s: %s", ToolCls.__name__, e,
                )

        # 注册 Skills
        from agent.skills import get_skill_executor
        from agent.skills.builtin import (
            LowCarbonTravelSkill,
            PolicyQuerySkill,
            ProfileUpdateSkill,
        )
        skill_exec = get_skill_executor()
        for SkillCls in [LowCarbonTravelSkill, PolicyQuerySkill, ProfileUpdateSkill]:
            try:
                skill_exec.register(SkillCls())
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(
                    "[P6.S.15] skill 注册失败 %s: %s", SkillCls.__name__, e,
                )

        import logging
        logging.getLogger(__name__).info(
            "[P6.S.15] tools/skills 注册完成: %d tools, %d skills",
            len(tool_reg.list_all()),
            len(skill_exec.list_all()),
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("[P6.S.15] tools/skills 注册失败(非致命): %s", e)


def _start_mcp_registry() -> None:
    """P6.S.16: 启动 MCP 客户端注册表(后台线程)

    读 config/mcp_servers.yaml,连接所有启用的 MCP server,
    把它们的 tool 注册到本地 ToolRegistry(零依赖,纯 stdlib)。

    失败不阻塞主流程(可降级为无 MCP 模式运行)。
    """
    try:
        from mcp import get_mcp_registry
        reg = get_mcp_registry()
        # 从 src/server/app.py 找 project_root(回退到 cwd 父目录)
        import os
        from pathlib import Path
        # app.py 在 src/server/app.py,project_root 是 src 的父目录
        here = Path(__file__).resolve()
        project_root = here.parent.parent.parent  # src/server -> src -> project_root
        # 尝试多个可能位置
        for candidate in [
            project_root / "config" / "mcp_servers.yaml",
            project_root / "mcp_servers.yaml",
            Path("config") / "mcp_servers.yaml",
            Path("mcp_servers.yaml"),
        ]:
            if candidate.exists():
                reg.connect_all_blocking(str(candidate))
                import logging
                logging.getLogger(__name__).info(
                    "[P6.S.16] MCP registry 启动: config=%s", candidate,
                )
                return
        # 没找到 config 文件,降级
        import logging
        logging.getLogger(__name__).info(
            "[P6.S.16] 未找到 config/mcp_servers.yaml, MCP 集成降级(无外部 server)",
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            "[P6.S.16] MCP registry 启动失败(非致命): %s", e,
        )


def _register_event_subscribers() -> None:
    """注册事件订阅者(失败不应阻塞启动)"""
    try:
        from feedback.profile_subscriber import register_feedback_subscribers
        register_feedback_subscribers()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("[App] 反馈订阅注册失败: %s", e)
    try:
        from rag.rag_subscriber import register_rag_subscribers
        register_rag_subscribers()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("[App] RAG 订阅注册失败: %s", e)


def _start_scheduler_safe() -> None:
    """启动调度器(失败不应阻塞启动)"""
    try:
        from scheduler import start_scheduler
        start_scheduler()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("[App] 调度器启动失败: %s", e)


def shutdown_app(timeout_s: float = 10.0) -> None:
    """
    P5-J: 关闭应用
    1) 等待 inflight 请求处理完毕(≤ timeout_s)
    2) 停止调度器(wait=False,不阻塞)
    3) 记录结构化日志

    参数:
        timeout_s: 等待 inflight 清零的最大秒数
    """
    import logging
    logger = logging.getLogger(__name__)

    # 1) 等待 inflight 排空
    remaining = get_inflight_count()
    if remaining > 0:
        logger.info(
            "[App] 收到关闭信号,等待 %d 个 inflight 请求完成 (timeout=%.1fs)",
            remaining, timeout_s,
        )
        drained = wait_for_inflight_drain(timeout_s=timeout_s)
        remaining_after = get_inflight_count()
        if drained:
            logger.info("[App] inflight 已全部完成")
        else:
            logger.warning(
                "[App] 等待超时,仍有 %d 个请求未完成,强制退出",
                remaining_after,
            )

    # 2) 停止调度器
    try:
        from scheduler import stop_scheduler
        stop_scheduler(wait=False)
        logger.info("[App] 调度器已停止")
    except Exception as e:
        logger.warning("[App] 调度器停止异常: %s", e)
