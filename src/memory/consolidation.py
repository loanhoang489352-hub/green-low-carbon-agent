"""
记忆整合模块(策略模式)
管理短期记忆到长期记忆的自动整合

策略接口:ConsolidationStrategy
- ThresholdStrategy(默认):轮次 ≥ 10 / 重要性 ≥ 0.6
- AdaptiveStrategy:活跃用户降低阈值(继承自原 AdaptiveConsolidator)
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Dict, Any, Optional, Protocol, runtime_checkable
from datetime import datetime

project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root / "src"))

from memory.short_term import ShortTermMemory, get_short_term_memory
from memory.long_term import LongTermMemory


# ---------------------------------------------------------------------------
# 策略接口
# ---------------------------------------------------------------------------

@runtime_checkable
class ConsolidationStrategy(Protocol):
    """整合策略接口

    实现类需提供:
    - should_consolidate(state) -> bool: 是否触发
    - importance_score(message) -> float: 消息重要性评分
    - name -> str: 策略名(用于日志/调试)
    """

    name: str

    def should_consolidate(self, state: Dict[str, Any]) -> bool: ...
    def importance_score(self, message: Dict[str, Any]) -> float: ...


# ---------------------------------------------------------------------------
# 具体策略
# ---------------------------------------------------------------------------

class ThresholdStrategy:
    """阈值策略:轮次 ≥ 10 / 空闲 ≥ 2h / 重要性 ≥ 0.6"""

    name = "threshold"
    MAX_CONVERSATION_TURNS = 10
    MAX_CONVERSATION_IDLE_HOURS = 2
    IMPORTANCE_THRESHOLD = 0.6

    BASE_IMPORTANCE = {
        "action_report": 0.7,
        "feedback": 0.8,
        "interest": 0.6,
        "knowledge_query": 0.5,
        "general": 0.3,
    }

    def should_consolidate(self, state: Dict[str, Any]) -> bool:
        turn_count = state.get("turn_count", 0)
        if turn_count >= self.MAX_CONVERSATION_TURNS:
            return True

        last_activity = state.get("last_activity")
        if last_activity:
            try:
                last = datetime.fromisoformat(last_activity)
                idle_hours = (datetime.now() - last).total_seconds() / 3600
                if idle_hours >= self.MAX_CONVERSATION_IDLE_HOURS:
                    return True
            except (ValueError, TypeError):
                pass

        msg_count = state.get("message_count", 0)
        if msg_count >= self.MAX_CONVERSATION_TURNS * 2:
            return True

        return False

    def importance_score(self, message: Dict[str, Any]) -> float:
        metadata = message.get("metadata", {}) or {}
        intent = metadata.get("intent", "general")
        content = message.get("content", "")
        base = self.BASE_IMPORTANCE.get(intent, 0.3)
        length_factor = min(len(content) / 200, 1.0) * 0.2
        return min(base + length_factor, 1.0)


class AdaptiveStrategy:
    """自适应策略:在 ThresholdStrategy 基础上对活跃用户降低阈值"""

    name = "adaptive"
    ACTIVE_USER_THRESHOLD = 20  # 每日 ≥ 20 条视为活跃

    def __init__(self) -> None:
        self._base = ThresholdStrategy()
        self._user_activity: Dict[str, Dict[str, Any]] = {}

    def should_consolidate(self, state: Dict[str, Any]) -> bool:
        # 基础检查
        if self._base.should_consolidate(state):
            return True

        # 活跃用户降低轮次阈值(除以 2)
        user_id = state.get("user_id")
        if user_id:
            activity = self._user_activity.setdefault(user_id, {"daily_messages": 0})
            if activity["daily_messages"] >= self.ACTIVE_USER_THRESHOLD:
                return state.get("turn_count", 0) >= self._base.MAX_CONVERSATION_TURNS // 2
        return False

    def importance_score(self, message: Dict[str, Any]) -> float:
        return self._base.importance_score(message)

    def record_user_activity(self, user_id: str) -> None:
        activity = self._user_activity.setdefault(user_id, {"daily_messages": 0})
        activity["daily_messages"] += 1
        activity["last_active"] = datetime.now().isoformat()


# ---------------------------------------------------------------------------
# 整合器
# ---------------------------------------------------------------------------

class MemoryConsolidator:
    """记忆整合器(委托给策略)"""

    IMPORTANCE_THRESHOLD = 0.6  # 兼容旧字段

    def __init__(
        self,
        short_term: Optional[ShortTermMemory] = None,
        long_term: Optional[LongTermMemory] = None,
        strategy: Optional[ConsolidationStrategy] = None,
    ) -> None:
        self.short_term = short_term or get_short_term_memory()
        self.long_term = long_term or LongTermMemory()
        self.strategy: ConsolidationStrategy = strategy or ThresholdStrategy()
        self._conversation_metadata: Dict[str, Dict[str, Any]] = {}

    def should_consolidate(self, conversation_id: str) -> bool:
        state = self._build_state(conversation_id)
        return self.strategy.should_consolidate(state)

    def consolidate(self, user_id: str, conversation_id: str) -> int:
        if not self.should_consolidate(conversation_id):
            return 0
        messages = self.short_term.get_conversation_history(conversation_id, limit=100)
        memories_to_save = self._extract_important_memories(messages)
        if not memories_to_save:
            return 0
        self.long_term.consolidate_short_term(user_id, memories_to_save)
        metadata = self._get_or_create_metadata(conversation_id)
        metadata["last_consolidated"] = datetime.now().isoformat()
        metadata["consolidated_count"] = metadata.get("consolidated_count", 0) + len(memories_to_save)
        return len(memories_to_save)

    def _extract_important_memories(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        important = []
        for msg in messages:
            if msg.get("role") != "user":
                continue
            content = msg.get("content", "")
            if not content or len(content) < 5:
                continue
            importance = self.strategy.importance_score(msg)
            if importance >= self.IMPORTANCE_THRESHOLD:
                important.append({
                    "content": content[:200],
                    "type": (msg.get("metadata") or {}).get("intent", "general"),
                    "importance": importance,
                    "created_at": msg.get("timestamp") or datetime.now().isoformat(),
                })
        return important

    def _build_state(self, conversation_id: str) -> Dict[str, Any]:
        md = self._get_or_create_metadata(conversation_id)
        return {
            "conversation_id": conversation_id,
            "turn_count": md.get("turn_count", 0),
            "message_count": md.get("message_count", 0),
            "last_activity": md.get("last_activity"),
        }

    def _get_or_create_metadata(self, conversation_id: str) -> Dict[str, Any]:
        if conversation_id not in self._conversation_metadata:
            now = datetime.now().isoformat()
            self._conversation_metadata[conversation_id] = {
                "turn_count": 0,
                "message_count": 0,
                "first_activity": now,
                "last_activity": now,
            }
        return self._conversation_metadata[conversation_id]

    def update_conversation_activity(self, conversation_id: str) -> None:
        md = self._get_or_create_metadata(conversation_id)
        md["last_activity"] = datetime.now().isoformat()
        md["turn_count"] = md.get("turn_count", 0) + 1

    def update_message_count(self, conversation_id: str, count: int = 1) -> None:
        md = self._get_or_create_metadata(conversation_id)
        md["message_count"] = md.get("message_count", 0) + count

    def get_consolidation_stats(self, conversation_id: str) -> Dict[str, Any]:
        md = self._get_or_create_metadata(conversation_id)
        return {
            "turn_count": md.get("turn_count", 0),
            "message_count": md.get("message_count", 0),
            "last_consolidated": md.get("last_consolidated"),
            "consolidated_count": md.get("consolidated_count", 0),
            "first_activity": md.get("first_activity"),
            "last_activity": md.get("last_activity"),
            "strategy": self.strategy.name,
        }

    def force_consolidate(self, user_id: str, conversation_id: str) -> int:
        messages = self.short_term.get_conversation_history(conversation_id, limit=100)
        memories_to_save = self._extract_important_memories(messages)
        if not memories_to_save:
            return 0
        self.long_term.consolidate_short_term(user_id, memories_to_save)
        return len(memories_to_save)


# ---------------------------------------------------------------------------
# 兼容性别名(旧 API)
# ---------------------------------------------------------------------------

class AdaptiveConsolidator(MemoryConsolidator):
    """旧名兼容,内部使用 AdaptiveStrategy"""

    ACTIVE_USER_THRESHOLD = 20
    SILENT_USER_DAYS = 7

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("strategy", AdaptiveStrategy())
        super().__init__(*args, **kwargs)
        self._user_activity_cache: Dict[str, Dict[str, Any]] = {}

    def should_consolidate(self, conversation_id: str, user_id: str = None) -> bool:
        state = self._build_state(conversation_id)
        if user_id:
            state["user_id"] = user_id
        return self.strategy.should_consolidate(state)

    def update_user_activity(self, user_id: str) -> None:
        if isinstance(self.strategy, AdaptiveStrategy):
            self.strategy.record_user_activity(user_id)


# ---------------------------------------------------------------------------
# 工厂
# ---------------------------------------------------------------------------

_global_consolidator: Optional[MemoryConsolidator] = None


def get_consolidator(strategy: str = "adaptive") -> MemoryConsolidator:
    """获取全局整合器

    Args:
        strategy: "threshold" | "adaptive"
    """
    global _global_consolidator
    if _global_consolidator is None:
        s: ConsolidationStrategy
        if strategy == "adaptive":
            s = AdaptiveStrategy()
        else:
            s = ThresholdStrategy()
        _global_consolidator = MemoryConsolidator(strategy=s)
    return _global_consolidator


def reset_consolidator() -> None:
    """重置(测试用)"""
    global _global_consolidator
    _global_consolidator = None
