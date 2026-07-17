"""
HTTP 服务器包
后续将 main.py 拆分到此处:
  - app.py: 工厂创建 handler
  - routers/: chat / auth / profile / feedback / policy / knowledge
  - middleware/: auth / rate_limit / cors
  - errors.py: 统一错误响应
当前阶段:占位 + 简单文档,完整拆分在 P2.1。
"""

from typing import Callable, Dict


def register_router(routes: Dict[str, Callable]) -> Dict[str, Callable]:
    """辅助函数:校验路由表格式"""
    if not isinstance(routes, dict):
        raise TypeError("routes must be a dict")
    for path, handler in routes.items():
        if not path.startswith("/"):
            raise ValueError(f"route path must start with /: {path}")
        if not callable(handler):
            raise TypeError(f"route handler must be callable: {path}")
    return routes


__all__ = ["register_router"]
