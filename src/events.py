"""
轻量级事件总线
用于解耦模块通信(如知识库更新 → RAG 重载、反馈 → 画像回流)
"""
import logging
import threading
from collections import defaultdict
from enum import Enum
from typing import Any, Callable, Dict, List

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """事件类型枚举"""
    KNOWLEDGE_UPDATED = "knowledge.updated"
    KB_DOC_ADDED = "knowledge.doc_added"
    KB_DOC_REMOVED = "knowledge.doc_removed"
    FEEDBACK_RECEIVED = "feedback.received"
    USER_PROFILE_UPDATED = "user.profile_updated"
    POLICY_UPDATED = "policy.updated"


class EventBus:
    """同步事件总线(线程安全)"""

    def __init__(self):
        self._subscribers: Dict[EventType, List[Callable]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(self, event_type: EventType, callback: Callable) -> None:
        """订阅事件"""
        with self._lock:
            self._subscribers[event_type].append(callback)
        logger.debug("订阅事件: %s -> %s", event_type, callback.__name__)

    def unsubscribe(self, event_type: EventType, callback: Callable) -> None:
        with self._lock:
            if callback in self._subscribers[event_type]:
                self._subscribers[event_type].remove(callback)

    def publish(self, event_type: EventType, **payload: Any) -> None:
        """发布事件(同步调用所有订阅者,异常被吞并记录)"""
        with self._lock:
            subs = list(self._subscribers[event_type])
        for cb in subs:
            try:
                cb(event_type=event_type, **payload)
            except Exception as e:
                logger.exception("事件订阅者 %s 执行失败: %s", cb.__name__, e)

    def clear(self) -> None:
        """清空所有订阅(测试用)"""
        with self._lock:
            self._subscribers.clear()


# 全局单例
_bus: EventBus = EventBus()


def get_event_bus() -> EventBus:
    return _bus


def reset_event_bus() -> None:
    """重置(测试用)"""
    global _bus
    _bus = EventBus()
