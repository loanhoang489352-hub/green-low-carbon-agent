# -*- coding: utf-8 -*-
"""
用户反馈管理器
管理用户对智能体回复的点赞、点踩、评论反馈
"""

import sqlite3
import os
import sys
import uuid
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any

# Windows UTF-8 encoding
if sys.platform == 'win32':
    import io
    if hasattr(sys.stdout, 'buffer') and not isinstance(sys.stdout, io.TextIOWrapper):
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
        except Exception:
            pass

script_path = Path(__file__).resolve()
project_root = script_path.parent.parent.parent
data_dir = project_root / "data"
data_dir.mkdir(exist_ok=True)

DB_PATH = str(data_dir / "feedback.db")


def _get_connection() -> sqlite3.Connection:
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _init_database():
    """初始化反馈数据库"""
    conn = _get_connection()
    cursor = conn.cursor()

    # 消息反馈表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS message_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            conversation_id TEXT,
            feedback_type TEXT NOT NULL CHECK(feedback_type IN ('like', 'dislike', 'comment')),
            reason TEXT,
            comment TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(message_id, user_id, feedback_type)
        )
    ''')

    # 创建索引提升查询性能
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_feedback_message
        ON message_feedback(message_id)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_feedback_user
        ON message_feedback(user_id)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_feedback_conversation
        ON message_feedback(conversation_id)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_feedback_created
        ON message_feedback(created_at)
    ''')

    conn.commit()
    conn.close()


class FeedbackManager:
    """用户反馈管理器"""

    _initialized = False

    def __init__(self):
        if not FeedbackManager._initialized:
            _init_database()
            FeedbackManager._initialized = True

    def add_feedback(
        self,
        message_id: str,
        user_id: str,
        conversation_id: str,
        feedback_type: str,
        reason: Optional[str] = None,
        comment: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        添加反馈

        Args:
            message_id: 消息ID
            user_id: 用户ID
            conversation_id: 对话ID
            feedback_type: 反馈类型 (like/dislike/comment/remove_like/remove_dislike)
            reason: 点踩原因 (dislike专用)
            comment: 评论内容 (comment专用)

        Returns:
            包含状态和信息的字典
        """
        # 处理取消点赞/点踩
        if feedback_type == 'remove_like':
            self.remove_feedback(message_id, user_id, 'like')
            return {"success": True, "action": "removed", "feedback_type": "like", "message_id": message_id}
        if feedback_type == 'remove_dislike':
            self.remove_feedback(message_id, user_id, 'dislike')
            return {"success": True, "action": "removed", "feedback_type": "dislike", "message_id": message_id}

        if feedback_type not in ('like', 'dislike', 'comment'):
            return {"success": False, "error": f"无效的反馈类型: {feedback_type}"}

        if feedback_type == 'dislike' and not reason:
            return {"success": False, "error": "点踩必须提供原因"}

        if feedback_type == 'comment' and not comment:
            return {"success": False, "error": "评论内容不能为空"}

        try:
            conn = _get_connection()
            cursor = conn.cursor()

            # 检查是否已有相同反馈
            cursor.execute('''
                SELECT id, feedback_type FROM message_feedback
                WHERE message_id = ? AND user_id = ?
            ''', (message_id, user_id))
            existing = cursor.fetchall()

            # 如果是点赞/点踩，只能有一个（替换旧反馈）
            if feedback_type in ('like', 'dislike'):
                for row in existing:
                    if row['feedback_type'] in ('like', 'dislike'):
                        # 更新现有反馈
                        cursor.execute('''
                            UPDATE message_feedback
                            SET feedback_type = ?, reason = ?, comment = ?, created_at = ?
                            WHERE id = ?
                        ''', (feedback_type, reason, None, datetime.now().isoformat(), row['id']))
                        conn.commit()
                        conn.close()
                        return {
                            "success": True,
                            "action": "updated",
                            "feedback_type": feedback_type,
                            "message_id": message_id
                        }

            # 如果是评论，允许同一条消息多条评论
            if feedback_type == 'comment':
                feedback_id = str(uuid.uuid4())[:12]
                cursor.execute('''
                    INSERT INTO message_feedback (message_id, user_id, conversation_id, feedback_type, reason, comment, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (message_id, user_id, conversation_id, feedback_type, None, comment, datetime.now().isoformat()))
                conn.commit()
                conn.close()
                return {
                    "success": True,
                    "action": "added",
                    "feedback_type": feedback_type,
                    "message_id": message_id
                }

            # 新增点赞/点踩
            cursor.execute('''
                INSERT INTO message_feedback (message_id, user_id, conversation_id, feedback_type, reason, comment, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (message_id, user_id, conversation_id, feedback_type, reason, None, datetime.now().isoformat()))

            conn.commit()
            conn.close()

            return {
                "success": True,
                "action": "added",
                "feedback_type": feedback_type,
                "message_id": message_id
            }

        except sqlite3.IntegrityError:
            return {"success": False, "error": "该反馈已存在"}
        except Exception as e:
            print(f"[FeedbackManager] 添加反馈失败: {e}")
            return {"success": False, "error": str(e)}

    def remove_feedback(self, message_id: str, user_id: str, feedback_type: str = None) -> bool:
        """
        移除反馈

        Args:
            message_id: 消息ID
            user_id: 用户ID
            feedback_type: 反馈类型（不指定则删除所有该消息的反馈）

        Returns:
            是否成功
        """
        try:
            conn = _get_connection()
            cursor = conn.cursor()

            if feedback_type:
                cursor.execute('''
                    DELETE FROM message_feedback
                    WHERE message_id = ? AND user_id = ? AND feedback_type = ?
                ''', (message_id, user_id, feedback_type))
            else:
                cursor.execute('''
                    DELETE FROM message_feedback
                    WHERE message_id = ? AND user_id = ?
                ''', (message_id, user_id))

            conn.commit()
            deleted = cursor.rowcount > 0
            conn.close()
            return deleted

        except Exception as e:
            print(f"[FeedbackManager] 移除反馈失败: {e}")
            return False

    def get_message_feedback(self, message_id: str) -> Dict[str, Any]:
        """
        获取某条消息的反馈统计

        Args:
            message_id: 消息ID

        Returns:
            反馈统计信息
        """
        try:
            conn = _get_connection()
            cursor = conn.cursor()

            # 统计各类反馈数量
            cursor.execute('''
                SELECT feedback_type, COUNT(*) as count
                FROM message_feedback
                WHERE message_id = ?
                GROUP BY feedback_type
            ''', (message_id,))
            rows = cursor.fetchall()

            stats = {
                "message_id": message_id,
                "like_count": 0,
                "dislike_count": 0,
                "comment_count": 0,
                "reasons": {},
                "comments": []
            }

            for row in rows:
                ftype = row['feedback_type']
                count = row['count']
                if ftype == 'like':
                    stats['like_count'] = count
                elif ftype == 'dislike':
                    stats['dislike_count'] = count
                elif ftype == 'comment':
                    stats['comment_count'] = count

            # 获取点踩原因分布
            if stats['dislike_count'] > 0:
                cursor.execute('''
                    SELECT reason, COUNT(*) as count
                    FROM message_feedback
                    WHERE message_id = ? AND feedback_type = 'dislike' AND reason IS NOT NULL
                    GROUP BY reason
                ''', (message_id,))
                for row in cursor.fetchall():
                    stats['reasons'][row['reason']] = row['count']

            # 获取评论列表
            if stats['comment_count'] > 0:
                cursor.execute('''
                    SELECT user_id, comment, created_at
                    FROM message_feedback
                    WHERE message_id = ? AND feedback_type = 'comment'
                    ORDER BY created_at DESC
                ''', (message_id,))
                stats['comments'] = [
                    {"user_id": row['user_id'], "comment": row['comment'], "created_at": row['created_at']}
                    for row in cursor.fetchall()
                ]

            conn.close()
            return stats

        except Exception as e:
            print(f"[FeedbackManager] 获取反馈统计失败: {e}")
            return {"message_id": message_id, "error": str(e)}

    def get_user_feedback_history(self, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """
        获取用户的反馈历史

        Args:
            user_id: 用户ID
            limit: 返回数量限制

        Returns:
            反馈历史列表
        """
        try:
            conn = _get_connection()
            cursor = conn.cursor()

            cursor.execute('''
                SELECT message_id, conversation_id, feedback_type, reason, comment, created_at
                FROM message_feedback
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            ''', (user_id, limit))

            history = []
            for row in cursor.fetchall():
                item = {
                    "message_id": row['message_id'],
                    "conversation_id": row['conversation_id'],
                    "feedback_type": row['feedback_type'],
                    "created_at": row['created_at']
                }
                if row['reason']:
                    item['reason'] = row['reason']
                if row['comment']:
                    item['comment'] = row['comment']
                history.append(item)

            conn.close()
            return history

        except Exception as e:
            print(f"[FeedbackManager] 获取反馈历史失败: {e}")
            return []

    def get_conversation_feedback_stats(self, conversation_id: str) -> Dict[str, Any]:
        """
        获取某个对话的反馈统计

        Args:
            conversation_id: 对话ID

        Returns:
            反馈统计
        """
        try:
            conn = _get_connection()
            cursor = conn.cursor()

            cursor.execute('''
                SELECT
                    COUNT(*) as total_feedback,
                    SUM(CASE WHEN feedback_type = 'like' THEN 1 ELSE 0 END) as like_count,
                    SUM(CASE WHEN feedback_type = 'dislike' THEN 1 ELSE 0 END) as dislike_count,
                    SUM(CASE WHEN feedback_type = 'comment' THEN 1 ELSE 0 END) as comment_count
                FROM message_feedback
                WHERE conversation_id = ?
            ''', (conversation_id,))

            row = cursor.fetchone()
            conn.close()

            return {
                "conversation_id": conversation_id,
                "total_feedback": row['total_feedback'] or 0,
                "like_count": row['like_count'] or 0,
                "dislike_count": row['dislike_count'] or 0,
                "comment_count": row['comment_count'] or 0
            }

        except Exception as e:
            print(f"[FeedbackManager] 获取对话反馈统计失败: {e}")
            return {"conversation_id": conversation_id, "error": str(e)}

    def get_feedback_stats(self, days: int = 7) -> Dict[str, Any]:
        """
        获取反馈统计汇总（用于后台管理）

        Args:
            days: 统计天数范围

        Returns:
            统计汇总
        """
        try:
            conn = _get_connection()
            cursor = conn.cursor()

            # 计算日期边界
            cursor.execute('''
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN feedback_type = 'like' THEN 1 ELSE 0 END) as likes,
                    SUM(CASE WHEN feedback_type = 'dislike' THEN 1 ELSE 0 END) as dislikes,
                    SUM(CASE WHEN feedback_type = 'comment' THEN 1 ELSE 0 END) as comments
                FROM message_feedback
                WHERE created_at >= datetime('now', '-' || ? || ' days')
            ''', (days,))

            row = cursor.fetchone()

            # 点踩原因分布
            cursor.execute('''
                SELECT reason, COUNT(*) as count
                FROM message_feedback
                WHERE feedback_type = 'dislike'
                    AND reason IS NOT NULL
                    AND created_at >= datetime('now', '-' || ? || ' days')
                GROUP BY reason
                ORDER BY count DESC
            ''', (days,))
            reason_rows = cursor.fetchall()

            # 每日反馈趋势
            cursor.execute('''
                SELECT
                    date(created_at) as date,
                    SUM(CASE WHEN feedback_type = 'like' THEN 1 ELSE 0 END) as likes,
                    SUM(CASE WHEN feedback_type = 'dislike' THEN 1 ELSE 0 END) as dislikes,
                    SUM(CASE WHEN feedback_type = 'comment' THEN 1 ELSE 0 END) as comments
                FROM message_feedback
                WHERE created_at >= datetime('now', '-' || ? || ' days')
                GROUP BY date(created_at)
                ORDER BY date ASC
            ''', (days,))
            trend_rows = cursor.fetchall()

            # 活跃用户提供反馈最多的
            cursor.execute('''
                SELECT user_id, COUNT(*) as feedback_count
                FROM message_feedback
                WHERE created_at >= datetime('now', '-' || ? || ' days')
                GROUP BY user_id
                ORDER BY feedback_count DESC
                LIMIT 10
            ''', (days,))
            top_users = cursor.fetchall()

            conn.close()

            total = row['total'] or 0
            likes = row['likes'] or 0
            dislikes = row['dislikes'] or 0
            comments = row['comments'] or 0

            return {
                "period_days": days,
                "total_feedback": total,
                "likes": likes,
                "dislikes": dislikes,
                "comments": comments,
                "satisfaction_rate": round(likes / total * 100, 1) if total > 0 else 0,
                "dislike_reasons": {row['reason']: row['count'] for row in reason_rows},
                "daily_trend": [
                    {
                        "date": r['date'],
                        "likes": r['likes'],
                        "dislikes": r['dislikes'],
                        "comments": r['comments']
                    }
                    for r in trend_rows
                ],
                "top_users": [
                    {"user_id": r['user_id'], "feedback_count": r['feedback_count']}
                    for r in top_users
                ]
            }

        except Exception as e:
            print(f"[FeedbackManager] 获取反馈统计汇总失败: {e}")
            return {"error": str(e)}

    def get_recent_negative_feedback(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        获取最近的负面反馈（点踩+评论），用于分析改进

        Args:
            limit: 返回数量

        Returns:
            负面反馈列表
        """
        try:
            conn = _get_connection()
            cursor = conn.cursor()

            cursor.execute('''
                SELECT
                    mf.message_id,
                    mf.user_id,
                    mf.conversation_id,
                    mf.feedback_type,
                    mf.reason,
                    mf.comment,
                    mf.created_at
                FROM message_feedback mf
                WHERE mf.feedback_type IN ('dislike', 'comment')
                ORDER BY mf.created_at DESC
                LIMIT ?
            ''', (limit,))

            results = []
            for row in cursor.fetchall():
                item = {
                    "message_id": row['message_id'],
                    "user_id": row['user_id'],
                    "conversation_id": row['conversation_id'],
                    "feedback_type": row['feedback_type'],
                    "created_at": row['created_at']
                }
                if row['reason']:
                    item['reason'] = row['reason']
                if row['comment']:
                    item['comment'] = row['comment']
                results.append(item)

            conn.close()
            return results

        except Exception as e:
            print(f"[FeedbackManager] 获取负面反馈失败: {e}")
            return []

    def check_user_feedback(self, message_id: str, user_id: str) -> Dict[str, bool]:
        """
        检查用户对某条消息的反馈状态

        Args:
            message_id: 消息ID
            user_id: 用户ID

        Returns:
            用户对该消息的反馈状态
        """
        try:
            conn = _get_connection()
            cursor = conn.cursor()

            cursor.execute('''
                SELECT feedback_type FROM message_feedback
                WHERE message_id = ? AND user_id = ?
            ''', (message_id, user_id))

            rows = cursor.fetchall()
            conn.close()

            return {
                "liked": any(r['feedback_type'] == 'like' for r in rows),
                "disliked": any(r['feedback_type'] == 'dislike' for r in rows),
                "commented": any(r['feedback_type'] == 'comment' for r in rows)
            }

        except Exception as e:
            print(f"[FeedbackManager] 检查反馈状态失败: {e}")
            return {"liked": False, "disliked": False, "commented": False}
