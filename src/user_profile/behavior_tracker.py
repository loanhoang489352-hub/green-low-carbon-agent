"""
行为追踪器 - 统一入口
整合碳足迹、目标追踪、成就系统

P4-C.3/C.4:行为事件持久化到 user_profiles.db 的 behavior_events / user_goals /
user_achievements / carbon_footprint_log 表(由 Schema Registry 管理)
"""

from typing import Dict, Optional

from .carbon_footprint import CarbonFootprintCalculator
from .goal_tracker import GoalReminderSystem
from .achievement_system import AchievementSystem
from .persistence import get_behavior_persistence


class BehaviorTracker:
    """
    行为追踪器 - 统一入口

    整合碳足迹计算、目标追踪、成就系统，
    为用户提供完整的行为改变支持
    """

    def __init__(self, db_path: str = None):
        # 旧 db_path 字段保留兼容(已弃用,持久化改走 user_profiles.db)
        self.db_path = db_path or "data/behavior_tracker.db"
        self._persistence = get_behavior_persistence()

        self.carbon = CarbonFootprintCalculator()
        self.goals = GoalReminderSystem()
        self.achievements = AchievementSystem()

    # ===== 碳足迹记录 =====

    def record_travel(self, user_id: str, vehicle: str, distance: float) -> Dict:
        """记录出行行为"""
        record = self.carbon.record_action("出行", vehicle, distance, "km")

        self._save_behavior(user_id, "出行", vehicle, distance, "km", record.amount)

        # 获得积分
        action_key = f"{vehicle}1次" if vehicle in ["公共交通", "私家车"] else vehicle
        if action_key in self.carbon.REDUCTION_ACTIONS:
            result = self.achievements.earn_points(user_id, action_key)

        return {"carbon_kg": record.amount, "distance": distance, "vehicle": vehicle}

    def record_diet(self, user_id: str, food_type: str, weight: float = 1.0) -> Dict:
        """记录饮食行为"""
        record = self.carbon.record_action("饮食", food_type, weight, "kg")

        self._save_behavior(user_id, "饮食", food_type, weight, "kg", record.amount)

        # 获得积分
        if food_type in ["蔬菜", "水果"]:
            self.achievements.earn_points(user_id, "素食1天")

        return {"carbon_kg": record.amount, "food_type": food_type, "weight": weight}

    def record_electricity(self, user_id: str, kwh: float) -> Dict:
        """记录用电"""
        record = self.carbon.record_action("用电", "用电", kwh, "度")

        self._save_behavior(user_id, "用电", "用电", kwh, "度", record.amount)

        # 获得积分
        self.achievements.earn_points(user_id, "省电1度", kwh)

        return {"carbon_kg": record.amount, "kwh": kwh}

    def record_green_action(self, user_id: str, action: str, value: float = 1.0) -> Dict:
        """记录低碳行为（减排）"""
        record = self.carbon.record_reduction(action, value)

        self._save_behavior(
            user_id,
            "低碳",
            action,
            value,
            "次",
            -record.get("减排量", 0),  # 负数表示减排
        )

        # 获得积分
        points_result = self.achievements.earn_points(user_id, action, value)

        # 更新目标
        reduction = record.get("减排量", 0)
        for goal in self.goals.get_active_goals():
            self.goals.add_reduction(goal["goal_id"], reduction)

        return {
            "action": action,
            "减排量_kg": record.get("减排量", 0),
            "points_earned": points_result.get("points_earned", 0),
        }

    def _save_behavior(
        self, user_id: str, category: str, action: str, value: float, unit: str, carbon_kg: float
    ):
        """保存行为到数据库(P4-C.3:走 behavior_events 表)"""
        # carbon_kg: 正数=排放,负数=减排
        try:
            self._persistence.record_event(
                user_id=user_id,
                event_type=category,
                event_data={
                    "action": action,
                    "value": value,
                    "unit": unit,
                    "carbon_kg_legacy": carbon_kg,
                },
                carbon_impact=carbon_kg,
            )
            if carbon_kg is not None and category in ("出行", "饮食", "用电"):
                # 同步写 carbon_footprint_log
                self._persistence.record_carbon(
                    user_id=user_id,
                    category=category,
                    amount_kg_co2e=abs(carbon_kg),
                    source="behavior_tracker",
                    metadata={"action": action, "value": value, "unit": unit},
                )
        except Exception as e:
            import logging

            logging.getLogger(__name__).warning(
                "[BehaviorTracker] _save_behavior failed (non-fatal): %s",
                e,
            )

    # ===== 查询接口 =====

    def get_carbon_report(self, user_id: str = None, days: int = 30) -> Dict:
        """碳足迹报告"""
        return self.carbon.get_monthly_report()

    def get_goals_status(self) -> Dict:
        """目标状态"""
        return {
            "goals": self.goals.get_all_goals(),
            "statistics": self.goals.get_statistics(),
            "reminders": self.goals.check_reminders(),
        }

    def get_achievements(self, user_id: str = None) -> Dict:
        """成就档案"""
        if user_id:
            return self.achievements.get_user_profile(user_id)
        return {"error": "需要user_id"}

    def get_summary(self) -> Dict:
        """综合摘要"""
        return {
            "carbon": self.carbon.get_monthly_report(),
            "goals": self.goals.get_statistics(),
            "achievements": {
                "levels": len(self.achievements.LEVELS),
                "badges_count": len(self.achievements.BADGES),
            },
        }

    # ===== 目标管理 =====

    def create_goal(
        self,
        title: str,
        target_value: float = None,
        period: str = "weekly",
        category: str = "comprehensive",
    ) -> Dict:
        """创建目标"""
        goal = self.goals.create_goal(title, target_value, period, category)
        return self.goals.get_goal_status(goal.goal_id)

    def get_dashboard(self) -> Dict:
        """用户仪表板"""
        return {
            "carbon": self.carbon.get_monthly_report(),
            "goals": self.goals.get_active_goals(),
            "suggestions": self.carbon.get_suggestions(),
            "achievements": {
                "levels": len(self.achievements.LEVELS),
                "badges": len(self.achievements.BADGES),
            },
        }


# 全局实例
_tracker: Optional[BehaviorTracker] = None


def get_tracker() -> BehaviorTracker:
    """获取全局追踪器实例"""
    global _tracker
    if _tracker is None:
        _tracker = BehaviorTracker()
    return _tracker
