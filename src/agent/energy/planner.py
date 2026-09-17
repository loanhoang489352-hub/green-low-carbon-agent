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
import math
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
from .emission_factors import electricity_factor_for

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
        "gas_stove_flame_adjust",
    ],
    "gas_upgrade": [
        "gas_water_heater_insulation",
    ],
    # P12 任务3: 扩充电器族
    "dishwasher_present": [
        "dishwasher_off_peak",
    ],
    "electric_heater_present": [
        "electric_heater_temp",
    ],
    "range_hood_present": [
        "range_hood_short_use",
    ],
    "rice_cooker_present": [
        "rice_cooker_insulation",
    ],
    "toilet_present": [
        "toilet_dual_flush",
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
    # P12 任务3: 扩充电器关键词
    "洗碗机": "dishwasher_present",
    "dishwasher": "dishwasher_present",
    "电暖器": "electric_heater_present",
    "取暖器": "electric_heater_present",
    "electric_heater": "electric_heater_present",
    "油烟机": "range_hood_present",
    "抽油烟机": "range_hood_present",
    "range_hood": "range_hood_present",
    "电饭煲": "rice_cooker_present",
    "rice_cooker": "rice_cooker_present",
    "马桶": "toilet_present",
    "toilet": "toilet_present",
    "燃气灶": "gas_baseline",
    "gas_stove": "gas_baseline",
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
        app_keys = list(dict.fromkeys(self._match_appliance_key(a) for a in profile.appliances if isinstance(a, str) and a))
        baseline_keys = ["water_baseline"]
        if profile.has_incandescent is True:
            action_keys.append("led_replace_incandescent")
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
        # Applicability beats category quotas. Unknown devices are not invented.
        excluded = set(profile.already_doing or []) | set(profile.excluded_actions or [])
        action_keys = [key for key in action_keys if key not in excluded
                       and not (key.startswith("gas_") and profile.uses_gas is not True)
                       and not (key == "water_repair_drip" and profile.has_drip is not True)
                       and not (key == "led_replace_incandescent" and profile.has_incandescent is not True)
                       and not (key == "ac_temp_up_1c" and profile.ac_temp_setting is not None and float(profile.ac_temp_setting) >= 26)]
        # Generic water heaters may be gas-powered; do not assume electric control.
        if not any(a in ("电热水器", "electric_water_heater") for a in profile.appliances):
            action_keys = [k for k in action_keys if not k.startswith("water_heater_")]
        action_keys = action_keys[:12]
        if profile.priority == "comfort":
            action_keys = [k for k in action_keys if k not in {"ac_temp_up_1c", "water_heater_temp_down", "electric_heater_temp", "water_bathing_shorter"}]

        # 4. 拼装 EnergyAction
        actions: List[EnergyAction] = []
        for ak in action_keys:
            saving = APPLIANCE_SAVINGS[ak]
            action = self._action_from_template(ak, saving, profile, city_pricing)
            if ak == "water_bathing_shorter":
                self._estimate_shower(action, profile)
            actions.append(action)
        if profile.priority == "money":
            actions.sort(key=lambda a: (-a.estimated_saving_cny, a.difficulty, a.id))
        else:
            actions.sort(key=lambda a: (a.difficulty, a.id))

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

    def _action_from_template(self, action_key: str, saving, profile, city_pricing) -> EnergyAction:
        """从 APPLIANCE_SAVINGS 模板构造一个 EnergyAction
        不修改任何数值字段 — 数值 = 政策/标准溯源
        """
        annual = action_key in {"ac_temp_up_1c", "led_replace_incandescent", "unplug_standby", "washer_full_load"}
        descriptions = {
            "ac_temp_up_1c": "制冷时可在保持舒适的前提下尝试调高1°C；制热情景不套用此年度参考量。",
            "ac_clean_filter": "按设备说明书检查和清洁滤网，操作前断电；不套用冰箱标准估算空调节省量。",
            "fridge_temp_setting": "按冰箱说明书检查温度和散热空间，兼顾食物保鲜。",
            "water_heater_off_peak": "只有确认自家峰谷套餐和设备定时功能后，才考虑调整加热时段；错峰不等于省电。",
            "water_heater_temp_down": "按热水器说明书检查适合的运行模式，保留必要的卫生与安全设置，不统一要求降低储水温度。",
            "dishwasher_off_peak": "按说明书合理装载；如有峰谷套餐，可核对适用时段后再安排运行。",
            "range_hood_short_use": "按设备说明书保持足够排烟并清洁油网，不为省电牺牲通风。",
            "rice_cooker_insulation": "按设备说明书安排烹饪与用餐时间，减少不必要的保温，同时保证食物安全。",
            "gas_stove_flame_adjust": "观察燃气灶运行是否正常，异常时停止使用并联系专业人员，不自行拆调燃气部件。",
            "gas_water_heater_insulation": "需要管道保温时先咨询专业人员，勿遮挡排烟、进气和检修部位。",
            "water_repair_drip": "确认存在滴漏后安排维修；未测流量和持续时间前不估算节省量。",
        }
        electricity_factor = electricity_factor_for(profile.city)
        annual_kwh = float(saving.saving_kwh_per_action) if annual else 0.0
        unit_price = city_pricing.tiers[0].unit_price_cny if city_pricing and city_pricing.tiers else None
        annual_cny = annual_kwh * unit_price if unit_price is not None else 0.0
        annual_co2 = annual_kwh * electricity_factor.kg_co2_per_kwh
        source_ref = saving.source_ref
        if annual:
            source_ref += (
                f" + official:{electricity_factor.source_url}"
                f"({electricity_factor.reporting_year}年{electricity_factor.geography}电力平均因子"
                f" {electricity_factor.kg_co2_per_kwh}kgCO2/kWh)"
            )
        return EnergyAction(
            id=action_key,  # action_id 直接用模板 key,稳定
            category=saving.category,
            title=saving.title,
            description=descriptions.get(action_key, saving.description),
            estimated_saving_kwh=round(annual_kwh, 3),
            estimated_saving_cny=round(annual_cny, 2),
            estimated_saving_co2_kg=round(annual_co2, 3),
            difficulty=saving.difficulty,
            when_to_do=saving.when_to_do,
            source_ref=source_ref,
            estimate_period="year" if annual else "unknown",
            estimate_kind="reference" if annual else "qualitative",
            estimate_note=((f"节电量是知识库年度参考，未按你家设备功率和时长校准；费用按"
                            f"{unit_price}元/kWh计算；减排按生态环境部、国家统计局发布的"
                            f"{electricity_factor.reporting_year}年{electricity_factor.geography}因子"
                            f"{electricity_factor.kg_co2_per_kwh}kgCO2/kWh计算。不是实测。") if annual
                           else "旧模板缺少明确周期或可验证数值依据，不计算收益。"),
        )

    def _estimate_shower(self, action, profile):
        action.title = "尝试缩短一次淋浴"
        action.description = "在保持舒适的前提下，本周尝试把每次淋浴缩短1分钟；已经很短则保持原习惯。"
        values = (profile.family_size, profile.shower_minutes, profile.shower_flow_lpm,
                  profile.showers_per_person_week, profile.water_price_per_m3)
        if any(v is None for v in values):
            action.estimate_note = "补充家庭人数、淋浴分钟数、实测流量、每人每周次数和水价后，可计算用水估算。"
            return
        people, minutes, flow, frequency, price = map(float, values)
        reduction = min(1.0, max(0.0, minutes - 3.0))
        water = people * reduction * flow * frequency * 52 / 1000
        action.estimated_saving_water_m3 = round(water, 3)
        action.estimated_saving_cny = round(water * price, 2)
        action.estimate_period = "year"
        action.estimate_kind = "calculated"
        action.source_ref = "profile:人数/实测流量/每周次数/水价 + formula:人数×缩短分钟×L/min×次数×52÷1000"
        action.estimate_note = f"假设每次缩短{reduction:g}分钟且全年保持：{people:g}人×{reduction:g}分钟×{flow:g}L/min×{frequency:g}次/周×52÷1000；水价{price:g}元/m³。不推算热水能耗或减碳。"

    # ========== 守卫(Guard)逻辑 ==========

    def _check_guards(self, profile: HouseholdProfile) -> Optional[EnergyPlan]:
        """4 个标准守卫检查

        任一失败 → 返回一个 blocked EnergyPlan(actions=[], warning=GUARD_XXX: ...)
        全过 → 返回 None,继续正常 plan 生成
        """
        # 1) GUARD_NO_APPLIANCES: appliances 全空 / 全 None / 全 ""
        # Reject malformed/NaN/negative inputs before arithmetic or sorting.
        ranges = {"family_size": (1, 20), "home_size_sqm": (10, 2000),
                  "monthly_electricity_bill": (0, 5000), "monthly_water_bill": (0, 1000),
                  "monthly_gas_bill": (0, 5000), "ac_temp_setting": (16, 32),
                  "shower_minutes": (0, 120), "shower_flow_lpm": (0, 50),
                  "showers_per_person_week": (0, 21), "water_price_per_m3": (0, 100)}
        try:
            for key, (low, high) in ranges.items():
                value = getattr(profile, key, None)
                if value is not None and (isinstance(value, bool) or not math.isfinite(float(value)) or not low <= float(value) <= high):
                    raise ValueError(key)
            if profile.family_size is not None and float(profile.family_size) != int(float(profile.family_size)):
                raise ValueError("family_size")
            for key in ("uses_gas", "has_incandescent", "has_drip"):
                if getattr(profile, key) is not None and not isinstance(getattr(profile, key), bool):
                    raise ValueError(key)
            for key in ("appliances", "already_doing", "excluded_actions", "confirmed_fields"):
                if not isinstance(getattr(profile, key), list) or any(not isinstance(x, str) for x in getattr(profile, key) if x is not None):
                    raise ValueError(key)
        except (TypeError, ValueError, OverflowError):
            return self._make_blocked_plan(profile, "GUARD_EXTREME_VALUES: 请检查人数、设备列表及非负有限数值")
        apps = getattr(profile, "appliances", None)
        if not apps or all(
            (a is None) or (not isinstance(a, str)) or (a.strip() == "")
            for a in apps
        ):
            return self._make_blocked_plan(
                profile,
                f"{GUARD_NO_APPLIANCES}: appliances 列表为空,无法推荐具体行动",
            )
        if profile.family_size is None:
            return self._make_blocked_plan(profile, "GUARD_MISSING_INFO: 请补充家庭人数")

        # 2) GUARD_UNKNOWN_CITY: 城市不在政策表
        city = getattr(profile, "city", "") or ""
        if city and lookup_city_pricing(city) is None:
            return self._make_blocked_plan(
                profile,
                f"{GUARD_UNKNOWN_CITY}: 城市 '{city}' 不在政策表,无法估算节省金额",
            )

        # 3) GUARD_ZERO_USAGE: 月费用(电/水/气)全 0 或缺失
        # 缺失(None)经 `or 0` 归一为 0,与 0 同等对待(修复:原来 all(... is not None) 前置让缺失直接放行)
        elec_bill = float(getattr(profile, "monthly_electricity_bill", 0) or 0)
        water_bill = float(getattr(profile, "monthly_water_bill", 0) or 0)
        gas_bill = float(getattr(profile, "monthly_gas_bill", 0) or 0)
        if elec_bill <= 0 and water_bill <= 0 and gas_bill <= 0:
            return self._make_blocked_plan(
                profile,
                f"{GUARD_ZERO_USAGE}: 月用电/水/气均为 0 或缺失,无法估算节省",
            )

        # 4) GUARD_EXTREME_VALUES: 参数超出合理区间
        family_size = int(float(getattr(profile, "family_size", 1) or 1))
        home_size = float(getattr(profile, "home_size_sqm", 90) or 90)
        if (family_size < 1 or family_size > 20
                or home_size < 10 or home_size > 2000
                or elec_bill > 5000 or water_bill > 1000 or gas_bill > 5000):
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
        if not isinstance(appliance, str):
            return None
        a = appliance.strip().lower()
        if a in ("燃气热水器", "gas_water_heater"):
            return "gas_upgrade"
        for kw, key in _APPLIANCE_KEYWORD_MAP.items():
            if kw.lower() == a:
                return key
        return None

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
        reminder = "以舒适和设备说明书为准；峰谷时段请核对自家电价套餐。打卡只记录执行，不代表实测节省。"

        total_cny = sum(a.estimated_saving_cny for a in picked)
        total_co2 = sum(a.estimated_saving_co2_kg for a in picked)

        goal = (
            f"今天从{len(picked)}件候选中选1件尝试，记录执行感受"
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
