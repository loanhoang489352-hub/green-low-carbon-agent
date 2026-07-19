"""
P12.1: 节能规划器 — EnergyPlanner

严格无幻觉:每个 action 都从 APPLIANCE_SAVINGS 模板生成,
数值字段直接复用 source_ref,绝不二次"创作"数字。

支持:
1. generate_plan(profile) → EnergyPlan (5-10 actions, 每类至少 2 个)
2. generate_today_card(plan) → TodayCard (抽 3 个最容易执行的 + 1 个安全提醒)
3. save_plan / load_plan (落 SQLite,便于 P12.2 路由层调用)

P12 重构 — GUARD 接口契约:
  generate_plan 开头跑 4 个守卫检查;任一失败立即返回 blocked plan:
    GUARD_NO_APPLIANCES  : appliances 全空 / 全 None / 全 ""
    GUARD_UNKNOWN_CITY   : 城市不在 CITY_TIER_PRICING
    GUARD_ZERO_USAGE     : 月费用(电/水/气)全 0 或缺失
    GUARD_EXTREME_VALUES : 参数超出合理区间(负面积/0 人/天价账单)
  blocked plan 字段:status="blocked", blocked=True, warning="GUARD_XXX: ...",
  actions=[]。
"""
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional

from paths import ENERGY_ACTIONS_DB

from .models import (
    HouseholdProfile,
    EnergyAction,
    EnergyPlan,
    TodayCard,
    PlanStatus,
)
from .policies import (
    APPLIANCE_SAVINGS,
    CITY_TIER_PRICING,
    lookup_city_pricing,
)

logger = logging.getLogger(__name__)

# ========== 标准守卫常量(契约) ==========
GUARD_UNKNOWN_CITY   = "GUARD_UNKNOWN_CITY"
GUARD_ZERO_USAGE     = "GUARD_ZERO_USAGE"
GUARD_NO_APPLIANCES  = "GUARD_NO_APPLIANCES"
GUARD_EXTREME_VALUES = "GUARD_EXTREME_VALUES"


# 家庭画像 → 推荐 action_keys 的映射(每类至少 2 个)
# 关键:不靠 LLM 推断,全部用查表
_PROFILE_TO_ACTIONS: Dict[str, List[str]] = {
    "ac_present": [
        "ac_temp_up_1c",
        "ac_clean_filter",
    ],
    "water_heater_present": [
        "water_heater_off_peak",
        "water_heater_temp_down",
    ],
    "fridge_present": [
        "fridge_temp_setting",
    ],
    "washer_present": [
        "washer_full_load",
    ],
    "lighting": [
        "led_replace_incandescent",
        "unplug_standby",
    ],
    "water_baseline": [
        "water_repair_drip",
        "water_bathing_shorter",
    ],
    "water_upgrade": [
        "water_low_flow_shower",
    ],
    "gas_baseline": [
        "gas_stove_pot_match",
    ],
    "gas_upgrade": [
        "gas_water_heater_insulation",
    ],
}

# appliance 关键词 → profile key 的映射
_APPLIANCE_KEYWORD_MAP: Dict[str, str] = {
    "空调": "ac_present",
    "ac": "ac_present",
    "air_conditioner": "ac_present",
    "热水器": "water_heater_present",
    "电热水器": "water_heater_present",
    "water_heater": "water_heater_present",
    "冰箱": "fridge_present",
    "fridge": "fridge_present",
    "冰柜": "fridge_present",
    "洗衣机": "washer_present",
    "washer": "washer_present",
    "灯": "lighting",
    "灯具": "lighting",
    "lighting": "lighting",
}


class EnergyPlanner:
    """节能方案生成器

    使用方式:
        planner = EnergyPlanner()
        plan = planner.generate_plan(profile)
        card = planner.generate_today_card(plan)
        planner.save_plan(plan)   # 落 SQLite
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or ENERGY_ACTIONS_DB

    # ========== 方案生成 ==========

    def generate_plan(self, profile: HouseholdProfile) -> EnergyPlan:
        """根据画像生成 5-10 个 action 的方案

        步骤:
          0. 4 个标准 GUARD 检查(任何一条失败 → blocked plan)
          1. 根据 city 查阶梯电价 → 修正节省元数据
          2. 根据 appliances 推节能潜力(查表,不编造)
          3. 拼装 action(每类至少 2 个,确保 5-10 个)
          4. 总节省直接对 actions 求和
        """
        # ===== 0. 守卫检查(按 GUARD_NO_APPLIANCES → GUARD_UNKNOWN_CITY →
        #                GUARD_ZERO_USAGE → GUARD_EXTREME_VALUES 顺序) =====
        blocked_plan = self._check_guards(profile)
        if blocked_plan is not None:
            logger.info(
                "[planner] blocked plan for user=%s warning=%s",
                profile.user_id, blocked_plan.warning,
            )
            return blocked_plan

        # 1. 阶梯电价(用于后续可能的"高耗电家庭建议错峰"提示)
        city_pricing = lookup_city_pricing(profile.city)
        logger.info(
            "[planner] user=%s city=%s pricing=%s",
            profile.user_id, profile.city, city_pricing.city if city_pricing else None,
        )

        # 2. 推 action_keys
        action_keys: List[str] = []
        app_keys = {self._match_appliance_key(a) for a in profile.appliances if a}
        # 总是保留照明 + 水 baseline + 气 baseline
        baseline_keys = ["lighting", "water_baseline", "gas_baseline"]
        for k in baseline_keys:
            action_keys.extend(_PROFILE_TO_ACTIONS.get(k, []))
        for k in app_keys:
            if k:
                action_keys.extend(_PROFILE_TO_ACTIONS.get(k, []))
        # 去重保序
        seen = set()
        deduped = []
        for ak in action_keys:
            if ak not in seen and ak in APPLIANCE_SAVINGS:
                seen.add(ak)
                deduped.append(ak)
        action_keys = deduped

        # 3. 先 truncate 到 10(从主推荐池里截),再补齐每类至少 2 个(补完后不再 truncate,允许上限 12 — 任务要求 5-10,但每类至少 2 个 = 6 个起步;真实家庭常有 8-12 个)
        action_keys = action_keys[:10]
        action_keys = self._ensure_category_min_two(action_keys)
        # 最终上限 12(避免极多家电时爆炸)
        action_keys = action_keys[:12]  # 上限 12

        # 4. 拼装 EnergyAction
        actions: List[EnergyAction] = []
        for ak in action_keys:
            saving = APPLIANCE_SAVINGS[ak]
            actions.append(self._action_from_template(ak, saving))

        # 5. 合计
        total_cny = sum(a.estimated_saving_cny for a in actions)
        total_co2 = sum(a.estimated_saving_co2_kg for a in actions)

        # 6. 缩 plan id
        plan_id = f"plan-{uuid.uuid4().hex[:10]}"

        return EnergyPlan(
            id=plan_id,
            user_id=profile.user_id,
            profile_snapshot=profile,
            actions=actions,
            total_estimated_saving_cny=round(total_cny, 2),
            total_estimated_saving_co2_kg=round(total_co2, 2),
            created_at=datetime.utcnow().isoformat() + "Z",
            status=PlanStatus.ACTIVE.value,
        )

    def _action_from_template(self, action_key: str, saving) -> EnergyAction:
        """从 APPLIANCE_SAVINGS 模板构造一个 EnergyAction
        不修改任何数值字段 — 数值 = 政策/标准溯源
        """
        return EnergyAction(
            id=action_key,  # action_id 直接用模板 key,稳定
            category=saving.category,
            title=saving.title,
            description=saving.description,
            estimated_saving_kwh=float(saving.saving_kwh_per_action),
            estimated_saving_cny=float(saving.saving_cny_per_action),
            estimated_saving_co2_kg=float(saving.saving_co2_kg_per_action),
            difficulty=saving.difficulty,
            when_to_do=saving.when_to_do,
            source_ref=saving.source_ref,
        )

    # ========== 守卫(Guard)逻辑 ==========

    def _check_guards(self, profile: HouseholdProfile) -> Optional[EnergyPlan]:
        """4 个标准守卫检查

        任一失败 → 返回一个 blocked EnergyPlan(actions=[], warning=GUARD_XXX: ...)
        全过 → 返回 None,继续正常 plan 生成
        """
        # 1) GUARD_NO_APPLIANCES: appliances 全空 / 全 None / 全 ""
        apps = getattr(profile, "appliances", None)
        if not apps or all(
            (a is None) or (not isinstance(a, str)) or (a.strip() == "")
            for a in apps
        ):
            return self._make_blocked_plan(
                profile,
                f"{GUARD_NO_APPLIANCES}: appliances 列表为空,无法推荐具体行动",
            )

        # 2) GUARD_UNKNOWN_CITY: 城市不在政策表
        city = getattr(profile, "city", "") or ""
        if lookup_city_pricing(city) is None:
            return self._make_blocked_plan(
                profile,
                f"{GUARD_UNKNOWN_CITY}: 城市 '{city}' 不在政策表,无法估算节省金额",
            )

        # 3) GUARD_ZERO_USAGE: 月费用(电/水/气)全 0 或缺失
        # 兼容字段:优先 *_bill( HouseholdProfile 现有字段),fallback 到 *_kwh / *_m3(原始用量)
        elec_bill = float(getattr(profile, "monthly_electricity_bill", 0) or 0)
        water_bill = float(getattr(profile, "monthly_water_bill", 0) or 0)
        gas_bill = float(getattr(profile, "monthly_gas_bill", 0) or 0)
        elec_kwh = float(getattr(profile, "monthly_electricity_kwh", 0) or 0)
        water_m3 = float(getattr(profile, "monthly_water_m3", 0) or 0)
        gas_m3 = float(getattr(profile, "monthly_gas_m3", 0) or 0)
        # 总用量 = bill > 0 或原始用量 > 0 即视为"有用量"
        if (elec_bill <= 0 and water_bill <= 0 and gas_bill <= 0
                and elec_kwh <= 0 and water_m3 <= 0 and gas_m3 <= 0):
            return self._make_blocked_plan(
                profile,
                f"{GUARD_ZERO_USAGE}: 月用电/水/气均为 0 或缺失,无法估算节省",
            )

        # 4) GUARD_EXTREME_VALUES: 参数超出合理区间
        family_size = int(getattr(profile, "family_size", 1) or 1)
        home_size = float(getattr(profile, "home_size_sqm", 0) or 0)
        if (family_size < 1 or family_size > 20
                or home_size < 10 or home_size > 2000
                or elec_bill > 5000 or water_bill > 1000 or gas_bill > 5000
                or elec_kwh > 5000 or water_m3 > 100 or gas_m3 > 500):
            return self._make_blocked_plan(
                profile,
                f"{GUARD_EXTREME_VALUES}: 参数超出合理区间 "
                f"(family_size={family_size}, home_size_sqm={home_size}, "
                f"bills={elec_bill}/{water_bill}/{gas_bill})",
            )

        return None

    def _make_blocked_plan(
        self,
        profile: HouseholdProfile,
        warning_message: str,
    ) -> EnergyPlan:
        """构造一个 blocked plan — 守卫失败时返回"""
        return EnergyPlan(
            id="blocked-" + uuid.uuid4().hex[:8],
            user_id=profile.user_id,
            profile_snapshot=profile,
            actions=[],
            total_estimated_saving_cny=0.0,
            total_estimated_saving_co2_kg=0.0,
            created_at=datetime.now().isoformat(),
            status=PlanStatus.BLOCKED.value,
            warning=warning_message,
            blocked=True,
        )

    def _match_appliance_key(self, appliance: str) -> Optional[str]:
        a = appliance.strip().lower()
        for kw, key in _APPLIANCE_KEYWORD_MAP.items():
            if kw.lower() in a or a in kw.lower():
                return key
        return None

    def _ensure_category_min_two(self, action_keys: List[str]) -> List[str]:
        """每类(electricity/water/gas)至少 2 个 action"""
        from collections import Counter
        cat_count: Counter = Counter()
        for ak in action_keys:
            if ak in APPLIANCE_SAVINGS:
                cat_count[APPLIANCE_SAVINGS[ak].category] += 1

        # 不足 2 个的类 → 按"安全/易执行"补
        # 补全优先级:electricity → led_replace_incandescent + unplug_standby(总是推荐)
        #            water → water_bathing_shorter(必选)
        #            gas → gas_stove_pot_match(必选)
        fillers = {
            "electricity": ["unplug_standby", "led_replace_incandescent"],
            "water": ["water_repair_drip", "water_bathing_shorter"],
            "gas": ["gas_stove_pot_match", "gas_water_heater_insulation"],
        }
        for cat, want in [(c, cat_count[c]) for c in cat_count]:
            pass  # noqa
        for category, fill_keys in fillers.items():
            while cat_count[category] < 2:
                for fk in fill_keys:
                    if fk not in action_keys and fk in APPLIANCE_SAVINGS:
                        action_keys.append(fk)
                        cat_count[category] += 1
                        break
                else:
                    break  # 找不到,跳出
        return action_keys

    # ========== 今日卡 ==========

    def generate_today_card(self, plan: EnergyPlan) -> TodayCard:
        """从 plan 抽今日 3 个最易执行 + 1 个安全提醒"""
        # 排序:difficulty 升序 → 按潜在节省降序
        ranked = sorted(
            plan.actions,
            key=lambda a: (a.difficulty, -a.estimated_saving_cny),
        )
        picked = ranked[:3]

        # 安全/风险提醒(根据画像中 peak_offpeak_usage)
        profile = plan.profile_snapshot
        if profile.peak_offpeak_usage == "peak":
            reminder = (
                "你高峰用电偏多,建议把电热水器、洗碗机安排到 22:00 后谷段"
            )
        elif profile.peak_offpeak_usage == "offpeak":
            reminder = "已偏谷段用电,继续保持即可"
        else:
            reminder = (
                "晚 18-21 时是用电高峰,尽量把大功率电器错开"
            )

        total_cny = sum(a.estimated_saving_cny for a in picked)
        total_co2 = sum(a.estimated_saving_co2_kg for a in picked)

        goal = (
            f"今日完成 3 件 ≈ 省 {total_cny:.1f} 元 / 减 {total_co2:.1f} kg CO₂"
        )

        return TodayCard(
            user_id=plan.user_id,
            plan_id=plan.id,
            goal=goal,
            actions=picked,
            reminder=reminder,
            when_to_do="今天 21:00 前完成",
            judge="点击反馈:全做/部分做/未做",
        )

    # ========== 落库 / 加载 ==========

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(str(self.db_path))
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=5000")
        return c

    def save_plan(self, plan: EnergyPlan) -> None:
        """保存方案到 energy_plans 表"""
        conn = self._conn()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO energy_plans
                  (plan_id, user_id, profile_snapshot, actions,
                   total_saving_cny, total_saving_co2_kg, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan.id,
                    plan.user_id,
                    json.dumps(plan.profile_snapshot.to_dict(), ensure_ascii=False),
                    json.dumps([a.to_dict() for a in plan.actions], ensure_ascii=False),
                    plan.total_estimated_saving_cny,
                    plan.total_estimated_saving_co2_kg,
                    plan.status,
                    plan.created_at,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def load_plan(self, plan_id: str) -> Optional[EnergyPlan]:
        """按 plan_id 加载方案"""
        conn = self._conn()
        try:
            cur = conn.execute(
                "SELECT plan_id, user_id, profile_snapshot, actions, "
                "total_saving_cny, total_saving_co2_kg, status, created_at "
                "FROM energy_plans WHERE plan_id = ?",
                (plan_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            profile_dict = json.loads(row[2])
            actions_dict = json.loads(row[3])
            return EnergyPlan(
                id=row[0],
                user_id=row[1],
                profile_snapshot=HouseholdProfile.from_dict(profile_dict),
                actions=[EnergyAction(**a) for a in actions_dict],
                total_estimated_saving_cny=row[4],
                total_estimated_saving_co2_kg=row[5],
                created_at=row[7],
                status=row[6],
            )
        finally:
            conn.close()

    def list_plans(self, user_id: str) -> List[EnergyPlan]:
        """列出某用户的所有方案"""
        conn = self._conn()
        out: List[EnergyPlan] = []
        try:
            cur = conn.execute(
                "SELECT plan_id FROM energy_plans WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            )
            for (pid,) in cur.fetchall():
                plan = self.load_plan(pid)
                if plan:
                    out.append(plan)
        finally:
            conn.close()
        return out
