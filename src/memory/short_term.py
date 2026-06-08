"""
短期记忆模块
管理会话级别的短期记忆和对话历史
"""

import json
from typing import List, Dict, Any, Optional
from collections import defaultdict
from datetime import datetime, timedelta


class ShortTermMemory:
    """
    短期记忆管理器
    
    特点:
    - 基于会话管理
    - 有时间过期机制
    - 存储对话历史
    - 支持工作记忆（最近几轮对话）
    """
    
    # 配置
    MAX_CONVERSATION_LENGTH = 50  # 单个对话最大消息数
    CONVERSATION_TTL_DAYS = 7     # 对话保留天数
    WORKING_MEMORY_SIZE = 5        # 工作记忆大小（最近N轮）
    
    def __init__(self):
        # 存储结构: {conversation_id: [messages]}
        self.conversations: Dict[str, List[Dict]] = defaultdict(list)
        
        # 元数据: {conversation_id: metadata}
        self.metadata: Dict[str, Dict] = {}
        
        # 工作记忆缓存: {conversation_id: [recent_messages]}
        self.working_memory: Dict[str, List[Dict]] = {}
        
        print("🧠 短期记忆系统初始化完成")
    
    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict] = None
    ) -> bool:
        """
        添加消息到对话
        
        Args:
            conversation_id: 对话ID
            role: 角色 (user/assistant/system)
            content: 消息内容
            metadata: 附加元数据
        
        Returns:
            是否成功
        """
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {}
        }
        
        # 添加到对话历史
        self.conversations[conversation_id].append(message)
        
        # 限制对话长度
        if len(self.conversations[conversation_id]) > self.MAX_CONVERSATION_LENGTH:
            self.conversations[conversation_id] = self.conversations[conversation_id][-self.MAX_CONVERSATION_LENGTH:]
        
        # 更新工作记忆
        self._update_working_memory(conversation_id)
        
        # 更新元数据
        if conversation_id not in self.metadata:
            self.metadata[conversation_id] = {
                "created_at": datetime.now().isoformat(),
                "message_count": 0,
                "user_id": None
            }
        
        self.metadata[conversation_id]["message_count"] += 1
        self.metadata[conversation_id]["last_activity"] = datetime.now().isoformat()
        
        return True
    
    def _update_working_memory(self, conversation_id: str):
        """更新工作记忆"""
        messages = self.conversations.get(conversation_id, [])
        
        # 保留最近的消息
        self.working_memory[conversation_id] = messages[-self.WORKING_MEMORY_SIZE * 2:]
    
    def get_conversation_history(
        self,
        conversation_id: str,
        limit: Optional[int] = None
    ) -> List[Dict]:
        """
        获取对话历史
        
        Args:
            conversation_id: 对话ID
            limit: 限制返回的消息数
        
        Returns:
            消息列表
        """
        messages = self.conversations.get(conversation_id, [])
        
        if limit:
            return messages[-limit:]
        
        return messages
    
    def get_working_memory(self, conversation_id: str) -> List[Dict]:
        """
        获取工作记忆（最近几轮对话的上下文）
        
        Args:
            conversation_id: 对话ID
        
        Returns:
            工作记忆消息列表
        """
        return self.working_memory.get(conversation_id, [])
    
    def get_context_for_llm(self, conversation_id: str) -> str:
        """
        为LLM生成上下文字符串
        
        Args:
            conversation_id: 对话ID
        
        Returns:
            格式化的上下文字符串
        """
        working = self.get_working_memory(conversation_id)
        
        if not working:
            return ""
        
        context_parts = []
        for msg in working:
            role = "用户" if msg["role"] == "user" else "助手"
            context_parts.append(f"{role}: {msg['content']}")
        
        return "\n".join(context_parts)
    
    def search_conversations(
        self,
        user_id: str = None,
        keyword: str = None,
        limit: int = 10
    ) -> List[Dict]:
        """
        搜索对话
        
        Args:
            user_id: 用户ID
            keyword: 关键词
            limit: 返回数量
        
        Returns:
            匹配的对话列表
        """
        results = []
        
        for conv_id, metadata in self.metadata.items():
            if user_id and metadata.get("user_id") != user_id:
                continue
            
            if keyword:
                messages = self.conversations.get(conv_id, [])
                has_keyword = any(
                    keyword in msg.get("content", "")
                    for msg in messages
                )
                if not has_keyword:
                    continue
            
            results.append({
                "conversation_id": conv_id,
                "metadata": metadata,
                "preview": self.conversations.get(conv_id, [{}])[-1].get("content", "")[:100]
            })
        
        # 按最后活动时间排序
        results.sort(
            key=lambda x: x["metadata"].get("last_activity", ""),
            reverse=True
        )
        
        return results[:limit]
    
    def delete_conversation(self, conversation_id: str) -> bool:
        """删除对话"""
        if conversation_id in self.conversations:
            del self.conversations[conversation_id]
        
        if conversation_id in self.metadata:
            del self.metadata[conversation_id]
        
        if conversation_id in self.working_memory:
            del self.working_memory[conversation_id]
        
        return True
    
    def cleanup_expired(self) -> int:
        """
        清理过期的对话
        
        Returns:
            清理的对话数量
        """
        now = datetime.now()
        expired_threshold = now - timedelta(days=self.CONVERSATION_TTL_DAYS)
        expired_ids = []
        
        for conv_id, metadata in self.metadata.items():
            last_activity = datetime.fromisoformat(
                metadata.get("last_activity", now.isoformat())
            )
            if last_activity < expired_threshold:
                expired_ids.append(conv_id)
        
        for conv_id in expired_ids:
            self.delete_conversation(conv_id)
        
        return len(expired_ids)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        total_messages = sum(
            len(msgs) for msgs in self.conversations.values()
        )
        
        return {
            "total_conversations": len(self.conversations),
            "total_messages": total_messages,
            "avg_messages_per_conversation": (
                total_messages / len(self.conversations)
                if self.conversations else 0
            ),
            "active_conversations": sum(
                1 for m in self.metadata.values()
                if (datetime.now() - datetime.fromisoformat(
                    m.get("last_activity", datetime.now().isoformat())
                )).days < 1
            )
        }
    
    def extract_preferences(self, conversation_id: str) -> Dict[str, Any]:
        """
        从对话中提取偏好信息
        
        Args:
            conversation_id: 对话ID
        
        Returns:
            偏好字典
        """
        messages = self.conversations.get(conversation_id, [])
        
        preferences = {
            "interests": [],
            "questions": [],
            "actions": [],
            "feedback": []
        }
        
        for msg in messages:
            content = msg.get("content", "")
            metadata = msg.get("metadata", {})
            intent = metadata.get("intent", "")
            
            if msg["role"] == "user":
                if intent == "knowledge_query":
                    preferences["questions"].append(content)
                elif intent == "action_report":
                    preferences["actions"].append(content)
                elif intent in ["feedback", "suggestion_accept", "suggestion_reject"]:
                    preferences["feedback"].append(content)

        return preferences


# ============================================================
# 单例工厂
# ============================================================
import threading

_short_term_instance: Optional["ShortTermMemory"] = None
_short_term_lock = threading.Lock()


def get_short_term_memory() -> "ShortTermMemory":
    """获取共享的 ShortTermMemory 单例。

    GreenAgent / LangGraphAgent / MemoryConsolidator 必须共享同一个实例,
    否则会出现写入与读取不在同一对象上的数据竞争,导致记忆丢失。
    """
    global _short_term_instance
    if _short_term_instance is None:
        with _short_term_lock:
            if _short_term_instance is None:
                _short_term_instance = ShortTermMemory()
    return _short_term_instance


def reset_short_term_memory() -> None:
    """重置单例(仅供测试使用)。"""
    global _short_term_instance
    with _short_term_lock:
        _short_term_instance = None
