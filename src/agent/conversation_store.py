"""
会话状态存储(单例)
P4-B.5:统一 GreenAgent 与 LangGraphAgent 的 active_conversations 状态

核心能力:
- 单例,所有 agent 共享同一份会话元数据
- 跨进程重启**无**持久化(由 LangGraph SqliteSaver 负责状态,本类只做元数据)
- TTL 清理过期会话(由 scheduler 周期调用)
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional


@dataclass
class ConversationContext:
    """对话上下文(per-conversation 元数据)"""

    user_id: str
    conversation_id: str
    turn_count: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_updated: str = field(default_factory=lambda: datetime.now().isoformat())


class ConversationStore:
    """会话存储单例

    线程安全(双检锁)。持有 user_id -> conversation_id 列表 与
    conversation_id -> ConversationContext 映射。
    """

    _instance: Optional["ConversationStore"] = None
    _lock = threading.Lock()

    CONVERSATION_TTL_DAYS = 7  # 7 天未活动视为过期

    def __new__(cls) -> "ConversationStore":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init()
        return cls._instance

    def _init(self) -> None:
        self._conversations: Dict[str, ConversationContext] = {}
        self._user_index: Dict[str, List[str]] = {}

    def get_or_create(self, user_id: str, conversation_id: Optional[str] = None) -> ConversationContext:
        """获取或创建会话

        Args:
            user_id: 用户 ID
            conversation_id: 指定 ID 时,优先复用;若不存在则用该 ID 创建
                          未指定时,返回该用户最近一个活动会话,再否则创建新会话
        """
        with self._lock:
            if conversation_id:
                if conversation_id in self._conversations:
                    ctx = self._conversations[conversation_id]
                    ctx.last_updated = datetime.now().isoformat()
                    ctx.turn_count += 1
                    return ctx
                # 指定 ID 但不存在 → 用该 ID 创建
                ctx = ConversationContext(
                    user_id=user_id,
                    conversation_id=conversation_id,
                )
                self._conversations[conversation_id] = ctx
                self._user_index.setdefault(user_id, []).append(conversation_id)
                return ctx

            # 复用用户最近一个活动会话
            if user_id in self._user_index and self._user_index[user_id]:
                last_conv_id = self._user_index[user_id][-1]
                if last_conv_id in self._conversations:
                    ctx = self._conversations[last_conv_id]
                    ctx.last_updated = datetime.now().isoformat()
                    ctx.turn_count += 1
                    return ctx

            # 创建新会话
            return self._new_conversation(user_id)

    def _new_conversation(self, user_id: str) -> ConversationContext:
        conv_id = str(uuid.uuid4())
        ctx = ConversationContext(user_id=user_id, conversation_id=conv_id)
        self._conversations[conv_id] = ctx
        self._user_index.setdefault(user_id, []).append(conv_id)
        return ctx

    def get(self, conversation_id: str) -> Optional[ConversationContext]:
        """获取会话(不创建)"""
        return self._conversations.get(conversation_id)

    def list_user_conversations(self, user_id: str) -> List[ConversationContext]:
        """列出用户所有活跃会话"""
        ids = self._user_index.get(user_id, [])
        return [self._conversations[i] for i in ids if i in self._conversations]

    def get_latest(self, user_id: str) -> Optional[ConversationContext]:
        """获取用户最近一个会话"""
        ids = self._user_index.get(user_id, [])
        if not ids:
            return None
        return self._conversations.get(ids[-1])

    def remove(self, conversation_id: str) -> bool:
        """移除会话"""
        with self._lock:
            ctx = self._conversations.pop(conversation_id, None)
            if ctx is None:
                return False
            ids = self._user_index.get(ctx.user_id, [])
            if conversation_id in ids:
                ids.remove(conversation_id)
            return True

    def cleanup_expired(self) -> int:
        """清理过期会话(由 scheduler 周期调用)

        Returns:
            删除的会话数
        """
        cutoff = datetime.now() - timedelta(days=self.CONVERSATION_TTL_DAYS)
        cutoff_iso = cutoff.isoformat()
        removed = 0
        with self._lock:
            expired_ids = [
                cid for cid, ctx in self._conversations.items()
                if ctx.last_updated < cutoff_iso
            ]
            for cid in expired_ids:
                ctx = self._conversations.pop(cid)
                ids = self._user_index.get(ctx.user_id, [])
                if cid in ids:
                    ids.remove(cid)
                removed += 1
        return removed

    def stats(self) -> Dict[str, int]:
        """统计信息"""
        return {
            "total_conversations": len(self._conversations),
            "total_users": len(self._user_index),
        }

    def reset(self) -> None:
        """重置(测试用)"""
        with self._lock:
            self._conversations.clear()
            self._user_index.clear()


def get_conversation_store() -> ConversationStore:
    """获取单例(兼容旧名)"""
    return ConversationStore()
