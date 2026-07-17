"""
目标提醒系统
设置和管理减排目标，追踪进度，自动提醒
"""

from typing import Dict, List
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class CarbonGoal:
    """碳减排目标"""

    goal_id: str
    title: str
    target_value: float  # 目标值 (kg CO2)
    current_value: float  # 当前值
    period: str  # weekly / monthly
    category: str  # 出行/用电/饮食/综合
    start_date: str
    end_date: str
    completed: bool = False


class GoalReminderSystem:
    """
    目标提醒系统

    支持设置周/月减排目标，自动追踪进度，
    发送提醒通知
    """

    # 目标类型模板
    GOAL_TEMPLATES = {
        "周减排5kg": {
            "target_value": 5.0,
            "period": "weekly",
            "category": "comprehensive",
            "description": "每周减少5kg CO2排放",
        },
        "周减排10kg": {
            "target_value": 10.0,
            "period": "weekly",
            "category": "comprehensive",
            "description": "每周减少10kg CO2排放",
        },
        "月减排20kg": {
            "target_value": 20.0,
            "period": "monthly",
            "category": "comprehensive",
            "description": "每月减少20kg CO2排放",
        },
        "周绿色出行3天": {
            "target_value": 3.0,
            "period": "weekly",
            "category": "travel",
            "description": "每周公交/步行3天",
        },
        "月素食8天": {
            "target_value": 8.0,
            "period": "monthly",
            "category": "diet",
            "description": "每月8天素食",
        },
        "周省电10度": {
            "target_value": 10.0,
            "period": "weekly",
            "category": "electricity",
            "description": "每周节省10度电",
        },
    }

    # 提醒阈值
    REMINDER_THRESHOLDS = {
        "progress": 0.5,  # 进度50%时提醒
        "deadline": 0.8,  # 截止前20%时提醒
        "overdue": 1.0,  # 逾期时提醒
    }

    def __init__(self):
        self.goals: Dict[str, CarbonGoal] = {}
        self.completed_history: List[Dict] = []

    def create_goal(
        self,
        title: str,
        target_value: float = None,
        period: str = "weekly",
        category: str = "comprehensive",
        start_date: str = None,
        end_date: str = None,
    ) -> CarbonGoal:
        """创建目标"""
        import uuid

        goal_id = str(uuid.uuid4())[:8]

        # 使用模板默认值
        if target_value is None and title in self.GOAL_TEMPLATES:
            template = self.GOAL_TEMPLATES[title]
            target_value = template["target_value"]
            period = template.get("period", period)
            category = template.get("category", category)

        if start_date is None:
            start_date = datetime.now().strftime("%Y-%m-%d")

        if end_date is None:
            if period == "weekly":
                end_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
            else:
                end_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")

        goal = CarbonGoal(
            goal_id=goal_id,
            title=title,
            target_value=target_value or 10.0,
            current_value=0.0,
            period=period,
            category=category,
            start_date=start_date,
            end_date=end_date,
            completed=False,
        )

        self.goals[goal_id] = goal
        return goal

    def update_progress(self, goal_id: str, value: float) -> Dict:
        """更新目标进度"""
        if goal_id not in self.goals:
            return {"error": "目标不存在"}

        goal = self.goals[goal_id]
        goal.current_value = value

        # 检查是否完成
        if value >= goal.target_value:
            goal.completed = True
            self.completed_history.append(
                {
                    "goal_id": goal_id,
                    "title": goal.title,
                    "target": goal.target_value,
                    "achieved": value,
                    "completed_date": datetime.now().strftime("%Y-%m-%d"),
                    "period": goal.period,
                }
            )

        return self.get_goal_status(goal_id)

    def add_reduction(self, goal_id: str, reduction: float) -> Dict:
        """增加减排量"""
        if goal_id not in self.goals:
            return {"error": "目标不存在"}

        goal = self.goals[goal_id]
        goal.current_value += reduction

        # 检查是否完成
        if goal.current_value >= goal.target_value and not goal.completed:
            goal.completed = True
            self.completed_history.append(
                {
                    "goal_id": goal_id,
                    "title": goal.title,
                    "target": goal.target_value,
                    "achieved": goal.current_value,
                    "completed_date": datetime.now().strftime("%Y-%m-%d"),
                    "period": goal.period,
                }
            )

        return self.get_goal_status(goal_id)

    def get_goal_status(self, goal_id: str) -> Dict:
        """获取目标状态"""
        if goal_id not in self.goals:
            return {"error": "目标不存在"}

        goal = self.goals[goal_id]
        progress = (
            min(goal.current_value / goal.target_value * 100, 100) if goal.target_value > 0 else 0
        )

        # 计算剩余天数
        end_dt = datetime.strptime(goal.end_date, "%Y-%m-%d")
        remaining_days = (end_dt - datetime.now()).days

        return {
            "goal_id": goal_id,
            "title": goal.title,
            "target": goal.target_value,
            "current": round(goal.current_value, 2),
            "progress": f"{progress:.1f}%",
            "remaining_days": remaining_days,
            "completed": goal.completed,
            "status": "completed"
            if goal.completed
            else ("on_track" if progress > 50 else "needs_effort"),
        }

    def get_all_goals(self) -> List[Dict]:
        """获取所有目标"""
        return [self.get_goal_status(gid) for gid in self.goals]

    def get_active_goals(self) -> List[Dict]:
        """获取进行中的目标"""
        return [s for s in self.get_all_goals() if not s.get("completed")]

    def check_reminders(self) -> List[Dict]:
        """检查需要提醒的目标"""
        reminders = []

        for goal_id, goal in self.goals.items():
            if goal.completed:
                continue

            progress = goal.current_value / goal.target_value if goal.target_value > 0 else 0
            end_dt = datetime.strptime(goal.end_date, "%Y-%m-%d")
            remaining_days = (end_dt - datetime.now()).days

            # 进度50%提醒
            if progress >= 0.5 and progress < 0.8:
                reminders.append(
                    {
                        "type": "progress",
                        "goal_id": goal_id,
                        "title": goal.title,
                        "message": f"目标已完成{progress * 100:.0f}%，继续加油！",
                        "priority": "medium",
                    }
                )

            # 截止前提醒
            if remaining_days <= 3 and remaining_days > 0:
                reminders.append(
                    {
                        "type": "deadline",
                        "goal_id": goal_id,
                        "title": goal.title,
                        "message": f"目标还有{remaining_days}天到期，当前进度{progress * 100:.0f}%",
                        "priority": "high",
                    }
                )

            # 逾期提醒
            if remaining_days < 0:
                reminders.append(
                    {
                        "type": "overdue",
                        "goal_id": goal_id,
                        "title": goal.title,
                        "message": f"目标已逾期，当前进度{progress * 100:.0f}%",
                        "priority": "high",
                    }
                )

        return reminders

    def get_statistics(self) -> Dict:
        """获取目标统计"""
        active = self.get_active_goals()
        completed_total = len(self.completed_history)

        # 计算总目标完成率
        total_target = sum(g.target_value for g in self.goals.values())
        total_achieved = sum(g.current_value for g in self.goals.values())
        overall_rate = total_achieved / total_target * 100 if total_target > 0 else 0

        return {
            "总目标数": len(self.goals),
            "进行中": len(active),
            "已完成": completed_total,
            "总目标值_kg": total_target,
            "总达成_kg": round(total_achieved, 2),
            "完成率": f"{overall_rate:.1f}%",
            "本周新增": len([g for g in self.goals.values() if g.period == "weekly"]),
        }

    @classmethod
    def get_available_templates(cls) -> Dict[str, str]:
        """获取目标模板"""
        return {k: v["description"] for k, v in cls.GOAL_TEMPLATES.items()}
