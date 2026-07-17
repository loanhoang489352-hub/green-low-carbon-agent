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
        """P4-H + P6.S.19: 三段整合 短→工作→长

        1) 短期→工作:把当前会话的"焦点"写入 working memory(高 importance)
        2) 短期→长期:经策略筛选的高重要性消息直接晋升长期
        3) P6.S.19: 调 LLM 摘要中等重要性消息(importance 0.4-0.6),生成 1 条 summary
           存入长期(避免 LTM 只是 raw 切片,丢失上下文)
        """
        if not self.should_consolidate(conversation_id):
            return 0
        messages = self.short_term.get_conversation_history(conversation_id, limit=100)
        memories_to_save = self._extract_important_memories(messages)
        # 1) 短期 → 工作(P4-H: 把当前会话焦点写到 workspace)
        try:
            self._promote_to_working(user_id, conversation_id, messages)
        except Exception as e:
            import logging

            logging.getLogger(__name__).debug("[consolidation] working promote: %s", e)
        # 2) 短期 → 长期(原逻辑)
        if not memories_to_save:
            saved = 0
        else:
            self.long_term.consolidate_short_term(user_id, memories_to_save)
            saved = len(memories_to_save)
        # 3) P6.S.19: LLM 摘要中等重要性消息
        try:
            saved += self._summarize_medium_memories(user_id, conversation_id, messages)
        except Exception as e:
            import logging

            logging.getLogger(__name__).debug("[consolidation] summarize: %s", e)
        metadata = self._get_or_create_metadata(conversation_id)
        metadata["last_consolidated"] = datetime.now().isoformat()
        metadata["consolidated_count"] = metadata.get("consolidated_count", 0) + saved
        return saved

    def _summarize_medium_memories(
        self,
        user_id: str,
        conversation_id: str,
        messages: List[Dict[str, Any]],
    ) -> int:
        """P6.S.19: 调 LLM 摘要中等 importance 消息,生成 1 条 summary 存 LTM

        解决"长期记忆只是 raw 切片,丢失上下文"的 bug
        只摘要 importance 0.4-0.6 的中等消息(高 importance 已直接存,低 importance 丢弃)
        """
        # 过滤中等 importance 消息
        medium = []
        for m in messages:
            importance = m.get("importance", 0.5) if isinstance(m, dict) else 0.5
            content = m.get("content", "") if isinstance(m, dict) else str(m)
            if 0.4 <= importance <= 0.6 and content and len(content) > 20:
                medium.append(content)
        if len(medium) < 3:
            return 0  # 太少不摘要,避免浪费 LLM
        try:
            from llm import get_llm_client

            llm = get_llm_client()
        except Exception:
            return 0
        if not llm or not hasattr(llm, "chat"):
            return 0
        # 调 LLM 摘要
        joined = "\n".join(f"- {c[:200]}" for c in medium[:10])
        prompt = f"请用 100 字以内中文总结以下用户对话要点(客观、保留关键信息):\n{joined}\n\n摘要:"
        try:
            resp = llm.chat(
                [
                    {"role": "system", "content": "你是记忆摘要助手。"},
                    {"role": "user", "content": prompt},
                ]
            )
            summary = resp.content.strip()[:300] if resp and resp.content else ""
            if not summary or len(summary) < 10:
                return 0
            # 存 LTM
            self.long_term.add_memory(
                user_id=user_id,
                content=f"[摘要] {summary}",
                memory_type="summary",
                importance=0.7,  # 摘要比单条消息重要
                tags=["auto_summary", conversation_id[:8]],
            )
            return 1
        except Exception:
            return 0

    def _promote_to_working(
        self,
        user_id: str,
        conversation_id: str,
        messages: List[Dict[str, Any]],
    ) -> int:
        """P4-H: 把当前会话的"焦点 / 当前任务"提升到工作记忆

        策略:取最近 3 条 assistant 消息,把它们摘要为 current_focus。
        同时如果之前已有 current_focus,会被同名 key 覆盖(工作记忆本身的设计)。
        """
        try:
            from memory.working import get_working_memory

            wm = get_working_memory()
            recent_assistant = [
                m.get("content", "")[:200]
                for m in messages
                if m.get("role") == "assistant" and m.get("content")
            ][-3:]
            if not recent_assistant:
                return 0
            focus = " | ".join(recent_assistant)
            wm.set(
                user_id,
                key=f"conversation_focus:{conversation_id}",
                value=focus,
                agent_name="consolidator",
                importance=0.6,
            )
            # 全局 current_focus(覆盖式写入)
            wm.set(
                user_id,
                key="current_focus",
                value=focus[:200],
                agent_name="consolidator",
                importance=0.7,
            )
            return 1
        except Exception:
            return 0

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
                important.append(
                    {
                        "content": content[:200],
                        "type": (msg.get("metadata") or {}).get("intent", "general"),
                        "importance": importance,
                        "created_at": msg.get("timestamp") or datetime.now().isoformat(),
                    }
                )
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

    def set_message_count(self, conversation_id: str, count: int) -> None:
        """P5-G: 覆盖式设置 message_count(用于 scheduler 同步持久 STM 的当前值)。

        与 update_message_count(累加)不同,本方法直接覆盖,避免 STM 持久化后
        scheduler 每次都把累计的 message_count 重复相加导致漂移。
        """
        md = self._get_or_create_metadata(conversation_id)
        md["message_count"] = max(0, int(count))

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
