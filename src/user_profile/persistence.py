"""
用户行为持久化辅助(P4-C.4)

为 GoalReminderSystem / AchievementSystem / CarbonFootprintCalculator
提供 DB 持久化能力。复用 user_profiles.db:
- user_goals
- user_achievements
- carbon_footprint_log

不破坏现有 in-memory 类行为(原 goal_tracker / achievement_system 仍可用),
只是新增"持久化"接口。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional


class BehaviorPersistence:
    """行为/目标/成就/碳足迹的 DB 持久化层

    4 张表(behavior_events / user_goals / user_achievements / carbon_footprint_log)
    均落在 behavior_tracker.db(由 Schema Registry 管理)
    """

    def __init__(self, db_path: str = None) -> None:
        if db_path is None:
            project_root = Path(__file__).parent.parent.parent
            db_path = str(project_root / "data" / "behavior_tracker.db")
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    # ===== behavior_events =====

    def record_event(
        self,
        user_id: str,
        event_type: str,
        event_data: Dict[str, Any] = None,
        intent_type: str = None,
        context: str = None,
        carbon_impact: float = None,
        duration_minutes: int = None,
        related_interests: List[str] = None,
    ) -> int:
        """写入一条行为事件

        Args:
            user_id: 用户 ID
            event_type: 事件类型(出行/饮食/用电/低碳行为 等)
            event_data: 详细数据(JSON)
            intent_type: 关联的意图类型
            context: 上下文说明
            carbon_impact: 碳影响(kg CO2e, 正数=排放, 负数=减排)
            duration_minutes: 持续分钟
            related_interests: 关联的兴趣 ID 列表

        Returns:
            事件 ID
        """
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute(
                """
                INSERT INTO behavior_events
                (user_id, event_type, event_data, intent_type, context,
                 carbon_impact, duration_minutes, related_interests, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    event_type,
                    json.dumps(event_data or {}, ensure_ascii=False),
                    intent_type,
                    context,
                    carbon_impact,
                    duration_minutes,
                    json.dumps(related_interests or [], ensure_ascii=False),
                    now,
                ),
            )
            event_id = cursor.lastrowid
            conn.commit()
            return event_id
        finally:
            conn.close()

    def get_user_events(
        self,
        user_id: str,
        event_type: str = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """查询用户行为事件"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            if event_type:
                cursor.execute(
                    """
                    SELECT id, event_type, event_data, intent_type, context,
                           carbon_impact, duration_minutes, related_interests, created_at
                    FROM behavior_events
                    WHERE user_id = ? AND event_type = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (user_id, event_type, limit),
                )
            else:
                cursor.execute(
                    """
                    SELECT id, event_type, event_data, intent_type, context,
                           carbon_impact, duration_minutes, related_interests, created_at
                    FROM behavior_events
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (user_id, limit),
                )
            rows = cursor.fetchall()
            results = []
            for row in rows:
                related = row[7]
                try:
                    related = json.loads(related) if related else []
                except (ValueError, TypeError):
                    related = []
                data = row[2]
                try:
                    data = json.loads(data) if data else {}
                except (ValueError, TypeError):
                    data = {"raw": data}
                results.append({
                    "id": row[0],
                    "event_type": row[1],
                    "event_data": data,
                    "intent_type": row[3],
                    "context": row[4],
                    "carbon_impact": row[5],
                    "duration_minutes": row[6],
                    "related_interests": related,
                    "created_at": row[8],
                })
            return results
        finally:
            conn.close()

    # ===== user_goals =====

    def create_goal(
        self,
        user_id: str,
        goal_type: str,
        target_value: float,
        deadline: str = None,
    ) -> int:
        """创建持久化目标"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute(
                """
                INSERT INTO user_goals
                (user_id, goal_type, target_value, current_value, deadline,
                 status, created_at, updated_at)
                VALUES (?, ?, ?, 0, ?, 'active', ?, ?)
                """,
                (user_id, goal_type, target_value, deadline, now, now),
            )
            goal_id = cursor.lastrowid
            conn.commit()
            return goal_id
        finally:
            conn.close()

    def update_goal_progress(self, goal_id: int, current_value: float) -> bool:
        """更新目标进度(完成时自动标记)"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute("SELECT target_value FROM user_goals WHERE id = ?", (goal_id,))
            row = cursor.fetchone()
            if not row:
                return False
            target = row[0]
            new_status = "completed" if current_value >= target else "active"
            cursor.execute(
                """
                UPDATE user_goals
                SET current_value = ?, status = ?, updated_at = ?
                WHERE id = ?
                """,
                (current_value, new_status, now, goal_id),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def get_active_goals(self, user_id: str) -> List[Dict[str, Any]]:
        """获取用户活跃目标"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, goal_type, target_value, current_value, deadline, status,
                       created_at, updated_at
                FROM user_goals
                WHERE user_id = ? AND status = 'active'
                ORDER BY created_at DESC
                """,
                (user_id,),
            )
            rows = cursor.fetchall()
            return [
                {
                    "id": row[0],
                    "goal_type": row[1],
                    "target_value": row[2],
                    "current_value": row[3],
                    "deadline": row[4],
                    "status": row[5],
                    "created_at": row[6],
                    "updated_at": row[7],
                }
                for row in rows
            ]
        finally:
            conn.close()

    # ===== user_achievements =====

    def grant_achievement(
        self,
        user_id: str,
        achievement_code: str,
        metadata: Dict[str, Any] = None,
    ) -> bool:
        """授予成就(已存在则跳过)"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            try:
                cursor.execute(
                    """
                    INSERT INTO user_achievements
                    (user_id, achievement_code, earned_at, metadata)
                    VALUES (?, ?, ?, ?)
                    """,
                    (user_id, achievement_code, now, json.dumps(metadata or {}, ensure_ascii=False)),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                # UNIQUE 冲突:已存在
                return False
        finally:
            conn.close()

    def get_user_achievements(self, user_id: str) -> List[Dict[str, Any]]:
        """获取用户所有成就"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, achievement_code, earned_at, metadata
                FROM user_achievements
                WHERE user_id = ?
                ORDER BY earned_at DESC
                """,
                (user_id,),
            )
            rows = cursor.fetchall()
            results = []
            for row in rows:
                meta = row[3]
                try:
                    meta = json.loads(meta) if meta else {}
                except (ValueError, TypeError):
                    meta = {}
                results.append({
                    "id": row[0],
                    "code": row[1],
                    "earned_at": row[2],
                    "metadata": meta,
                })
            return results
        finally:
            conn.close()

    # ===== carbon_footprint_log =====

    def record_carbon(
        self,
        user_id: str,
        category: str,
        amount_kg_co2e: float,
        source: str = "user_report",
        metadata: Dict[str, Any] = None,
    ) -> int:
        """记录碳足迹"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute(
                """
                INSERT INTO carbon_footprint_log
                (user_id, category, amount_kg_co2e, recorded_at, source, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, category, amount_kg_co2e, now, source,
                 json.dumps(metadata or {}, ensure_ascii=False)),
            )
            log_id = cursor.lastrowid
            conn.commit()
            return log_id
        finally:
            conn.close()

    def calculate_weekly_total(self, user_id: str) -> float:
        """计算用户本周总碳足迹(kg CO2e)"""
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=7)).isoformat()
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COALESCE(SUM(amount_kg_co2e), 0)
                FROM carbon_footprint_log
                WHERE user_id = ? AND recorded_at >= ?
                """,
                (user_id, cutoff),
            )
            row = cursor.fetchone()
            return row[0] if row else 0.0
        finally:
            conn.close()


# 单例
_persistence: Optional[BehaviorPersistence] = None


def get_behavior_persistence() -> BehaviorPersistence:
    """获取持久化单例"""
    global _persistence
    if _persistence is None:
        _persistence = BehaviorPersistence()
    return _persistence
