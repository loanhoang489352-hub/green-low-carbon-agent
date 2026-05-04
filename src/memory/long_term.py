"""
长期记忆模块
基于向量数据库的思想，管理用户长期记忆和偏好
"""

import json
import sqlite3
from typing import List, Dict, Any, Optional
from pathlib import Path
from datetime import datetime, timedelta
import hashlib
import sys

# 添加项目根目录
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


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
        
        # 初始化数据库
        self._init_database()
        
        print("📝 长期记忆系统初始化完成")
    
    def _init_database(self):
        """初始化数据库表"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        # 用户记忆表
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
                tags TEXT
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
        
        conn.commit()
        conn.close()
    
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
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        now = datetime.now().isoformat()
        tags_json = json.dumps(tags or [], ensure_ascii=False)
        
        cursor.execute("""
            INSERT INTO user_memories
            (user_id, memory_type, content, importance, created_at, last_accessed, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, memory_type, content, importance, now, now, tags_json))
        
        memory_id = cursor.lastrowid
        
        conn.commit()
        conn.close()
        
        return memory_id
    
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
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        if memory_type:
            cursor.execute("""
                SELECT id, memory_type, content, importance, created_at, tags
                FROM user_memories
                WHERE user_id = ? AND memory_type = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (user_id, memory_type, limit))
        else:
            cursor.execute("""
                SELECT id, memory_type, content, importance, created_at, tags
                FROM user_memories
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (user_id, limit))
        
        rows = cursor.fetchall()
        conn.close()
        
        memories = []
        for row in rows:
            memories.append({
                "id": row[0],
                "type": row[1],
                "content": row[2],
                "importance": row[3],
                "created_at": row[4],
                "tags": json.loads(row[5])
            })
        
        return memories
    
    def search_memories(
        self,
        user_id: str,
        query: str,
        limit: int = 5
    ) -> List[Dict]:
        """
        搜索记忆（简化版：基于关键词匹配）
        
        Args:
            user_id: 用户ID
            query: 查询文本
            limit: 返回数量
        
        Returns:
            匹配的记忆列表
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        # 简单关键词搜索
        keywords = query.split()
        keyword_conditions = " OR ".join(
            ["content LIKE ?" for _ in keywords]
        )
        
        cursor.execute(f"""
            SELECT id, memory_type, content, importance, created_at, tags
            FROM user_memories
            WHERE user_id = ? AND ({keyword_conditions})
            ORDER BY importance DESC, created_at DESC
            LIMIT ?
        """, (user_id, *[f"%{kw}%" for kw in keywords], limit))
        
        rows = cursor.fetchall()
        conn.close()
        
        memories = []
        for row in rows:
            memories.append({
                "id": row[0],
                "type": row[1],
                "content": row[2],
                "importance": row[3],
                "created_at": row[4],
                "tags": json.loads(row[5])
            })
        
        return memories
    
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
        conn = sqlite3.connect(str(self.db_path))
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
        conn.close()
    
    def get_preferences(self, user_id: str) -> Dict[str, Dict]:
        """
        获取用户偏好
        
        Args:
            user_id: 用户ID
        
        Returns:
            偏好字典 {type: {value, confidence, updated_at}}
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT preference_type, value, confidence, updated_at
            FROM user_preferences
            WHERE user_id = ?
        """, (user_id,))
        
        rows = cursor.fetchall()
        conn.close()
        
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
        conn = sqlite3.connect(str(self.db_path))
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
        conn.close()
        
        return deleted
    
    def decay_importance(self, decay_rate: float = 0.95):
        """
        降低记忆重要性（记忆遗忘机制）
        
        Args:
            decay_rate: 衰减率
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE user_memories
            SET importance = importance * ?
            WHERE importance > 0.1
        """, (decay_rate,))
        
        conn.commit()
        conn.close()
    
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
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM user_memories")
        total_memories = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(DISTINCT user_id) FROM user_memories")
        total_users = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM user_preferences")
        total_preferences = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            "total_memories": total_memories,
            "total_users": total_users,
            "total_preferences": total_preferences,
            "avg_memories_per_user": (
                total_memories / total_users if total_users > 0 else 0
            )
        }


# 导出 timedelta 以便外部使用
