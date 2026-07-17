"""
成就积分系统
积分获取、徽章奖励、里程碑系统
"""

from typing import Dict, Optional, List
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Achievement:
    """成就"""

    badge_id: str
    name: str
    description: str
    category: str  # travel/diet/electricity/consumption/comprehensive
    requirement: Dict  # 达成条件
    points: int  # 积分奖励
    icon: str  # 徽章图标
    earned: bool = False
    earned_date: str = None


@dataclass
class UserPoints:
    """用户积分"""

    user_id: str
    total_points: int = 0
    level: int = 1
    points_history: List[Dict] = field(default_factory=list)
    badges: List[str] = field(default_factory=list)


class AchievementSystem:
    """
    成就积分系统

    - 积分累计：每种低碳行为获得对应积分
    - 徽章解锁：达成条件自动解锁
    - 等级系统：积分达到阈值升级
    - 里程碑奖励：阶段性奖励
    """

    # 积分规则 (每次行为)
    POINTS_RULES = {
        # 出行
        "公共交通1次": 10,
        "步行/骑行1次": 15,
        "拼车1次": 8,
        "新能源汽车": 50,
        # 饮食
        "素食1天": 20,
        "自带餐具": 5,
        "光盘行动": 5,
        # 用电
        "随手关灯": 3,
        "空调调高1度": 5,
        "省电1度": 2,
        # 消费
        "自带购物袋": 3,
        "双面打印": 2,
        "购买二手": 10,
        "选择环保产品": 15,
        # 其他
        "分享低碳经验": 20,
        "参与低碳活动": 30,
        "邀请好友": 50,
    }

    # 徽章定义
    BADGES = [
        {
            "badge_id": "first_step",
            "name": "初次行动",
            "description": "完成第1次低碳行为",
            "category": "comprehensive",
            "requirement": {"action_count": 1},
            "points": 10,
            "icon": "🌱",
        },
        {
            "badge_id": "week_streak",
            "name": "一周坚持",
            "description": "连续7天记录低碳行为",
            "category": "comprehensive",
            "requirement": {"streak_days": 7},
            "points": 100,
            "icon": "🌿",
        },
        {
            "badge_id": "month_streak",
            "name": "一月坚持",
            "description": "连续30天记录低碳行为",
            "category": "comprehensive",
            "requirement": {"streak_days": 30},
            "points": 300,
            "icon": "🌳",
        },
        {
            "badge_id": "green_traveler",
            "name": "绿色出行者",
            "description": "累计公共交通/步行/骑行20次",
            "category": "travel",
            "requirement": {"travel_count": 20},
            "points": 150,
            "icon": "🚌",
        },
        {
            "badge_id": "eco_driver",
            "name": "环保车主",
            "description": "选择新能源汽车或拼车10次",
            "category": "travel",
            "requirement": {"carpool_count": 10},
            "points": 100,
            "icon": "🚗",
        },
        {
            "badge_id": "vegetarian_week",
            "name": "素食一周",
            "description": "一周内素食5天",
            "category": "diet",
            "requirement": {"vegetarian_days": 5, "period_days": 7},
            "points": 80,
            "icon": "🥗",
        },
        {
            "badge_id": "energy_saver",
            "name": "省电达人",
            "description": "累计省电50度",
            "category": "electricity",
            "requirement": {"save_kwh": 50},
            "points": 120,
            "icon": "💡",
        },
        {
            "badge_id": "zero_bag",
            "name": "环保先锋",
            "description": "自带购物袋30次",
            "category": "consumption",
            "requirement": {"bag_count": 30},
            "points": 80,
            "icon": "🛍️",
        },
        {
            "badge_id": "carbon_hero",
            "name": "减碳英雄",
            "description": "累计减排100kg CO2",
            "category": "comprehensive",
            "requirement": {"total_reduction_kg": 100},
            "points": 500,
            "icon": "🏆",
        },
        {
            "badge_id": "level_5",
            "name": "低碳达人",
            "description": "达到5级",
            "category": "level",
            "requirement": {"level": 5},
            "points": 0,
            "icon": "⭐",
        },
    ]

    # 等级配置
    LEVELS = [
        {"level": 1, "name": "低碳新人", "min_points": 0},
        {"level": 2, "name": "低碳行者", "min_points": 100},
        {"level": 3, "name": "低碳达人", "min_points": 300},
        {"level": 4, "name": "低碳先锋", "min_points": 600},
        {"level": 5, "name": "低碳专家", "min_points": 1000},
        {"level": 6, "name": "环保卫士", "min_points": 2000},
        {"level": 7, "name": "减碳英雄", "min_points": 5000},
        {"level": 8, "name": "绿色大使", "min_points": 10000},
        {"level": 9, "name": "地球卫士", "min_points": 20000},
        {"level": 10, "name": "环保传奇", "min_points": 50000},
    ]

    # 里程碑奖励
    MILESTONES = {
        100: {"reward": "新皮肤", "description": "解锁成就徽章样式"},
        500: {"reward": "称号", "description": "获得'低碳达人'称号"},
        1000: {"reward": "徽章", "description": "解锁专属徽章"},
    }

    def __init__(self):
        self.user_data: Dict[str, UserPoints] = {}
        self.action_history: Dict[str, List[Dict]] = {}  # user_id -> actions
        self.streaks: Dict[str, int] = {}  # user_id -> 连续天数

    def earn_points(self, user_id: str, action: str, value: float = 1.0) -> Dict:
        """获得积分"""
        points = self.POINTS_RULES.get(action, 5) * int(value)

        if user_id not in self.user_data:
            self.user_data[user_id] = UserPoints(user_id=user_id)

        user = self.user_data[user_id]
        user.total_points += points
        user.points_history.append(
            {"action": action, "points": points, "date": datetime.now().strftime("%Y-%m-%d")}
        )

        # 检查升级
        old_level = user.level
        user.level = self._calculate_level(user.total_points)

        # 记录行为用于徽章检查
        if user_id not in self.action_history:
            self.action_history[user_id] = []
        self.action_history[user_id].append(
            {"action": action, "value": value, "date": datetime.now().strftime("%Y-%m-%d")}
        )

        # 检查徽章
        new_badges = self._check_badges(user_id)
        user.badges.extend(new_badges)

        result = {
            "action": action,
            "points_earned": points,
            "total_points": user.total_points,
            "level": user.level,
            "level_up": user.level > old_level,
            "new_badges": new_badges,
        }

        # 检查里程碑
        milestone = self._check_milestone(user.total_points)
        if milestone:
            result["milestone"] = milestone

        return result

    def _calculate_level(self, points: int) -> int:
        """计算等级"""
        for level_info in reversed(self.LEVELS):
            if points >= level_info["min_points"]:
                return level_info["level"]
        return 1

    def _check_badges(self, user_id: str) -> List[str]:
        """检查徽章解锁"""
        if user_id not in self.action_history:
            return []

        user = self.user_data.get(user_id)
        if not user:
            return []

        new_badges = []
        actions = self.action_history[user_id]

        for badge in self.BADGES:
            if badge["badge_id"] in user.badges:
                continue

            req = badge["requirement"]

            # 检查各项条件
            if "action_count" in req:
                if len(actions) >= req["action_count"]:
                    new_badges.append(badge["badge_id"])

            elif "travel_count" in req:
                travel_actions = [
                    a for a in actions if a["action"] in ["公共交通1次", "步行/骑行1次", "拼车1次"]
                ]
                if len(travel_actions) >= req["travel_count"]:
                    new_badges.append(badge["badge_id"])

            elif "bag_count" in req:
                bag_actions = [a for a in actions if a["action"] == "自带购物袋"]
                if len(bag_actions) >= req["bag_count"]:
                    new_badges.append(badge["badge_id"])

        return new_badges

    def _check_milestones(self, total_points: int) -> Optional[Dict]:
        """检查里程碑"""
        for threshold, milestone in self.MILESTONES.items():
            if total_points >= threshold:
                continue
            if total_points >= threshold:
                return milestone
        return None

    def get_user_profile(self, user_id: str) -> Dict:
        """获取用户成就档案"""
        if user_id not in self.user_data:
            return {"error": "用户无数据"}

        user = self.user_data[user_id]

        # 等级信息
        level_info = (
            self.LEVELS[user.level - 1] if user.level <= len(self.LEVELS) else self.LEVELS[-1]
        )
        next_level = self.LEVELS[user.level] if user.level < len(self.LEVELS) else None

        points_to_next = 0
        if next_level:
            points_to_next = next_level["min_points"] - user.total_points

        return {
            "user_id": user_id,
            "total_points": user.total_points,
            "level": user.level,
            "level_name": level_info["name"],
            "points_to_next": points_to_next,
            "badges_count": len(user.badges),
            "badges": user.badges,
            "next_badge": self._get_next_badge(user.badges),
        }

    def _get_next_badge(self, earned_badges: List[str]) -> Optional[Dict]:
        """获取下一个可解锁徽章"""
        for badge in self.BADGES:
            if badge["badge_id"] not in earned_badges:
                return badge
        return None

    def get_leaderboard(self, limit: int = 10) -> List[Dict]:
        """排行榜"""
        sorted_users = sorted(self.user_data.values(), key=lambda u: u.total_points, reverse=True)[
            :limit
        ]

        return [
            {
                "rank": i + 1,
                "user_id": u.user_id[:8] + "***",
                "total_points": u.total_points,
                "level": u.level,
                "level_name": self.LEVELS[u.level - 1]["name"],
            }
            for i, u in enumerate(sorted_users)
        ]

    @classmethod
    def get_points_rules(cls) -> Dict[str, int]:
        """获取积分规则"""
        return cls.POINTS_RULES

    @classmethod
    def get_all_badges(cls) -> List[Dict]:
        """获取所有徽章"""
        return [{"id": b["badge_id"], "name": b["name"], "icon": b["icon"]} for b in cls.BADGES]
