"""
M1-T2: 季节限定宠物 + 限时任务 + 过期规则
低耦合:独立模块,PetEngine 任务时调用 current_season() 获取当前季节加成
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Optional, Any

from .constants import _get_conn

_logger = logging.getLogger("pet.seasonal")


# 4 季节定义(北半球)
SEASON_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "spring": {  # 3-5
        "months": [3, 4, 5],
        "name": "春",
        "limited_pet": "春芽使者·花",
        "limited_appearance": "spring_bloom",
        "limited_habitat": "spring_meadow",
        "task": {
            "task_id": "spring_plant",
            "title": "春季植树·绿植养护",
            "description": "本月内植树 ≥ 3 棵,兑换春季限定皮肤",
            "behavior": "plant",
            "count": 3,
            "reward": {"fragments": 50, "appearance": "spring_bloom", "coins": 100},
        },
    },
    "summer": {  # 6-8
        "months": [6, 7, 8],
        "name": "夏",
        "limited_pet": "盛夏精灵·阳",
        "limited_appearance": "summer_sun",
        "limited_habitat": "summer_oasis",
        "task": {
            "task_id": "summer_ac",
            "title": "夏季节电·空调降碳",
            "description": "本月内节电 ≥ 100 kWh,兑换夏季限定皮肤",
            "behavior": "electricity",
            "count": 100,
            "reward": {"fragments": 50, "appearance": "summer_sun", "coins": 100},
        },
    },
    "autumn": {  # 9-11
        "months": [9, 10, 11],
        "name": "秋",
        "limited_pet": "金秋使者·叶",
        "limited_appearance": "autumn_leaves",
        "limited_habitat": "autumn_grove",
        "task": {
            "task_id": "autumn_recycle",
            "title": "金秋回收·落叶归仓",
            "description": "本月内回收 ≥ 30 kg,兑换秋季限定皮肤",
            "behavior": "recycle",
            "count": 30,
            "reward": {"fragments": 50, "appearance": "autumn_leaves", "coins": 100},
        },
    },
    "winter": {  # 12-2
        "months": [12, 1, 2],
        "name": "冬",
        "limited_pet": "冬日守护·雪",
        "limited_appearance": "winter_frost",
        "limited_habitat": "winter_cabin",
        "task": {
            "task_id": "winter_warm",
            "title": "冬季采暖降碳",
            "description": "本月内节电 ≥ 80 kWh(采暖节能),兑换冬季限定皮肤",
            "behavior": "electricity",
            "count": 80,
            "reward": {"fragments": 50, "appearance": "winter_frost", "coins": 100},
        },
    },
}

# 季节兑换回收比例(过期道具按原值 50% 回收为精灵币)
EXPIRED_RECOVERY_RATIO = 0.5


def current_season(today: Optional[date] = None) -> str:
    """根据日期返回当前季节(春/夏/秋/冬)"""
    today = today or date.today()
    m = today.month
    for sid, defn in SEASON_DEFINITIONS.items():
        if m in defn["months"]:
            return sid
    return "spring"  # 兜底


def current_season_def(today: Optional[date] = None) -> Dict[str, Any]:
    return SEASON_DEFINITIONS[current_season(today)]


def init_season_schema() -> None:
    """M1-T2: 2 张表(不动原 7 + 3 多品种表)"""
    conn = _get_conn()
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS user_season_progress (
            user_id TEXT,
            season TEXT,
            year INTEGER,
            task_id TEXT,
            progress REAL DEFAULT 0,
            completed_at TEXT,
            reward_claimed BOOLEAN DEFAULT FALSE,
            expired BOOLEAN DEFAULT FALSE,
            PRIMARY KEY (user_id, season, year, task_id)
        );

        CREATE TABLE IF NOT EXISTS seasonal_inventory (
            user_id TEXT,
            item_id TEXT,
            season TEXT,
            year INTEGER,
            obtained_at TEXT DEFAULT CURRENT_TIMESTAMP,
            expired BOOLEAN DEFAULT FALSE,
            recovered BOOLEAN DEFAULT FALSE,
            PRIMARY KEY (user_id, item_id, season, year)
        );
        """)
        conn.commit()
    finally:
        conn.close()


init_season_schema()


class SeasonalManager:
    """M1-T2: 季节活动管理器"""

    def __init__(self):
        self._conn = _get_conn()

    def get_current_season_info(self, today: Optional[date] = None) -> Dict[str, Any]:
        """返回当前季节完整配置(供前端展示)"""
        sid = current_season(today)
        defn = SEASON_DEFINITIONS[sid]
        return {
            "season": sid,
            "name": defn["name"],
            "limited_pet": defn["limited_pet"],
            "limited_appearance": defn["limited_appearance"],
            "limited_habitat": defn["limited_habitat"],
            "task": defn["task"],
            "expires_at": self._season_end_date(today).isoformat(),
        }

    def _season_end_date(self, today: Optional[date] = None) -> date:
        today = today or date.today()
        sid = current_season(today)
        defn = SEASON_DEFINITIONS[sid]
        last_month = max(defn["months"])
        if last_month == 12:
            # 冬:12-2,结束是 2/28
            from calendar import monthrange
            return date(today.year if today.month <= 2 else today.year, 2, 28)
        # 其他季节:结束是最后月最后日
        from calendar import monthrange
        return date(today.year, last_month, monthrange(today.year, last_month)[1])

    def record_progress(self, user_id: str, behavior_type: str, amount: float, today: Optional[date] = None) -> Optional[Dict[str, Any]]:
        """M1-T2: 录入行为时,推进当季任务进度

        Returns: 任务完成信息(若刚完成)或 None
        """
        today = today or date.today()
        sid = current_season(today)
        defn = SEASON_DEFINITIONS[sid]
        task = defn["task"]
        if task["behavior"] != behavior_type:
            return None
        # 累加进度
        cur = self._conn.execute(
            "SELECT progress FROM user_season_progress WHERE user_id=? AND season=? AND year=? AND task_id=?",
            (user_id, sid, today.year, task["task_id"])
        )
        row = cur.fetchone()
        new_progress = (row[0] if row else 0) + amount
        if row:
            self._conn.execute(
                "UPDATE user_season_progress SET progress=? WHERE user_id=? AND season=? AND year=? AND task_id=?",
                (new_progress, user_id, sid, today.year, task["task_id"])
            )
        else:
            self._conn.execute(
                "INSERT INTO user_season_progress (user_id, season, year, task_id, progress) VALUES (?, ?, ?, ?, ?)",
                (user_id, sid, today.year, task["task_id"], new_progress)
            )
        self._conn.commit()

        # 刚完成?
        if new_progress >= task["count"]:
            self._conn.execute(
                "UPDATE user_season_progress SET completed_at=? WHERE user_id=? AND season=? AND year=? AND task_id=?",
                (time.strftime("%Y-%m-%d %H:%M:%S"), user_id, sid, today.year, task["task_id"])
            )
            self._conn.commit()
            return {"task_id": task["task_id"], "season": sid, "year": today.year, "reward": task["reward"]}
        return None

    def claim_reward(self, user_id: str, task_id: str, season: str, year: int) -> Optional[Dict[str, Any]]:
        """领取奖励"""
        cur = self._conn.execute(
            "SELECT reward_claimed, completed_at, expired FROM user_season_progress "
            "WHERE user_id=? AND season=? AND year=? AND task_id=?",
            (user_id, season, year, task_id)
        )
        row = cur.fetchone()
        if not row or not row[1] or row[0] or row[2]:
            return None  # 未完成 / 已领 / 过期
        defn = SEASON_DEFINITIONS[season]
        reward = defn["task"]["reward"]
        # 落库 seasonal_inventory
        self._conn.execute(
            "INSERT INTO seasonal_inventory (user_id, item_id, season, year) VALUES (?, ?, ?, ?)",
            (user_id, reward.get("appearance", task_id), season, year)
        )
        # 标记已领
        self._conn.execute(
            "UPDATE user_season_progress SET reward_claimed=TRUE WHERE user_id=? AND season=? AND year=? AND task_id=?",
            (user_id, season, year, task_id)
        )
        self._conn.commit()
        return reward

    def get_user_season_status(self, user_id: str) -> Dict[str, Any]:
        """查用户当季状态(进度+历史)"""
        sid = current_season()
        cur = self._conn.execute(
            "SELECT task_id, progress, completed_at, reward_claimed FROM user_season_progress "
            "WHERE user_id=? AND season=? AND year=?",
            (user_id, sid, date.today().year)
        )
        rows = cur.fetchall()
        progress = {r[0]: {"progress": r[1], "completed": bool(r[2]), "claimed": bool(r[3])}
                   for r in rows}
        return {
            "current_season": sid,
            "current_task": SEASON_DEFINITIONS[sid]["task"],
            "progress": progress,
        }

    def expire_old_season_items(self, user_id: str, today: Optional[date] = None) -> int:
        """M1-T2: 过期回收逻辑 — 把未领取的过期任务标记 expired,自动按比例回收"""
        from datetime import date as _date
        today = today or _date.today()
        cur = self._conn.execute(
            "SELECT season, year FROM user_season_progress WHERE user_id=? AND reward_claimed=FALSE",
            (user_id,)
        )
        rows = cur.fetchall()
        recovered_coins = 0
        for season, year in rows:
            # 判断是否过期
            season_year = year
            last_month = max(SEASON_DEFINITIONS[season]["months"])
            if last_month == 12 and today.month <= 2:
                season_year = year if today.month <= 2 else year - 1
            expired_at = _date(season_year, last_month, 28) if last_month != 12 else _date(season_year, 12, 31)
            if today > expired_at:
                # 过期,按 50% 回收为精灵币
                reward_coins = SEASON_DEFINITIONS[season]["task"]["reward"].get("coins", 0)
                recovered = int(reward_coins * EXPIRED_RECOVERY_RATIO)
                recovered_coins += recovered
                # 标记过期
                self._conn.execute(
                    "UPDATE user_season_progress SET expired=TRUE WHERE user_id=? AND season=? AND year=?",
                    (user_id, season, year)
                )
                self._conn.execute(
                    "UPDATE seasonal_inventory SET expired=TRUE, recovered=TRUE WHERE user_id=? AND season=? AND year=?",
                    (user_id, season, year)
                )
                self._conn.commit()
        # 回收币
        if recovered_coins > 0:
            try:
                from .pet_engine import get_pet_engine
                pe = get_pet_engine()
                state = pe.get_state(user_id)
                state.coins += recovered_coins
                pe._save_state(state)
            except Exception as e:
                _logger.debug("[seasonal] 回收币失败: %s", e)
        return recovered_coins


_smgr: Optional[SeasonalManager] = None


def get_seasonal_manager() -> SeasonalManager:
    global _smgr
    if _smgr is None:
        _smgr = SeasonalManager()
    return _smgr
