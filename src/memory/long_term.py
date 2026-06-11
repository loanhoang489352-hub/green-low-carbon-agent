"""
长期记忆模块
基于向量数据库的思想,管理用户长期记忆和偏好

P5-G: 加 embedding BLOB 列,search_memories 走向量 + LIKE 兜底
"""

import json
import sqlite3
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
from datetime import datetime, timedelta
import hashlib
import sys

# 添加项目根目录
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# P5-F: 模块级 logger
try:
    from observability import get_logger
    _logger = get_logger("memory.long_term")
except Exception:
    import logging
    _logger = logging.getLogger("memory.long_term")


class LongTermMemory:
    """
    长期记忆管理器
    
    功能:
    - 存储用户持久化的偏好和记忆
    - 支持向量相似度检索（简化版：基于关键词）
    - 用户画像持久化
    - 记忆整合与遗忘
    """
    
    def __init__(self, db_path: str = None):
        """
        初始化长期记忆

        Args:
            db_path: 数据库路径
        """
        if db_path is None:
            db_path = project_root / "data" / "long_term_memory.db"

        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # P6.E.2: 连接池接入 — 同线程 60s 内复用连接
        # 必须在 _init_database() 之前定义,因为后者会调 self._release(conn)
        self._release = lambda c: None  # 池化连接由 db.connection 管 TTL

        # 初始化数据库
        self._init_database()

        print("📝 长期记忆系统初始化完成")

    def _get_conn(self):
        """P6.E.2: 连接池获取(同线程 60s 内复用)"""
        from db.connection import get_connection
        return get_connection(str(self.db_path))
    
    def _init_database(self):
        """初始化数据库表"""
        conn = self._get_conn()
        # 启用 WAL 模式支持并发读写,设置 busy_timeout 避免短时间锁定
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")
        cursor = conn.cursor()
        
        # 用户记忆表(P5-G: 加 embedding BLOB 列,默认 NULL)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                memory_type TEXT NOT NULL,
                content TEXT NOT NULL,
                importance REAL DEFAULT 0.5,
                created_at TEXT NOT NULL,
                last_accessed TEXT NOT NULL,
                access_count INTEGER DEFAULT 0,
                tags TEXT,
                embedding BLOB
            )
        """)
        
        # 用户偏好表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_preferences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                preference_type TEXT NOT NULL,
                value TEXT NOT NULL,
                confidence REAL DEFAULT 0.5,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, preference_type)
            )
        """)
        
        # 创建索引
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_user_id
            ON user_memories(user_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_preferences_user_id
            ON user_preferences(user_id)
        """)

        # P5-G: 旧表(没 embedding 列)自动 ALTER 加上
        cursor.execute("PRAGMA table_info(user_memories)")
        existing_cols = {row[1] for row in cursor.fetchall()}
        if "embedding" not in existing_cols:
            try:
                cursor.execute("ALTER TABLE user_memories ADD COLUMN embedding BLOB")
                _logger.info("[LTM] 旧表 user_memories 加 embedding BLOB 列")
            except Exception as e:
                _logger.warning("[LTM] ALTER TABLE embedding 失败: %s", e)

        conn.commit()
        self._release(conn)
    
    def add_memory(
        self,
        user_id: str,
        content: str,
        memory_type: str = "general",
        importance: float = 0.5,
        tags: List[str] = None
    ) -> int:
        """
        添加记忆

        Args:
            user_id: 用户ID
            content: 记忆内容
            memory_type: 记忆类型 (action_report, interest, feedback, general)
            importance: 重要性 (0-1)
            tags: 标签

        Returns:
            记忆ID
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        now = datetime.now().isoformat()
        tags_json = json.dumps(tags or [], ensure_ascii=False)

        # P5-G: 计算 embedding(embedder 不可用时存 NULL)
        embedding_blob = self._compute_embedding_blob(content)

        cursor.execute("""
            INSERT INTO user_memories
            (user_id, memory_type, content, importance, created_at, last_accessed, tags, embedding)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, memory_type, content, importance, now, now, tags_json, embedding_blob))

        memory_id = cursor.lastrowid

        conn.commit()
        self._release(conn)

        return memory_id

    def _compute_embedding_blob(self, content: str) -> Optional[bytes]:
        """P5-G: 懒加载 embedder 并编码 content → bytes (float32 little-endian)。

        失败 / embedder 不可用时返回 None,该行 embedding 列存 NULL,向量搜索
        会跳过该行,但 LIKE 搜索仍能找到。
        """
        try:
            from rag.rag_engine import get_rag_engine
            engine = get_rag_engine()
            if engine is None or not getattr(engine, "_initialized", False):
                return None
            embedder = getattr(engine, "_embedder", None)
            if embedder is None:
                return None
            import numpy as np
            vec = embedder.encode(content)
            # encode 可能返 (1, dim) 也可能返 (dim,)
            if vec.ndim == 2:
                vec = vec[0]
            return np.asarray(vec, dtype="float32").tobytes()
        except Exception as e:
            _logger.debug("[LTM] _compute_embedding_blob 失败(存 NULL): %s", e)
            return None
    
    def get_recent_memories(
        self,
        user_id: str,
        memory_type: str = None,
        limit: int = 10
    ) -> List[Dict]:
        """
        获取最近的记忆

        Args:
            user_id: 用户ID
            memory_type: 记忆类型过滤
            limit: 返回数量

        Returns:
            记忆列表
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        # P5-G: SELECT 加 embedding 列(返回 dict 不暴露,但要 fetch 让 sqlite
        # 拿到所有字段,避免长 blob 截断)
        if memory_type:
            cursor.execute("""
                SELECT id, memory_type, content, importance, created_at, tags, embedding
                FROM user_memories
                WHERE user_id = ? AND memory_type = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (user_id, memory_type, limit))
        else:
            cursor.execute("""
                SELECT id, memory_type, content, importance, created_at, tags, embedding
                FROM user_memories
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (user_id, limit))

        rows = cursor.fetchall()
        self._release(conn)

        memories = []
        for row in rows:
            memories.append({
                "id": row[0],
                "type": row[1],
                "content": row[2],
                "importance": row[3],
                "created_at": row[4],
                "tags": json.loads(row[5]),
                # 不暴露 embedding 字节(只用于内部)
            })

        # P4-B.3: 访问热度更新(防止热度永不变,decay 与 search 失真)
        if memories:
            self._bump_access([m["id"] for m in memories])

        return memories

    def search_memories(
        self,
        user_id: str,
        query: str,
        limit: int = 5
    ) -> List[Dict]:
        """P5-G: 向量检索 + LIKE 兜底

        1) 加载该用户全部 memories(有/无 embedding 都加载)
        2) 编码 query(embedder 可用时)
        3) 计算 cosine 相似度 → 取 top-20
        4) LIKE 过滤 query 关键词(对全部 memories)
        5) 合并:向量命中(score=similarity) + LIKE 命中(score=importance),去重,按 score 排序
        6) 拿 top `limit`,调 _bump_access

        降级行为:
        - embedder 不可用 → 整个向量步骤跳过,降级为纯 LIKE(原行为)
        - embedding IS NULL 的行 → 向量步骤跳过,LIKE 仍命中
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        rows = cursor.execute(
            "SELECT id, memory_type, content, importance, created_at, tags, embedding "
            "FROM user_memories WHERE user_id = ?",
            (user_id,),
        ).fetchall()
        self._release(conn)

        if not rows:
            return []

        # 1) 解析(embedding 反序列化为 numpy 数组)
        parsed = []
        for r in rows:
            emb_bytes = r[6]
            emb = None
            if emb_bytes:
                try:
                    import numpy as np
                    emb = np.frombuffer(emb_bytes, dtype="float32")
                    if emb.size == 0:
                        emb = None
                except Exception:
                    emb = None
            parsed.append({
                "id": r[0],
                "type": r[1],
                "content": r[2],
                "importance": r[3],
                "created_at": r[4],
                "tags": json.loads(r[5]),
                "_embedding": emb,
            })

        # 2) 向量召回(embedder 不可用 → try/except 跳过)
        vector_scored: List[Tuple[float, Dict]] = []
        try:
            from rag.rag_engine import get_rag_engine
            engine = get_rag_engine()
            if engine is not None and getattr(engine, "_initialized", False):
                embedder = getattr(engine, "_embedder", None)
                if embedder is not None:
                    import numpy as np
                    q_vec = np.asarray(embedder.encode(query), dtype="float32")
                    if q_vec.ndim == 2:
                        q_vec = q_vec[0]
                    q_norm = float(np.linalg.norm(q_vec))
                    if q_norm > 0:
                        scored = []
                        for it in parsed:
                            emb = it["_embedding"]
                            if emb is None or emb.size == 0:
                                continue
                            e_norm = float(np.linalg.norm(emb))
                            if e_norm == 0:
                                continue
                            sim = float(np.dot(emb, q_vec) / (e_norm * q_norm))
                            scored.append((sim, it))
                        scored.sort(key=lambda x: -x[0])
                        vector_scored = scored[:20]  # top-20 for LIKE filter
        except Exception as e:
            _logger.debug("[LTM] 向量检索失败,降级为 LIKE: %s", e)

        # 3) LIKE 召回(对全部 memories,按 query 关键词子串匹配)
        keywords = [k for k in query.split() if k]
        like_hits = []
        for it in parsed:
            if keywords:
                content = it["content"] or ""
                if not any(k in content for k in keywords):
                    continue
            like_hits.append(it)

        # 4) 合并:向量命中(按 similarity) + LIKE 命中(按 importance, created_at)
        seen_ids = set()
        merged: List[Dict] = []
        for sim, it in vector_scored:
            if it["id"] in seen_ids:
                continue
            seen_ids.add(it["id"])
            merged.append({**it, "_score": sim, "_source": "vector"})
        for it in like_hits:
            if it["id"] in seen_ids:
                continue
            seen_ids.add(it["id"])
            merged.append({**it, "_score": it["importance"], "_source": "like"})

        # 5) 排序(向量命中的 similarity 优先,like 的用 importance 兜底)
        merged.sort(key=lambda m: -m["_score"])

        # 6) 返回 top `limit`(不暴露内部 _embedding / _score / _source)
        result = [{
            "id": m["id"],
            "type": m["type"],
            "content": m["content"],
            "importance": m["importance"],
            "created_at": m["created_at"],
            "tags": m["tags"],
        } for m in merged[:limit]]

        # P4-B.3: 访问热度更新
        if result:
            self._bump_access([r["id"] for r in result])

        return result

    def _bump_access(self, memory_ids: List[int]) -> None:
        """访问热度更新(P4-B.3 接入)

        Args:
            memory_ids: 被访问到的记忆 ID 列表
        """
        if not memory_ids:
            return
        conn = self._get_conn()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        try:
            placeholders = ",".join("?" for _ in memory_ids)
            cursor.execute(
                f"""
                UPDATE user_memories
                SET last_accessed = ?,
                    access_count = access_count + 1
                WHERE id IN ({placeholders})
                """,
                (now, *memory_ids),
            )
            conn.commit()
        finally:
            self._release(conn)
    
    def update_preference(
        self,
        user_id: str,
        preference_type: str,
        value: str,
        confidence: float = 0.5
    ):
        """
        更新用户偏好
        
        Args:
            user_id: 用户ID
            preference_type: 偏好类型
            value: 偏好值
            confidence: 置信度
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        
        now = datetime.now().isoformat()
        
        # 如果值是列表或字典，转换为 JSON 字符串
        if isinstance(value, (list, dict)):
            value = json.dumps(value, ensure_ascii=False)
        
        cursor.execute("""
            INSERT INTO user_preferences (user_id, preference_type, value, confidence, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, preference_type)
            DO UPDATE SET
                value = excluded.value,
                confidence = excluded.confidence,
                updated_at = excluded.updated_at
        """, (user_id, preference_type, value, confidence, now))
        
        conn.commit()
        self._release(conn)
    
    def get_preferences(self, user_id: str) -> Dict[str, Dict]:
        """
        获取用户偏好
        
        Args:
            user_id: 用户ID
        
        Returns:
            偏好字典 {type: {value, confidence, updated_at}}
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT preference_type, value, confidence, updated_at
            FROM user_preferences
            WHERE user_id = ?
        """, (user_id,))
        
        rows = cursor.fetchall()
        self._release(conn)
        
        preferences = {}
        for row in rows:
            preferences[row[0]] = {
                "value": row[1],
                "confidence": row[2],
                "updated_at": row[3]
            }
        
        return preferences
    
    def get_all_memories(self, user_id: str) -> List[Dict]:
        """获取用户所有记忆"""
        return self.get_recent_memories(user_id, limit=1000)
    
    def delete_old_memories(self, user_id: str, days: int = 90) -> int:
        """
        删除旧记忆
        
        Args:
            user_id: 用户ID
            days: 保留最近多少天的记忆
        
        Returns:
            删除的记忆数量
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        
        cutoff = (
            datetime.now() - timedelta(days=days)
        ).isoformat()
        
        cursor.execute("""
            DELETE FROM user_memories
            WHERE user_id = ? AND created_at < ?
        """, (user_id, cutoff))
        
        deleted = cursor.rowcount
        
        conn.commit()
        self._release(conn)
        
        return deleted
    
    def decay_importance(self, decay_rate: float = 0.95, half_life_days: int = None) -> int:
        """
        降低记忆重要性(记忆遗忘机制)

        Args:
            decay_rate: 直接指定每次衰减乘数(如 0.95)。与 half_life_days 互斥。
            half_life_days: 半衰期天数,系统根据"距上次访问天数"自动计算衰减率。
                          调度器默认传 30。半衰期公式:rate = 0.5 ** (days / half_life)
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        if half_life_days is not None and half_life_days > 0:
            # 逐条更新:基于"距 last_accessed 的天数"算衰减率
            now = datetime.now()
            cursor.execute(
                """
                SELECT id, importance, last_accessed
                FROM user_memories
                WHERE importance > 0.05
                """
            )
            rows = cursor.fetchall()
            updated = 0
            for row in rows:
                mem_id, importance, last_accessed = row
                try:
                    last = datetime.fromisoformat(last_accessed)
                    days = max((now - last).total_seconds() / 86400, 0)
                except (ValueError, TypeError):
                    days = 0
                rate = 0.5 ** (days / half_life_days)
                new_imp = importance * rate
                if new_imp < 0.05:
                    new_imp = 0.05
                if abs(new_imp - importance) > 1e-9:
                    cursor.execute(
                        "UPDATE user_memories SET importance = ? WHERE id = ?",
                        (new_imp, mem_id),
                    )
                    updated += 1
            conn.commit()
            self._release(conn)
            return updated

        # 兼容旧调用:整体乘以 decay_rate
        cursor.execute("""
            UPDATE user_memories
            SET importance = importance * ?
            WHERE importance > 0.1
        """, (decay_rate,))

        conn.commit()
        self._release(conn)
        return cursor.rowcount
    
    def consolidate_short_term(
        self,
        user_id: str,
        short_term_memories: List[Dict]
    ):
        """
        将短期记忆整合到长期记忆
        
        Args:
            user_id: 用户ID
            short_term_memories: 短期记忆列表
        """
        for memory in short_term_memories:
            self.add_memory(
                user_id=user_id,
                content=memory.get("content", ""),
                memory_type=memory.get("type", "general"),
                importance=memory.get("importance", 0.5)
            )
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM user_memories")
        total_memories = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(DISTINCT user_id) FROM user_memories")
        total_users = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM user_preferences")
        total_preferences = cursor.fetchone()[0]
        
        self._release(conn)
        
        return {
            "total_memories": total_memories,
            "total_users": total_users,
            "total_preferences": total_preferences,
            "avg_memories_per_user": (
                total_memories / total_users if total_users > 0 else 0
            )
        }


# 导出 timedelta 以便外部使用
