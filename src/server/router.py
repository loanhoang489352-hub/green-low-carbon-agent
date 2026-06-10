"""
路由系统
将 main.py 中的 if/elif 链改为声明式路由注册
P5-D: 加 with_auth 装饰器 + 默认 auth_required=True
"""
from typing import Callable, List, Optional, Tuple
from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass
class Route:
    """单条路由"""
    method: str  # "GET" / "POST" / "PUT" / "DELETE"
    path: str  # 精确路径或前缀(以 = 开头表示精确匹配,以 ^ 开头表示前缀匹配)
    handler: Callable  # (handler, data) -> None,handler 应调用 self.send_json
    auth_required: bool = True  # 默认需要认证(P5-D)
    description: str = ""

    def matches(self, method: str, path: str) -> bool:
        """检查是否匹配"""
        if method.upper() != self.method.upper():
            return False
        if self.path.startswith("^"):
            return path.startswith(self.path[1:])
        return path == self.path


class RouterRegistry:
    """路由注册中心"""

    def __init__(self):
        self._routes: List[Route] = []

    def add(self, route: Route) -> None:
        self._routes.append(route)

    def add_route(
        self,
        method: str,
        path: str,
        handler: Callable,
        auth_required: bool = True,  # P5-D: 默认 True
        description: str = "",
    ) -> None:
        self.add(Route(method, path, handler, auth_required, description))

    def find(self, method: str, path: str) -> Optional[Route]:
        for route in self._routes:
            if route.matches(method, path):
                return route
        return None

    def list_routes(self) -> List[Route]:
        return list(self._routes)

    def clear(self) -> None:
        self._routes.clear()


# 全局注册表
_registry: Optional[RouterRegistry] = None


def get_registry() -> RouterRegistry:
    global _registry
    if _registry is None:
        _registry = RouterRegistry()
    return _registry


def reset_registry() -> None:
    global _registry
    _registry = None


# ========== P5-D: 鉴权中间件 ==========

def _send_unauthorized(handler, message: str = "Authentication required") -> None:
    """统一 401 响应"""
    try:
        handler.send_json({
            "ok": False,
            "error": {
                "code": "UNAUTHORIZED",
                "message": message,
                "status": 401,
            },
        }, status=401)
    except Exception:
        # 兜底,如果 handler 没有 send_json
        try:
            handler.send_error(401, message)
        except Exception:
            pass


def with_auth(handler: Callable, public: bool = False) -> Callable:
    """
    P5-D 鉴权装饰器: 把 handler 包装成"先验证 token 再执行"的版本

    用法:
        registry.add_route("POST", "/api/chat", with_auth(my_handler), description="...")
        registry.add_route("GET", "/api/health", my_handler, auth_required=False, ...)

    参数:
        handler: 原始 handler,签名 (handler_obj, data) -> None
        public: 标记 public(True 表示跳过鉴权,等价于 auth_required=False)

    行为:
        - 从 request headers 解析 Authorization Bearer / X-Session-Id
        - 也可从 POST body 读 session_id 字段(向后兼容)
        - 验证失败 → 401 + JSON 响应
        - 验证成功 → 把 user 信息塞到 handler.current_user 供下游使用
    """
    if public:
        # 直接返回原 handler,不增加行为
        return handler

    def wrapper(handler_obj, *args, **kwargs):
        # 提取 body
        data = args[0] if args else kwargs.get("data", {})
        if not isinstance(data, dict):
            data = {}

        # 鉴权
        try:
            from auth.account_manager import AccountManager
            # 复用 process-wide 单例
            if not hasattr(wrapper, "_account_mgr"):
                wrapper._account_mgr = AccountManager()
            mgr = wrapper._account_mgr

            identity = mgr.verify_token(getattr(handler_obj, "headers", {}), data)
        except Exception:
            identity = None

        if identity is None:
            _send_unauthorized(handler_obj, "Invalid or missing session token")
            return

        # 把身份写入 handler,供下游 handler 使用
        try:
            handler_obj.current_user = identity
        except Exception:
            pass

        # 调用原 handler
        return handler(handler_obj, *args, **kwargs)

    wrapper.__name__ = getattr(handler, "__name__", "wrapped_handler")
    wrapper.__wrapped__ = handler  # 便于测试/调试识别
    return wrapper


# 全局标志: 启动时设置 True 表示启用鉴权检查(可通过环境变量关闭)
_auth_enabled = True


def is_auth_enabled() -> bool:
    """是否启用鉴权(P5-D: 启动时 init_app 显式打开)"""
    return _auth_enabled


def set_auth_enabled(enabled: bool) -> None:
    """设置鉴权开关(供 init_app / 测试用)"""
    global _auth_enabled
    _auth_enabled = bool(enabled)
