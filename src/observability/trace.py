"""
trace_id 生成与上下文传递 (P5-B)

设计:
- 全局 ContextVar,请求/调用链任何位置都能拿到当前 trace_id
- 默认值 "-" (单测/无 trace 上下文时不报错)
- new_trace_id() 用 uuid4 hex[:12] 短 ID(全局唯一且可读)
- with_trace() 上下文管理器(嵌套调用安全)
"""

from contextvars import ContextVar
from contextlib import contextmanager
import uuid
from typing import Optional


_trace_id_var: ContextVar[str] = ContextVar("trace_id", default="-")


def new_trace_id() -> str:
    """生成新 trace_id (12 位 hex)"""
    return uuid.uuid4().hex[:12]


def get_trace_id() -> str:
    """获取当前 trace_id (无上下文时返回 '-')"""
    return _trace_id_var.get()


def set_trace_id(trace_id: str) -> object:
    """显式设置 trace_id,返回 token (用于 reset)"""
    return _trace_id_var.set(trace_id)


def reset_trace_id(token: object) -> None:
    """重置 trace_id (与 set_trace_id 配对使用)"""
    _trace_id_var.reset(token)


@contextmanager
def with_trace(trace_id: Optional[str] = None):
    """
    上下文管理器: 自动生成/接管 trace_id

    用法:
        with with_trace() as tid:
            logger.info("...")
            nested_call()  # 内部 get_trace_id() 拿到 tid
    """
    tid = trace_id or new_trace_id()
    token = _trace_id_var.set(tid)
    try:
        yield tid
    finally:
        _trace_id_var.reset(token)


__all__ = [
    "new_trace_id",
    "get_trace_id",
    "set_trace_id",
    "reset_trace_id",
    "with_trace",
]
