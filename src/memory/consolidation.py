"""
记忆整合模块
管理短期记忆到长期记忆的自动整合
"""

import sys
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root / 'src'))

from memory.short_term import ShortTermMemory, get_short_term_memory
from memory.long_term import LongTermMemory


class MemoryConsolidator:
    """
    记忆整合器

    负责将短期记忆中重要的信息整合到长期记忆：
    - 触发条件检测
    - 重要信息提取
    - 整合执行
    """

    # 整合触发阈值
    MAX_CONVERSATION_TURNS = 10      # 对话轮次达到此值触发整合
    MAX_CONVERSATION_IDLE_HOURS = 2  # 空闲达到此小时数触发整合
    IMPORTANCE_THRESHOLD = 0.6        # 只整合重要性 >= 此值的信息

    # 记忆类型对应的重要性基础值
    MEMORY_IMPORTANCE = {
        "action_report": 0.7,   # 行动报告通常是重要的
        "feedback": 0.8,        # 反馈非常重要
        "interest": 0.6,        # 兴趣信息中等重要
        "knowledge_query": 0.5, # 知识查询一般重要
        "general": 0.3          # 一般信息较低
    }

    def __init__(self, short_term: ShortTermMemory = None, long_term: LongTermMemory = None):
        """
        初始化记忆整合器

        Args:
            short_term: 短期记忆实例
            long_term: 长期记忆实例
        """
        self.short_term = short_term or get_short_term_memory()
        self.long_term = long_term or LongTermMemory()

        # 追踪每个对话的元数据
        self._conversation_metadata: Dict[str, Dict] = {}

    def should_consolidate(self, conversation_id: str) -> bool:
        """
        判断是否应该触发整合

        Args:
            conversation_id: 对话ID

        Returns:
            是否应该整合
        """
        metadata = self._get_or_create_metadata(conversation_id)

        # 检查对话轮次
        turn_count = metadata.get("turn_count", 0)
        if turn_count >= self.MAX_CONVERSATION_TURNS:
            return True

        # 检查空闲时间
        last_activity = metadata.get("last_activity")
        if last_activity:
            try:
                last = datetime.fromisoformat(last_activity)
                idle_hours = (datetime.now() - last).total_seconds() / 3600
                if idle_hours >= self.MAX_CONVERSATION_IDLE_HOURS:
                    return True
            except (ValueError, TypeError):
                pass

        # 检查是否达到消息数量阈值
        msg_count = metadata.get("message_count", 0)
        if msg_count >= self.MAX_CONVERSATION_TURNS * 2:
            return True

        return False

    def consolidate(self, user_id: str, conversation_id: str) -> int:
        """
        执行记忆整合

        将短期记忆中的重要信息转入长期记忆

        Args:
            user_id: 用户ID
            conversation_id: 对话ID

        Returns:
            整合的记忆数量
        """
        if not self.should_consolidate(conversation_id):
            return 0

        # 获取对话历史
        messages = self.short_term.get_conversation_history(conversation_id, limit=100)

        # 提取重要记忆
        memories_to_save = self._extract_important_memories(messages)

        if not memories_to_save:
            return 0

        # 使用长期记忆的整合方法
        self.long_term.consolidate_short_term(user_id, memories_to_save)

        # 更新元数据
        metadata = self._get_or_create_metadata(conversation_id)
        metadata["last_consolidated"] = datetime.now().isoformat()
        metadata["consolidated_count"] = metadata.get("consolidated_count", 0) + len(memories_to_save)

        return len(memories_to_save)

    def _extract_important_memories(self, messages: List[Dict]) -> List[Dict]:
        """
        从对话历史中提取重要信息

        Args:
            messages: 短期记忆中的消息列表

        Returns:
            重要的记忆列表
        """
        important_memories = []

        for msg in messages:
            # 只处理用户消息
            if msg.get("role") != "user":
                continue

            content = msg.get("content", "")
            if not content or len(content) < 5:
                continue

            metadata = msg.get("metadata", {}) or {}
            intent = metadata.get("intent", "general")
            timestamp = msg.get("timestamp", "")

            # 计算重要性
            base_importance = self.MEMORY_IMPORTANCE.get(intent, 0.3)

            # 长度加成：较长的消息可能更重要
            length_factor = min(len(content) / 200, 1.0) * 0.2

            # 综合重要性
            importance = min(base_importance + length_factor, 1.0)

            # 只保留高于阈值的重要记忆
            if importance >= self.IMPORTANCE_THRESHOLD:
                # 截断过长的内容
                truncated_content = content[:200] if len(content) > 200 else content

                important_memories.append({
                    "content": truncated_content,
                    "type": intent,
                    "importance": importance,
                    "created_at": timestamp or datetime.now().isoformat()
                })

        return important_memories

    def _get_or_create_metadata(self, conversation_id: str) -> Dict:
        """获取或创建对话元数据"""
        if conversation_id not in self._conversation_metadata:
            self._conversation_metadata[conversation_id] = {
                "turn_count": 0,
                "message_count": 0,
                "first_activity": datetime.now().isoformat(),
                "last_activity": datetime.now().isoformat(),
            }
        return self._conversation_metadata[conversation_id]

    def update_conversation_activity(self, conversation_id: str):
        """更新对话活动（每次有新消息时调用）"""
        metadata = self._get_or_create_metadata(conversation_id)
        metadata["last_activity"] = datetime.now().isoformat()
        metadata["turn_count"] = metadata.get("turn_count", 0) + 1

    def update_message_count(self, conversation_id: str, count: int = 1):
        """更新消息计数"""
        metadata = self._get_or_create_metadata(conversation_id)
        metadata["message_count"] = metadata.get("message_count", 0) + count

    def get_consolidation_stats(self, conversation_id: str) -> Dict[str, Any]:
        """获取整合统计信息"""
        metadata = self._get_or_create_metadata(conversation_id)
        return {
            "turn_count": metadata.get("turn_count", 0),
            "message_count": metadata.get("message_count", 0),
            "last_consolidated": metadata.get("last_consolidated"),
            "consolidated_count": metadata.get("consolidated_count", 0),
            "first_activity": metadata.get("first_activity"),
            "last_activity": metadata.get("last_activity"),
        }

    def force_consolidate(self, user_id: str, conversation_id: str) -> int:
        """
        强制整合（不检查阈值）

        用于测试或手动触发
        """
        messages = self.short_term.get_conversation_history(conversation_id, limit=100)
        memories_to_save = self._extract_important_memories(messages)

        if not memories_to_save:
            return 0

        self.long_term.consolidate_short_term(user_id, memories_to_save)
        return len(memories_to_save)


class AdaptiveConsolidator(MemoryConsolidator):
    """
    自适应记忆整合器

    根据用户活跃度和记忆负载动态调整整合策略
    """

    # 活跃用户阈值（每天消息数）
    ACTIVE_USER_THRESHOLD = 20

    # 沉默用户阈值（超过此天数无活动）
    SILENT_USER_DAYS = 7

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._user_activity_cache: Dict[str, Dict] = {}

    def should_consolidate(self, conversation_id: str, user_id: str = None) -> bool:
        """增强版整合判断"""
        # 基础检查
        if super().should_consolidate(conversation_id):
            return True

        # 活跃用户：更频繁整合
        if user_id:
            activity = self._get_user_activity(user_id)
            daily_messages = activity.get("daily_messages", 0)

            if daily_messages >= self.ACTIVE_USER_THRESHOLD:
                # 活跃用户降低阈值
                metadata = self._get_or_create_metadata(conversation_id)
                turn_count = metadata.get("turn_count", 0)
                return turn_count >= self.MAX_CONVERSATION_TURNS // 2

        return False

    def _get_user_activity(self, user_id: str) -> Dict:
        """获取用户活跃度信息"""
        if user_id not in self._user_activity_cache:
            self._user_activity_cache[user_id] = {
                "daily_messages": 0,
                "last_active": None,
                "total_sessions": 0
            }
        return self._user_activity_cache[user_id]

    def update_user_activity(self, user_id: str):
        """更新用户活跃度"""
        activity = self._get_user_activity(user_id)
        activity["daily_messages"] = activity.get("daily_messages", 0) + 1
        activity["last_active"] = datetime.now().isoformat()


# 全局整合器实例
_global_consolidator: Optional[MemoryConsolidator] = None


def get_consolidator() -> MemoryConsolidator:
    """获取全局记忆整合器（延迟初始化）"""
    global _global_consolidator
    if _global_consolidator is None:
        _global_consolidator = MemoryConsolidator()
    return _global_consolidator