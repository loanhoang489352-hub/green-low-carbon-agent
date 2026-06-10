"""
短期记忆模块(P5-G: SQLite 持久化)
管理会话级别的短期记忆和对话历史

特性:
- 进程重启后会话不丢(SQLite 持久化)
- 内存缓存 + 写穿,热路径仍是 O(1) dict 读
- 公共 API 与重构前完全兼容(测试 / scheduler 都不需改)
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta


# P5-F: 模块级 logger
try:
    from observability import get_logger
    _logger = get_logger("memory.short_term")
except Exception:
    import logging
    _logger = logging.getLogger("memory.short_term")


class ShortTermMemory:
    """
    短期记忆管理器(持久化版本)

    P5-G 之前:全内存 defaultdict,进程重启 = 数据丢失
    P5-G 之后:SQLite 持久化 + 内存缓存,公共 API 不变
    """

    # 配置
    MAX_CONVERSATION_LENGTH = 50  # 单个对话最大消息数
    CONVERSATION_TTL_DAYS = 7     # 对话保留天数
    WORKING_MEMORY_SIZE = 5        # 工作记忆大小(最近 N 轮)

    def __init__(self, db_path: Optional[str] = None):
        # 决定 DB 路径(可选注入用于测试)
        if db_path is None:
            from paths import SHORT_TERM_DB
            db_path = str(SHORT_TERM_DB)
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # 内存缓存(加速热路径读;scheduler/cascaded_recall 等读频繁)
        # 注意:内部用 _cache,公共方法仍以 self.conversations 形式暴露(向后兼容)
        # 但为了一致性,公共 API 也读 _cache
        self._cache: Dict[str, List[Dict]] = {}
        self.metadata: Dict[str, Dict] = {}        # 公共属性,scheduler 读
        self.working_memory: Dict[str, List[Dict]] = {}

        self._init_db()
        self._load_from_db()
        _logger.info("[STM] 持久化初始化完成,db=%s,加载 %d 个会话",
                     self.db_path, len(self._cache))

    # ============================================================
    # SQLite 持久化层
    # ============================================================

    def _init_db(self) -> None:
        """初始化 DB 表(WAL 模式 + busy_timeout)"""
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                conversation_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS conversation_meta (
                conversation_id TEXT PRIMARY KEY,
                user_id TEXT,
                message_count INTEGER DEFAULT 0,
                last_activity TEXT,
                created_at TEXT
            );
        """)
        conn.commit()
        conn.close()

    def _load_from_db(self) -> None:
        """从 DB 加载到内存缓存(只在 __init__ 调一次)"""
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            for row in conn.execute("SELECT conversation_id, payload FROM conversations"):
                try:
                    self._cache[row["conversation_id"]] = json.loads(row["payload"])
                except (json.JSONDecodeError, TypeError):
                    continue
            for row in conn.execute(
                "SELECT conversation_id, user_id, message_count, last_activity, created_at "
                "FROM conversation_meta"
            ):
                self.metadata[row["conversation_id"]] = {
                    "user_id": row["user_id"],
                    "message_count": row["message_count"] or 0,
                    "last_activity": row["last_activity"],
                    "created_at": row["created_at"],
                }
            conn.close()
        except Exception as e:
            _logger.warning("[STM] 从 DB 加载失败,当作空 STM 处理: %s", e)

    def _persist_messages(self, cid: str) -> None:
        """写穿:把 _cache[cid] 序列化到 conversations 表"""
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute(
                "INSERT OR REPLACE INTO conversations (conversation_id, payload, updated_at) "
                "VALUES (?, ?, ?)",
                (cid, json.dumps(self._cache.get(cid, []), ensure_ascii=False),
                 datetime.now().isoformat()),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            _logger.warning("[STM] 持久化 messages 失败 cid=%s: %s", cid, e)

    def _persist_meta(self, cid: str) -> None:
        """写穿:把 metadata[cid] 写入 conversation_meta 表"""
        md = self.metadata.get(cid, {})
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute(
                "INSERT OR REPLACE INTO conversation_meta "
                "(conversation_id, user_id, message_count, last_activity, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (cid, md.get("user_id"), md.get("message_count", 0),
                 md.get("last_activity"), md.get("created_at")),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            _logger.warning("[STM] 持久化 meta 失败 cid=%s: %s", cid, e)

    def _persist_both(self, cid: str) -> None:
        """一次性写穿 messages + meta(顺序保证)"""
        self._persist_messages(cid)
        self._persist_meta(cid)

    def _delete_from_db(self, cid: str) -> None:
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("DELETE FROM conversations WHERE conversation_id = ?", (cid,))
            conn.execute("DELETE FROM conversation_meta WHERE conversation_id = ?", (cid,))
            conn.commit()
            conn.close()
        except Exception as e:
            _logger.warning("[STM] 删 DB 失败 cid=%s: %s", cid, e)

    # ============================================================
    # 公共 API(签名与 P5-G 之前完全一致)
    # ============================================================

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict] = None,
    ) -> bool:
        """添加消息到对话"""
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {},
        }

        # 1) 追加到内存缓存
        self._cache.setdefault(conversation_id, []).append(message)

        # 2) 限制对话长度
        if len(self._cache[conversation_id]) > self.MAX_CONVERSATION_LENGTH:
            self._cache[conversation_id] = self._cache[conversation_id][
                -self.MAX_CONVERSATION_LENGTH:
            ]

        # 3) 更新工作记忆(派生)
        self._update_working_memory(conversation_id)

        # 4) 更新元数据
        if conversation_id not in self.metadata:
            self.metadata[conversation_id] = {
                "created_at": datetime.now().isoformat(),
                "message_count": 0,
                "user_id": None,
            }

        self.metadata[conversation_id]["message_count"] += 1
        self.metadata[conversation_id]["last_activity"] = datetime.now().isoformat()

        # 5) 写穿 SQLite
        self._persist_both(conversation_id)

        return True

    def _update_working_memory(self, conversation_id: str) -> None:
        """更新工作记忆(派生自 _cache)"""
        messages = self._cache.get(conversation_id, [])
        # 保留最近的消息
        self.working_memory[conversation_id] = messages[-self.WORKING_MEMORY_SIZE * 2:]

    def get_conversation_history(
        self,
        conversation_id: str,
        limit: Optional[int] = None,
    ) -> List[Dict]:
        """获取对话历史"""
        messages = list(self._cache.get(conversation_id, []))

        if limit:
            return messages[-limit:]

        return messages

    def get_working_memory(self, conversation_id: str) -> List[Dict]:
        """获取工作记忆(最近几轮对话的上下文)"""
        return self.working_memory.get(conversation_id, [])

    def get_context_for_llm(self, conversation_id: str) -> str:
        """为 LLM 生成上下文字符串"""
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
        limit: int = 10,
    ) -> List[Dict]:
        """搜索对话"""
        results = []

        for conv_id, metadata in self.metadata.items():
            if user_id and metadata.get("user_id") != user_id:
                continue

            if keyword:
                messages = self._cache.get(conv_id, [])
                has_keyword = any(
                    keyword in msg.get("content", "")
                    for msg in messages
                )
                if not has_keyword:
                    continue

            results.append({
                "conversation_id": conv_id,
                "metadata": metadata,
                "preview": self._cache.get(conv_id, [{}])[-1].get("content", "")[:100],
            })

        # 按最后活动时间排序
        results.sort(
            key=lambda x: x["metadata"].get("last_activity", ""),
            reverse=True,
        )

        return results[:limit]

    def delete_conversation(self, conversation_id: str) -> bool:
        """删除对话(内存 + DB 同步)"""
        if conversation_id in self._cache:
            del self._cache[conversation_id]
        if conversation_id in self.metadata:
            del self.metadata[conversation_id]
        if conversation_id in self.working_memory:
            del self.working_memory[conversation_id]
        self._delete_from_db(conversation_id)
        return True

    def cleanup_expired(self) -> int:
        """清理过期的对话"""
        now = datetime.now()
        expired_threshold = now - timedelta(days=self.CONVERSATION_TTL_DAYS)
        expired_ids = []

        for conv_id, metadata in self.metadata.items():
            last_activity = metadata.get("last_activity")
            if not last_activity:
                continue
            try:
                last = datetime.fromisoformat(last_activity)
            except (ValueError, TypeError):
                continue
            if last < expired_threshold:
                expired_ids.append(conv_id)

        for conv_id in expired_ids:
            self.delete_conversation(conv_id)

        return len(expired_ids)

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        total_messages = sum(len(msgs) for msgs in self._cache.values())

        return {
            "total_conversations": len(self._cache),
            "total_messages": total_messages,
            "avg_messages_per_conversation": (
                total_messages / len(self._cache) if self._cache else 0
            ),
            "active_conversations": sum(
                1 for m in self.metadata.values()
                if (datetime.now() - datetime.fromisoformat(
                    m.get("last_activity", datetime.now().isoformat())
                )).days < 1
            ),
        }

    def extract_preferences(self, conversation_id: str) -> Dict[str, Any]:
        """从对话中提取偏好信息"""
        messages = self._cache.get(conversation_id, [])

        preferences = {
            "interests": [],
            "questions": [],
            "actions": [],
            "feedback": [],
        }

        for msg in messages:
            content = msg.get("content", "")
            msg_meta = msg.get("metadata", {})
            intent = msg_meta.get("intent", "")

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
