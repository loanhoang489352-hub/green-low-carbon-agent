"""
任务6: 宠物养成 - 数值计算层
核心 PetEngine: 行为奖励 + 升级 + 形态/栖息地/图鉴/成就联动
低耦合:不修改 carbon_footprint / RAG / LLM,只 import 现有函数。
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional, Any

from .constants import _get_conn, init_pet_schema
from .numeric_rules import (
    BEHAVIOR_REWARDS,
    DAILY_CAPS,
    exp_to_next_level,
    APPEARANCE_TIERS,
    HABITAT_UNLOCKS,
    CODEX_THRESHOLDS,
    BEHAVIOR_TO_CODEX,
    ACHIEVEMENTS,
    SKILL_UNLOCK,
    compute_pet_status,
)

_logger = logging.getLogger("pet.engine")


@dataclass
class PetState:
    """宠物当前状态"""

    user_id: str
    level: int = 1
    exp: int = 0
    hunger: int = 50
    mood: int = 50
    vitality: int = 50
    coins: int = 0
    fragments: int = 0
    appearance: str = "seed"
    habitat: str = "green_house"
    total_co2_saved: float = 0.0
    consecutive_days: int = 0
    last_active_date: str = ""
    last_decay_at: str = ""

    def status(self) -> str:
        return compute_pet_status(self.hunger, self.mood, self.vitality)

    def title(self) -> str:
        for t in APPEARANCE_TIERS:
            if t["id"] == self.appearance:
                return t["title"]
        return "碳种子"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status()
        d["title"] = self.title()
        d["exp_to_next"] = exp_to_next_level(self.level)
        return d


@dataclass
class PetStateChangeResult:
    """任务6: 一次行为触发的变更结果"""

    co2_saved: float
    rewards: Dict[str, int]
    new_state: PetState
    old_state: PetState
    level_up: bool = False
    appearance_change: Optional[str] = None
    habitat_unlock: Optional[str] = None
    achievement_unlocks: List[str] = field(default_factory=list)
    codex_unlocks: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "co2_saved": self.co2_saved,
            "rewards": self.rewards,
            "old_state": self.old_state.to_dict(),
            "new_state": self.new_state.to_dict(),
            "level_up": self.level_up,
            "appearance_change": self.appearance_change,
            "habitat_unlock": self.habitat_unlock,
            "achievement_unlocks": self.achievement_unlocks,
            "codex_unlocks": self.codex_unlocks,
        }


class PetEngine:
    """宠物养成核心引擎 — 任务6 主类"""

    def __init__(self):
        init_pet_schema()  # 幂等
        self._conn = _get_conn()

    # ===== 状态读写 =====

    def get_state(self, user_id: str) -> PetState:
        """读状态(不存在则创建初始)"""
        cur = self._conn.execute(
            "SELECT user_id, level, exp, hunger, mood, vitality, coins, fragments, "
            "appearance, habitat, total_co2_saved, consecutive_days, last_active_date, last_decay_at "
            "FROM pets WHERE user_id=?",
            (user_id,),
        )
        row = cur.fetchone()
        if row is None:
            return self._create_pet(user_id)
        return PetState(*row)

    def _create_pet(self, user_id: str) -> PetState:
        state = PetState(user_id=user_id)
        self._save_state(state)
        return state

    def _save_state(self, state: PetState) -> None:
        self._conn.execute(
            """
        INSERT OR REPLACE INTO pets
        (user_id, level, exp, hunger, mood, vitality, coins, fragments,
         appearance, habitat, total_co2_saved, consecutive_days, last_active_date, last_decay_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                state.user_id,
                state.level,
                state.exp,
                state.hunger,
                state.mood,
                state.vitality,
                state.coins,
                state.fragments,
                state.appearance,
                state.habitat,
                state.total_co2_saved,
                state.consecutive_days,
                state.last_active_date,
                state.last_decay_at,
            ),
        )
        self._conn.commit()

    # ===== 任务2: 行为奖励 =====

    def apply_behavior_rewards(
        self,
        user_id: str,
        behavior_type: str,
        amount: float,
    ) -> PetStateChangeResult:
        """任务2/6 入口:接收一条低碳行为 → 双写数据(用户碳日志 + 宠物状态)

        不修改 carbon_footprint:复用其 calculate_* 函数读减排量
        """
        old_state = self.get_state(user_id)

        # 1) 调 carbon_footprint 算减排量(原有逻辑,不动)
        co2_saved = self._compute_co2(behavior_type, amount)

        # 2) 写用户碳收益报表(原有 carbon_footprint_log 表,不动)
        self._write_carbon_log(user_id, behavior_type, amount, co2_saved)

        # 3) 计算宠物资源奖励
        rewards = dict(BEHAVIOR_REWARDS.get(behavior_type, {}))

        # 4) 应用每日上限
        rewards = self._cap_daily(user_id, rewards)

        # 5) 应用新状态
        new_state = PetState(**asdict(old_state))  # 深拷贝
        new_state.hunger = min(100, max(0, new_state.hunger + rewards.get("hunger", 0)))
        new_state.mood = min(100, max(0, new_state.mood + rewards.get("mood", 0)))
        new_state.vitality = min(100, max(0, new_state.vitality + rewards.get("vitality", 0)))
        new_state.coins += rewards.get("coins", 0)
        new_state.fragments += rewards.get("fragments", 0)
        new_state.total_co2_saved += co2_saved
        new_state.exp += rewards.get("exp", 0)
        new_state.last_active_date = time.strftime("%Y-%m-%d")

        # 6) 升级检查
        level_up = False
        while new_state.exp >= exp_to_next_level(new_state.level) and new_state.level < 50:
            needed = exp_to_next_level(new_state.level)
            new_state.exp -= needed
            new_state.level += 1
            level_up = True

        # 7) 形态变化检查
        old_appearance = new_state.appearance
        new_state.appearance = self._check_appearance(new_state.total_co2_saved, new_state.level)
        appearance_change = new_state.appearance if new_state.appearance != old_appearance else None

        # 8) 栖息地解锁
        habitat_unlock = self._check_habitat(new_state)

        # 9) 连续天数(简化为今日活跃就 +1)
        new_state.consecutive_days = self._check_consecutive(new_state)

        # 10) 保存
        self._save_state(new_state)

        # 11) 写状态变更日志
        self._log_change(user_id, behavior_type, amount, co2_saved, rewards, old_state, new_state)

        # 12) 写装扮/栖息地解锁
        if appearance_change:
            self._unlock_appearance(user_id, appearance_change)
        if habitat_unlock:
            self._unlock_habitat(user_id, habitat_unlock)

        # 13) 检查成就
        achievement_unlocks = self._check_achievements(user_id, new_state)

        # 14) 更新图鉴
        codex_unlocks = self._update_codex(user_id, behavior_type, amount)

        return PetStateChangeResult(
            co2_saved=co2_saved,
            rewards=rewards,
            new_state=new_state,
            old_state=old_state,
            level_up=level_up,
            appearance_change=appearance_change,
            habitat_unlock=habitat_unlock,
            achievement_unlocks=achievement_unlocks,
            codex_unlocks=codex_unlocks,
        )

    def _compute_co2(self, behavior_type: str, amount: float) -> float:
        """任务6: 复用 carbon_footprint,不修改"""
        try:
            from user_profile.carbon_footprint import CarbonFootprintCalculator

            cf = CarbonFootprintCalculator()
            if behavior_type in ("bus", "walk", "bike"):
                return cf.calculate_travel_emission(distance=amount, vehicle_type=behavior_type)
            elif behavior_type == "electricity":
                return cf.calculate_electricity_emission(kwh=amount)
            elif behavior_type == "water":
                # 节水按 0.344 kg/吨
                return amount * 0.344
            elif behavior_type in ("recycle", "recycle_sort"):
                return amount * (2.0 if behavior_type == "recycle" else 0.5)
            elif behavior_type == "plastic":
                return amount * 0.3
            elif behavior_type == "purchase":
                return cf.calculate_consumption_emission(category="low_carbon", cost=amount)
            elif behavior_type == "plant":
                return amount * 5.0
        except Exception as e:
            _logger.debug("[PetEngine] 复用 carbon_footprint 失败 %s: %s", behavior_type, e)
        return 0.0

    def _write_carbon_log(
        self, user_id: str, behavior_type: str, amount: float, co2_saved: float
    ) -> None:
        """写用户碳收益报表(原有表,0 改)

        record_carbon 签名: (user_id, category, amount_kg_co2e, source, metadata)
        修复: 修正 amount→amount_kg_co2e, 删除多余的 co2_saved kwarg
        """
        try:
            from user_profile.persistence import get_behavior_persistence

            pers = get_behavior_persistence()
            if hasattr(pers, "record_carbon"):
                pers.record_carbon(
                    user_id=user_id,
                    category=behavior_type,
                    amount_kg_co2e=co2_saved,  # 修正:用 co2_saved 作为 amount_kg_co2e
                    source="pet_engine",
                    metadata={"behavior_amount": amount, "via": "pet_module"},
                )
        except Exception as e:
            _logger.debug("[PetEngine] 写 carbon log 失败: %s", e)

    def _cap_daily(self, user_id: str, rewards: Dict[str, int]) -> Dict[str, int]:
        """任务2: 每日上限"""
        # 简化为:本次入参 < 上限 (实际应累计查今日总和,这里给出接口骨架)
        for k, cap in [
            ("exp", DAILY_CAPS["exp"]),
            ("coins", DAILY_CAPS["coins"]),
            ("fragments", DAILY_CAPS["fragments"]),
        ]:
            if k in rewards and rewards[k] > cap:
                rewards[k] = cap
        return rewards

    def _check_appearance(self, co2: float, level: int) -> str:
        """形态判定 — 单约束(累计 co2),等级是参考指示"""
        for t in APPEARANCE_TIERS:
            if co2 >= t["co2_min"]:
                return t["id"]
        return "seed"

    def _check_habitat(self, state: PetState) -> Optional[str]:
        for h in HABITAT_UNLOCKS:
            hid = h["id"]
            if (
                state.total_co2_saved >= h["co2_min"]
                and state.consecutive_days >= h["consec_days_min"]
            ):
                cur = self._conn.execute(
                    "SELECT 1 FROM pet_habitat_unlocks WHERE user_id=? AND habitat_id=?",
                    (state.user_id, hid),
                ).fetchone()
                if not cur:
                    return hid
        return None

    def _check_consecutive(self, state: PetState) -> int:
        """简化为:今天活跃 = 至少 +1"""
        today = time.strftime("%Y-%m-%d")
        if state.last_active_date == today:
            return max(state.consecutive_days, 1)
        return state.consecutive_days + 1

    def _unlock_appearance(self, user_id: str, appearance_id: str) -> None:
        try:
            self._conn.execute(
                "INSERT OR IGNORE INTO pet_appearance_unlocks (user_id, appearance_id) VALUES (?, ?)",
                (user_id, appearance_id),
            )
            self._conn.commit()
        except Exception as e:
            _logger.debug("[PetEngine] unlock_appearance 失败: %s", e)

    def _unlock_habitat(self, user_id: str, habitat_id: str) -> None:
        try:
            self._conn.execute(
                "INSERT OR IGNORE INTO pet_habitat_unlocks (user_id, habitat_id) VALUES (?, ?)",
                (user_id, habitat_id),
            )
            self._conn.commit()
        except Exception as e:
            _logger.debug("[PetEngine] unlock_habitat 失败: %s", e)

    def _log_change(self, user_id, behavior_type, amount, co2_saved, rewards, old_state, new_state):
        try:
            self._conn.execute(
                """
            INSERT INTO pet_state_change_log
            (user_id, behavior_type, amount, co2_saved, rewards_json, old_state_json, new_state_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    user_id,
                    behavior_type,
                    amount,
                    co2_saved,
                    json.dumps(rewards),
                    json.dumps(old_state.to_dict()),
                    json.dumps(new_state.to_dict()),
                ),
            )
            self._conn.commit()
        except Exception as e:
            _logger.debug("[PetEngine] log_change 失败: %s", e)

    def _check_achievements(self, user_id: str, state: PetState) -> List[str]:
        """任务4: 成就检查 + 解锁"""
        unlocked = []
        for achv_id, meta in ACHIEVEMENTS.items():
            cur = self._conn.execute(
                "SELECT 1 FROM pet_achievements WHERE user_id=? AND achievement_id=?",
                (user_id, achv_id),
            ).fetchone()
            if cur:
                continue
            # 简化的条件判断
            cond = meta["cond"]
            ok = False
            if cond == "total_co2>=100" and state.total_co2_saved >= 100:
                ok = True
            elif cond == "total_co2>=1000" and state.total_co2_saved >= 1000:
                ok = True
            elif cond == "consecutive_days>=7" and state.consecutive_days >= 7:
                ok = True
            elif cond == "consecutive_days>=30" and state.consecutive_days >= 30:
                ok = True
            elif cond == "consecutive_days>=100" and state.consecutive_days >= 100:
                ok = True
            elif cond == "level==50" and state.level == 50:
                ok = True
            if ok:
                try:
                    self._conn.execute(
                        "INSERT OR IGNORE INTO pet_achievements (user_id, achievement_id) VALUES (?, ?)",
                        (user_id, achv_id),
                    )
                    self._conn.commit()
                    unlocked.append(achv_id)
                except Exception as e:
                    _logger.debug("[PetEngine] unlock achievement 失败: %s", e)
        return unlocked

    def _update_codex(self, user_id: str, behavior_type: str, amount: float) -> List[str]:
        """任务4: 图鉴更新 + 解锁"""
        unlocked = []
        codex_id = BEHAVIOR_TO_CODEX.get(behavior_type)
        if not codex_id:
            return unlocked
        threshold = CODEX_THRESHOLDS.get(codex_id, 0)
        # 累加进度
        try:
            cur = self._conn.execute(
                "SELECT progress FROM pet_codex WHERE user_id=? AND codex_id=?", (user_id, codex_id)
            ).fetchone()
            new_progress = (cur["progress"] if cur else 0) + int(amount)
            if cur:
                self._conn.execute(
                    "UPDATE pet_codex SET progress=? WHERE user_id=? AND codex_id=?",
                    (new_progress, user_id, codex_id),
                )
            else:
                self._conn.execute(
                    "INSERT INTO pet_codex (user_id, codex_id, unlocked_at, progress) VALUES (?, ?, ?, ?)",
                    (
                        user_id,
                        codex_id,
                        time.strftime("%Y-%m-%d %H:%M:%S") if new_progress >= threshold else None,
                        new_progress,
                    ),
                )
            self._conn.commit()
            if new_progress >= threshold and not cur:
                # 刚达阈值,标记 unlocked_at
                self._conn.execute(
                    "UPDATE pet_codex SET unlocked_at=? WHERE user_id=? AND codex_id=?",
                    (time.strftime("%Y-%m-%d %H:%M:%S"), user_id, codex_id),
                )
                self._conn.commit()
                unlocked.append(codex_id)
        except Exception as e:
            _logger.debug("[PetEngine] update_codex 失败: %s", e)
        return unlocked

    # ===== 任务3: 互动 =====

    def pat(self, user_id: str) -> Dict[str, Any]:
        """抚摸:心情+2"""
        state = self.get_state(user_id)
        state.mood = min(100, state.mood + 2)
        self._save_state(state)
        return {"ok": True, "mood": state.mood, "msg": "嘻嘻,好舒服~💚"}

    def feed(self, user_id: str, item_id: str) -> Dict[str, Any]:
        """投喂道具"""
        ITEMS = {
            "led_bulb": {"cost": 1, "hunger": 15, "mood": 3, "vitality": 0, "name": "节能灯泡"},
            "transit": {"cost": 1, "hunger": 5, "mood": 5, "vitality": 15, "name": "公交卡"},
            "solar": {"cost": 3, "hunger": 20, "mood": 8, "vitality": 10, "name": "太阳能板"},
            "recycle": {"cost": 2, "hunger": 10, "mood": 20, "vitality": 0, "name": "回收箱"},
            "fruit": {
                "cost": 20,
                "hunger": 100,
                "mood": 100,
                "vitality": 100,
                "name": "碳中和圣果",
            },
        }
        item = ITEMS.get(item_id)
        if not item:
            return {"ok": False, "msg": "道具不存在"}
        state = self.get_state(user_id)
        if state.coins < item["cost"]:
            return {"ok": False, "msg": f"精灵币不足(需 {item['cost']},有 {state.coins})"}
        state.coins -= item["cost"]
        state.hunger = min(100, state.hunger + item["hunger"])
        state.mood = min(100, state.mood + item["mood"])
        state.vitality = min(100, state.vitality + item["vitality"])
        self._save_state(state)
        return {
            "ok": True,
            "item_name": item["name"],
            "msg": f"投喂了 {item['name']}!好吃~",
            "state": state.to_dict(),
        }

    # ===== 任务5: 技能 =====

    def is_skill_unlocked(self, skill_id: str, level: int) -> bool:
        return level >= SKILL_UNLOCK.get(skill_id, 999)

    def record_skill_use(self, user_id: str, skill_id: str, result: Dict[str, Any]) -> None:
        try:
            self._conn.execute(
                "INSERT INTO pet_skill_uses (user_id, skill_id, result_json) VALUES (?, ?, ?)",
                (user_id, skill_id, json.dumps(result, ensure_ascii=False, default=str)),
            )
            self._conn.commit()
        except Exception as e:
            _logger.debug("[PetEngine] record_skill_use 失败: %s", e)

    def get_skills(self, user_id: str) -> List[Dict[str, Any]]:
        state = self.get_state(user_id)
        all_skills = {
            "skill_today_summary": {"name": "今日复盘", "type": "active"},
            "skill_lifetime_impact": {"name": "长期累计", "type": "active"},
            "skill_score_card": {"name": "低碳成绩单", "type": "active"},
            "skill_share_poster": {"name": "环保海报", "type": "active"},
            "advanced_carbon_footprint": {"name": "碳足迹分析", "type": "advanced"},
            "advanced_personalized_advice": {"name": "个性化推荐", "type": "advanced"},
        }
        result = []
        for sid, meta in all_skills.items():
            result.append(
                {
                    "id": sid,
                    "name": meta["name"],
                    "type": meta["type"],
                    "unlocked": self.is_skill_unlocked(sid, state.level),
                    "unlock_level": SKILL_UNLOCK.get(sid, 999),
                }
            )
        return result


# 任务6: 单例
_pet_engine: Optional[PetEngine] = None


def get_pet_engine() -> PetEngine:
    global _pet_engine
    if _pet_engine is None:
        _pet_engine = PetEngine()
    return _pet_engine
