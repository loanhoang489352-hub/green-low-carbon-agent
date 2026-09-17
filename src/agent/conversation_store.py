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

# 统一时间格式:与 utils.helpers.get_current_datetime()("%Y-%m-%d %H:%M:%S") 一致。
# cleanup_expired 做字符串比较,格式不一致(isoformat 的 'T' vs 空格)会导致
# 同一天内 core.py 写入的会话被误判更早而提前过期。
_DATETIME_FMT = "%Y-%m-%d %H:%M:%S"


def _now_str() -> str:
    return datetime.now().strftime(_DATETIME_FMT)


@dataclass
class ConversationContext:
    """对话上下文(per-conversation 元数据)"""

    user_id: str
    conversation_id: str
    last_domain: str = ""
    turn_count: int = 0
    created_at: str = field(default_factory=_now_str)
    last_updated: str = field(default_factory=_now_str)


class ConversationOwnershipError(PermissionError):
    """会话所有权校验失败(水平越权:用户试图复用/访问他人的 conversation_id)"""


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

    def get_or_create(
        self, user_id: str, conversation_id: Optional[str] = None
    ) -> ConversationContext:
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
                    # 水平越权防护:conversation_id 属于他人时,禁止复用(不返回、不覆盖)
                    if ctx.user_id != user_id:
                        raise ConversationOwnershipError(
                            f"conversation {conversation_id} 属于 {ctx.user_id},"
                            f"当前用户 {user_id} 无权复用"
                        )
                    # 复用已有会话 → 计一轮
                    ctx.turn_count += 1
                    ctx.last_updated = _now_str()
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
                    # 复用最近会话 → 计一轮
                    ctx = self._conversations[last_conv_id]
                    ctx.turn_count += 1
                    ctx.last_updated = _now_str()
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

    def assert_owner(self, conversation_id: str, user_id: str) -> None:
        """校验 conversation_id 归属 user_id(水平越权防护)

        会话在内存中且属于他人 → 抛 ConversationOwnershipError。
        会话不在内存(如重启后仅存在于 SQLite)→ 此处不拦截,由持久层/业务层兜底。
        """
        ctx = self._conversations.get(conversation_id)
        if ctx is not None and ctx.user_id != user_id:
            raise ConversationOwnershipError(
                f"conversation {conversation_id} 属于 {ctx.user_id},"
                f"当前用户 {user_id} 无权访问"
            )

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
        cutoff_str = cutoff.strftime(_DATETIME_FMT)
        removed = 0
        with self._lock:
            expired_ids = [
                cid for cid, ctx in self._conversations.items() if ctx.last_updated < cutoff_str
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
