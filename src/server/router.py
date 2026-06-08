"""
路由系统
将 main.py 中的 if/elif 链改为声明式路由注册
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
    auth_required: bool = True  # 是否需要认证
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
        auth_required: bool = True,
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
