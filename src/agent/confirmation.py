"""
Human-in-the-loop 确认流(P16)

出方案 / 花钱 / 不可逆操作前,暂停等用户确认,而不是自动提交。

设计:
  - ActionRisk: 动作风险分级(low / medium / high)
  - risk_for_action(category): 按动作类别映射风险
  - requires_confirmation(risk, delegation_level): 是否需确认
      · high   → 必确认
      · medium → delegation_level < 3 时确认(3 = 全权委托,自动提交)
      · low    → 不确认
  - PendingConfirmation + ConfirmationStore: 待确认动作的增查 + approve/reject

纯逻辑 + 线程安全内存存储,零外部依赖,可单测。持久化(TTL/DB)由调用方按需挂。
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional


class ActionRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


_HIGH_KEYWORDS = ("purchase", "payment", "irreversible", "delete", "reset", "transfer")
_MEDIUM_KEYWORDS = ("plan", "schedule", "commit", "activate", "register", "complete", "claim")


def risk_for_action(category: str) -> ActionRisk:
    """按动作类别(或描述)映射风险等级。默认 low。"""
    cat = (category or "").lower()
    if any(k in cat for k in _HIGH_KEYWORDS):
        return ActionRisk.HIGH
    if any(k in cat for k in _MEDIUM_KEYWORDS):
        return ActionRisk.MEDIUM
    return ActionRisk.LOW


def requires_confirmation(risk, delegation_level: int = 1) -> bool:
    """是否需用户确认。risk 可为 ActionRisk 或字符串。"""
    r = risk if isinstance(risk, ActionRisk) else ActionRisk(str(risk or "low"))
    if r == ActionRisk.HIGH:
        return True
    if r == ActionRisk.MEDIUM:
        return int(delegation_level or 0) < 3
    return False


@dataclass
class PendingConfirmation:
    id: str
    user_id: str
    action_id: str
    description: str
    risk: str = "medium"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    status: str = "pending"  # pending | approved | rejected


class ConfirmationStore:
    """待确认动作内存存储(线程安全),带 TTL 清理。"""

    TTL_HOURS = 24

    def __init__(self) -> None:
        self._items: Dict[str, PendingConfirmation] = {}
        self._lock = threading.Lock()

    def add(self, user_id: str, action_id: str, description: str, risk) -> PendingConfirmation:
        conf = PendingConfirmation(
            id=str(uuid.uuid4()),
            user_id=user_id,
            action_id=action_id,
            description=description,
            risk=risk.value if isinstance(risk, ActionRisk) else str(risk),
        )
        with self._lock:
            self._items[conf.id] = conf
        return conf

    def get(self, conf_id: str) -> Optional[PendingConfirmation]:
        with self._lock:
            return self._items.get(conf_id)

    def _set_status(self, conf_id: str, status: str) -> bool:
        with self._lock:
            conf = self._items.get(conf_id)
            if conf is None or conf.status != "pending":
                return False
            conf.status = status
            return True

    def approve(self, conf_id: str) -> bool:
        return self._set_status(conf_id, "approved")

    def reject(self, conf_id: str) -> bool:
        return self._set_status(conf_id, "rejected")

    def list_pending(self, user_id: str) -> List[PendingConfirmation]:
        with self._lock:
            return [c for c in self._items.values()
                    if c.user_id == user_id and c.status == "pending"]

    def cleanup_expired(self) -> int:
        cutoff = datetime.now() - timedelta(hours=self.TTL_HOURS)
        cutoff_iso = cutoff.isoformat()
        removed = 0
        with self._lock:
            expired = [cid for cid, c in self._items.items()
                       if c.status == "pending" and c.created_at < cutoff_iso]
            for cid in expired:
                self._items.pop(cid)
                removed += 1
        return removed

    def reset(self) -> None:
        with self._lock:
            self._items.clear()


_store: Optional[ConfirmationStore] = None
_store_lock = threading.Lock()


def get_confirmation_store() -> ConfirmationStore:
    """全局单例"""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = ConfirmationStore()
    return _store


__all__ = [
    "ActionRisk",
    "risk_for_action",
    "requires_confirmation",
    "PendingConfirmation",
    "ConfirmationStore",
    "get_confirmation_store",
]
