"""
M1-T3: 低碳行为排行榜 + 宠物 PK 对战
战力公式: 累计碳减排 kg × 0.6 + 连续天数 × 5 + 宠物综合等级 × 3
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple

from .constants import _get_conn

logger = logging.getLogger("pet.ranking")

# 战力公式权重
WEIGHT_CO2 = 0.6
WEIGHT_STREAK = 5.0
WEIGHT_PET_LEVEL = 3.0

# 段位划分
TIER_THRESHOLDS = [
    (0,    "青铜", "bronze"),
    (100,  "白银", "silver"),
    (300,  "黄金", "gold"),
    (700,  "铂金", "platinum"),
    (1500, "钻石", "diamond"),
    (3000, "大师", "master"),
    (6000, "宗师", "grandmaster"),
]

# 段位奖励
TIER_REWARDS = {
    "bronze":      {"coins": 0, "fragments": 0},
    "silver":      {"coins": 50, "fragments": 5},
    "gold":        {"coins": 100, "fragments": 10},
    "platinum":    {"coins": 200, "fragments": 20, "appearance": "pk_platinum_crown"},
    "diamond":     {"coins": 400, "fragments": 40, "appearance": "pk_diamond_aura"},
    "master":      {"coins": 800, "fragments": 80, "appearance": "pk_master_robe"},
    "grandmaster": {"coins": 1500, "fragments": 200, "appearance": "pk_grandmaster_wings"},
}


def init_ranking_schema() -> None:
    conn = _get_conn()
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS user_power (
            user_id TEXT PRIMARY KEY,
            co2_total REAL DEFAULT 0,
            streak_days INTEGER DEFAULT 0,
            pet_level INTEGER DEFAULT 1,
            power REAL DEFAULT 0,
            tier TEXT DEFAULT 'bronze',
            last_calc_at TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS pk_battles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            challenger_id TEXT,
            opponent_id TEXT,
            winner_id TEXT,
            challenger_power REAL,
            opponent_power REAL,
            season TEXT,
            battle_at TEXT DEFAULT CURRENT_TIMESTAMP,
            rewards_json TEXT
        );

        CREATE TABLE IF NOT EXISTS friendships (
            user_id TEXT,
            friend_id TEXT,
            added_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, friend_id)
        );
        """)
        conn.commit()
    finally:
        conn.close()


init_ranking_schema()


def compute_power(co2_total: float, streak_days: int, pet_level: int) -> float:
    """M1-T3: 战力计算(供主调用)"""
    return co2_total * WEIGHT_CO2 + streak_days * WEIGHT_STREAK + pet_level * WEIGHT_PET_LEVEL


def get_tier(power: float) -> Tuple[str, str]:
    """根据战力返 (中文名, ID)"""
    name = "青铜"
    tid = "bronze"
    for threshold, n, t in TIER_THRESHOLDS:
        if power >= threshold:
            name = n
            tid = t
    return name, tid


class RankingSystem:
    """M1-T3: 排行榜 + PK 系统"""

    def __init__(self):
        self._conn = _get_conn()

    def recompute_user_power(self, user_id: str, co2_total: float, streak_days: int, pet_level: int) -> Dict[str, Any]:
        """重算并存储用户战力"""
        power = compute_power(co2_total, streak_days, pet_level)
        tier_name, tier_id = get_tier(power)
        self._conn.execute("""
        INSERT OR REPLACE INTO user_power
        (user_id, co2_total, streak_days, pet_level, power, tier, last_calc_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (user_id, co2_total, streak_days, pet_level, power, tier_id, time.strftime("%Y-%m-%d %H:%M:%S")))
        self._conn.commit()
        return {"user_id": user_id, "power": power, "tier_name": tier_name, "tier_id": tier_id}

    def get_user_power(self, user_id: str) -> Optional[Dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT co2_total, streak_days, pet_level, power, tier, last_calc_at "
            "FROM user_power WHERE user_id=?",
            (user_id,)
        )
        row = cur.fetchone()
        if not row:
            return None
        power = row[3]
        return {
            "user_id": user_id,
            "co2_total": row[0],
            "streak_days": row[1],
            "pet_level": row[2],
            "power": power,
            "tier_id": row[4],
            "tier_name": dict([(t, n) for th, n, t in TIER_THRESHOLDS]).get(row[4], "青铜"),
            "last_calc_at": row[5],
        }

    def get_leaderboard(self, period: str = "all", top: int = 20) -> List[Dict[str, Any]]:
        """排行榜:period=day/week/month/all"""
        if period == "all":
            order_by = "power DESC"
            cur = self._conn.execute(
                f"SELECT user_id, power, tier, co2_total, streak_days, pet_level "
                f"FROM user_power ORDER BY {order_by} LIMIT ?",
                (top,)
            )
        else:
            # 简化:用月周期 = 当前月的累计
            ym = time.strftime("%Y-%m")
            cur = self._conn.execute(
                "SELECT user_id, power, tier, co2_total, streak_days, pet_level "
                "FROM user_power ORDER BY power DESC LIMIT ?",
                (top,)
            )
        rows = cur.fetchall()
        result = []
        for i, r in enumerate(rows, 1):
            result.append({
                "rank": i,
                "user_id": r[0],
                "power": r[1],
                "tier": r[2],
                "co2_total": r[3],
                "streak_days": r[4],
                "pet_level": r[5],
            })
        return result

    def pk_battle(self, challenger_id: str, opponent_id: str) -> Dict[str, Any]:
        """M1-T3: PK 对战 — 高战力胜,记录战报"""
        ch = self.get_user_power(challenger_id) or self.recompute_user_power(
            challenger_id, 0, 0, 1
        )
        op = self.get_user_power(opponent_id) or self.recompute_user_power(
            opponent_id, 0, 0, 1
        )
        ch_power = ch["power"]
        op_power = op["power"]
        winner = challenger_id if ch_power >= op_power else opponent_id
        rewards = {}
        if winner == challenger_id:
            # 挑战者胜:小额奖励
            rewards = {"coins": 20, "fragments": 1}
        else:
            # 对手胜:挑战者安慰
            rewards = {"coins": 5, "fragments": 0}
        # 写战报
        self._conn.execute("""
        INSERT INTO pk_battles
        (challenger_id, opponent_id, winner_id, challenger_power, opponent_power, season, rewards_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (challenger_id, opponent_id, winner, ch_power, op_power,
              time.strftime("%Y-%m"), str(rewards)))
        self._conn.commit()
        # 发奖
        if rewards.get("coins", 0) > 0:
            try:
                from .pet_engine import get_pet_engine
                pe = get_pet_engine()
                state = pe.get_state(winner)
                state.coins += rewards.get("coins", 0)
                state.fragments += rewards.get("fragments", 0)
                pe._save_state(state)
            except Exception as e:
                _logger.debug("[ranking] 发奖失败: %s", e)
        return {
            "winner": winner,
            "challenger_power": ch_power,
            "opponent_power": op_power,
            "rewards": rewards,
        }

    def add_friend(self, user_id: str, friend_id: str) -> bool:
        """M1-T3: 加好友(双向)"""
        if user_id == friend_id:
            return False
        try:
            self._conn.execute(
                "INSERT OR IGNORE INTO friendships (user_id, friend_id) VALUES (?, ?)",
                (user_id, friend_id)
            )
            self._conn.execute(
                "INSERT OR IGNORE INTO friendships (user_id, friend_id) VALUES (?, ?)",
                (friend_id, user_id)
            )
            self._conn.commit()
            return True
        except Exception:
            return False

    def list_friends(self, user_id: str) -> List[str]:
        cur = self._conn.execute(
            "SELECT friend_id FROM friendships WHERE user_id=?",
            (user_id,)
        )
        return [r[0] for r in cur.fetchall()]

    def generate_comparison_report(self, user_id: str, friend_id: str) -> Dict[str, Any]:
        """M1-T3: PK 后生成用户低碳能力对比报告"""
        u = self.get_user_power(user_id) or {}
        f = self.get_user_power(friend_id) or {}
        if not u or not f:
            return {"error": "用户数据缺失"}
        # 反向输出个性化建议
        suggestions = []
        diff_co2 = f.get("co2_total", 0) - u.get("co2_total", 0)
        diff_streak = f.get("streak_days", 0) - u.get("streak_days", 0)
        diff_pet = f.get("pet_level", 0) - u.get("pet_level", 0)
        if diff_co2 > 50:
            suggestions.append(f"对方比你多减排 {diff_co2:.0f} kg,建议加强日常节电/回收")
        if diff_streak > 7:
            suggestions.append(f"对方连续打卡 {diff_streak} 天,建议保持连续性")
        if diff_pet > 5:
            suggestions.append(f"对方宠物高 {diff_pet} 级,建议多投喂+互动")
        if not suggestions:
            suggestions.append("你已全面领先,继续保持!💚")
        return {
            "user": u,
            "friend": f,
            "power_diff": f.get("power", 0) - u.get("power", 0),
            "suggestions": suggestions,
        }


_ranking: Optional[RankingSystem] = None


def get_ranking_system() -> RankingSystem:
    global _ranking
    if _ranking is None:
        _ranking = RankingSystem()
    return _ranking
