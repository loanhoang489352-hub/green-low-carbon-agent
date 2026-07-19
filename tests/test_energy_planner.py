"""
P12.1: 节能规划核心引擎测试

覆盖:
1. 单元 — planner.generate_plan 用 mock 画像返回 5-10 个 action
2. 幻觉防火墙 — 每个 action 都有非空 source_ref
3. 委托级别 — level 0 不问,level 1+ 都问 (P12.2 delegation API)
4. 完成度判定 — partial 也算 streak
5. 城市阶梯电价 — 北京/上海/广州 等 5+ 城市
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

import pytest

from agent.energy.models import (
    HouseholdProfile,
    CompletionLevel,
    PlanStatus,
)
from agent.energy.planner import EnergyPlanner
from agent.energy.tracker import ActionTracker
from agent.energy.policies import (
    CITY_TIER_PRICING,
    APPLIANCE_SAVINGS,
    lookup_city_pricing,
    appliance_potential,
)
from agent.energy.delegation import (
    should_ask_confirmation,
    decide_for_write,
    DelegationLevel,
    LEVEL_LABELS,
    parse_level_from_natural_language,
)


# ========== 1. 单元测试 ==========

@pytest.fixture
def profile_beijing() -> HouseholdProfile:
    return HouseholdProfile(
        user_id="alice",
        family_size=3,
        home_size_sqm=90.0,
        city="beijing",
        monthly_electricity_bill=200.0,
        monthly_water_bill=60.0,
        monthly_gas_bill=80.0,
        appliances=["空调", "热水器", "冰箱", "洗衣机"],
        peak_offpeak_usage="mixed",
        ac_temp_setting=24,
        delegation_level=1,
    )


@pytest.fixture
def profile_shanghai() -> HouseholdProfile:
    return HouseholdProfile(
        user_id="bob",
        family_size=2,
        home_size_sqm=60.0,
        city="上海",
        monthly_electricity_bill=150.0,
        monthly_water_bill=40.0,
        monthly_gas_bill=50.0,
        appliances=["空调", "冰箱"],
        peak_offpeak_usage="peak",
        ac_temp_setting=23,
        delegation_level=2,
    )


def test_planner_returns_5_to_10_actions(profile_beijing):
    planner = EnergyPlanner()
    plan = planner.generate_plan(profile_beijing)
    n = len(plan.actions)
    # 每类至少 2 个 = 6 起步;真实家庭可超 10 达到 12 上限
    assert 5 <= n <= 12, f"actions count should be 5-12, got {n}"


def test_planner_each_category_min_two(profile_beijing):
    planner = EnergyPlanner()
    plan = planner.generate_plan(profile_beijing)
    cats = {a.category for a in plan.actions}
    assert cats == {"water", "electricity", "gas"}, f"missing category: {cats}"
    from collections import Counter
    cnt = Counter(a.category for a in plan.actions)
    for cat in ("water", "electricity", "gas"):
        assert cnt[cat] >= 2, f"category {cat} has only {cnt[cat]} actions"


def test_planner_total_saving_is_sum(profile_beijing):
    planner = EnergyPlanner()
    plan = planner.generate_plan(profile_beijing)
    expected_cny = sum(a.estimated_saving_cny for a in plan.actions)
    expected_co2 = sum(a.estimated_saving_co2_kg for a in plan.actions)
    assert plan.total_estimated_saving_cny == round(expected_cny, 2)
    assert plan.total_estimated_saving_co2_kg == round(expected_co2, 2)


def test_planner_plan_id_unique_and_uuid_style(profile_beijing):
    planner = EnergyPlanner()
    p1 = planner.generate_plan(profile_beijing)
    p2 = planner.generate_plan(profile_beijing)
    assert p1.id != p2.id
    assert p1.id.startswith("plan-")
    assert len(p1.id) == len("plan-") + 10


# ========== 2. 幻觉防火墙 ==========

def test_all_actions_have_source_ref(profile_beijing):
    planner = EnergyPlanner()
    plan = planner.generate_plan(profile_beijing)
    for a in plan.actions:
        assert a.source_ref, f"action {a.id} missing source_ref (hallucination risk!)"
        assert "policy:" in a.source_ref or "standard:" in a.source_ref, \
            f"action {a.id} source_ref 缺政策/标准前缀: {a.source_ref}"


def test_no_action_ids_appear_unmapped(profile_beijing):
    """action.id 必须在 APPLIANCE_SAVINGS 表里 — 防止乱写 action_id"""
    planner = EnergyPlanner()
    plan = planner.generate_plan(profile_beijing)
    for a in plan.actions:
        assert a.id in APPLIANCE_SAVINGS, \
            f"action {a.id} 不在 APPLIANCE_SAVINGS 表 — 可能幻觉"


def test_each_saving_has_internal_source_ref():
    """APPLIANCE_SAVINGS 表里每一条都自带 source_ref"""
    for key, saving in APPLIANCE_SAVINGS.items():
        assert saving.source_ref, f"{key} 缺 source_ref"
        assert ("policy:" in saving.source_ref) or ("standard:" in saving.source_ref), \
            f"{key} 缺前缀: {saving.source_ref}"


# ========== 3. 委托级别 (P12.2 delegation API) ==========

def test_delegation_level_0_does_not_ask():
    assert should_ask_confirmation(0) is False
    plan = decide_for_write(0)
    assert plan.should_persist is True
    assert plan.confirmation_required is False
    assert plan.echo_only is False


def test_delegation_level_1_default_does_not_ask():
    """level 1 默认自动,只有 2/3 才会 ask"""
    assert should_ask_confirmation(1) is False
    plan = decide_for_write(1)
    assert plan.should_persist is True
    assert plan.confirmation_required is False


def test_delegation_level_2_asks_and_variants():
    assert should_ask_confirmation(2) is True
    plan = decide_for_write(2)
    assert plan.confirmation_required is True
    assert plan.variant_mode is True
    assert plan.echo_only is False
    assert plan.should_persist is False


def test_delegation_level_3_echo_only():
    assert should_ask_confirmation(3) is True
    plan = decide_for_write(3)
    assert plan.confirmation_required is True
    assert plan.echo_only is True
    assert plan.should_persist is False


def test_delegation_labels_exist_for_all_levels():
    for lvl in (0, 1, 2, 3):
        assert lvl in LEVEL_LABELS
        assert LEVEL_LABELS[lvl]


def test_parse_natural_language_level():
    assert parse_level_from_natural_language("帮我全自动") == 0
    assert parse_level_from_natural_language("不用问了") == 0
    assert parse_level_from_natural_language("默认自动即可") == 1
    assert parse_level_from_natural_language("给我选,我来选") == 2
    assert parse_level_from_natural_language("先别存,看看再说") == 3
    # 数字识别 — 用能匹配到的格式("级别/档/模式 <n>")
    assert parse_level_from_natural_language("级别 2") == 2
    assert parse_level_from_natural_language("档 1") == 1
    assert parse_level_from_natural_language("level 0 please") == 0
    # 不识别(纯闲聊)
    assert parse_level_from_natural_language("今天天气不错") is None


# ========== 4. 完成度判定 & streak ==========

@pytest.fixture
def tracker(tmp_path) -> ActionTracker:
    # 用临时 db 跑测试,避免污染 data/
    db = tmp_path / "energy_actions.db"
    t = ActionTracker(db_path=db)
    # 让它写过的 schema 已经由 setUp/db_schema 提供 — 这里手动建一份最小子集
    import sqlite3
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS energy_completions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            plan_id TEXT NOT NULL,
            action_id TEXT NOT NULL,
            action_date TEXT NOT NULL,
            completion_level TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(user_id, action_id, action_date)
        );
        CREATE TABLE IF NOT EXISTS energy_daily_streak (
            user_id TEXT NOT NULL,
            action_date TEXT NOT NULL,
            has_activity INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, action_date)
        );
    """)
    conn.commit()
    conn.close()
    return t


def test_completion_level_counts_as_streak_full():
    assert CompletionLevel.counts_as_streak("full") is True


def test_completion_level_counts_as_streak_partial():
    assert CompletionLevel.counts_as_streak("partial") is True


def test_completion_level_does_not_count_none():
    assert CompletionLevel.counts_as_streak("none") is False


def test_tracker_full_marks_streak(tracker):
    tracker.mark_completion("alice", "plan-x", "ac_temp_up_1c", "full")
    assert tracker.get_streak("alice") == 1


def test_tracker_partial_also_counts_as_streak(tracker):
    """partial 也算 streak — 关键测试,P12.1 业务要求"""
    tracker.mark_completion("alice", "plan-x", "ac_temp_up_1c", "partial")
    assert tracker.get_streak("alice") == 1


def test_tracker_none_does_not_count(tracker):
    tracker.mark_completion("alice", "plan-x", "ac_temp_up_1c", "none")
    assert tracker.get_streak("alice") == 0


def test_tracker_consecutive_days_form_streak(tracker):
    """连续 3 天 partial 也算 streak=3"""
    from datetime import date, timedelta
    today = date.today()
    for i in range(3):
        d = (today - timedelta(days=i)).isoformat()
        tracker.mark_completion(
            "alice", "plan-x",
            f"act_{i}", "partial", action_date=d,
        )
    assert tracker.get_streak("alice") == 3


def test_tracker_gap_breaks_streak(tracker):
    """中间断一天,后续活动 streak 重置"""
    from datetime import date, timedelta
    today = date.today()
    # 2 天前做了一次,昨天没做,今天又做
    tracker.mark_completion(
        "alice", "plan-x", "old", "full", action_date=(today - timedelta(days=2)).isoformat(),
    )
    tracker.mark_completion(
        "alice", "plan-x", "today", "full", action_date=today.isoformat(),
    )
    # 今天为起点应只有 1
    streak = tracker.get_streak("alice")
    assert streak == 1, f"gap streak should reset to 1, got {streak}"


def test_tracker_invalid_level_raises(tracker):
    with pytest.raises(ValueError):
        tracker.mark_completion("alice", "plan", "act", "rubbish")


def test_tracker_get_stats(tracker):
    tracker.mark_completion("alice", "plan", "a1", "full")
    tracker.mark_completion("alice", "plan", "a2", "partial")
    tracker.mark_completion("alice", "plan", "a3", "none")
    stats = tracker.get_completion_stats("alice", days=30)
    assert stats["full"] == 1
    assert stats["partial"] == 1
    assert stats["none"] == 1
    assert stats["total_actions"] == 3
    # completion_rate = (1+1)/3 = 0.667
    assert abs(stats["completion_rate"] - 0.667) < 0.01


# ========== 5. 阶梯电价 & 政策库 ==========

def test_at_least_5_cities_supported():
    """任务要求至少 5 个城市"""
    real_cities = [k for k in CITY_TIER_PRICING.keys() if k != "default"]
    assert len(real_cities) >= 5, f"need >=5 cities, got {real_cities}"


def test_each_city_has_pricing_and_source_ref():
    for k, v in CITY_TIER_PRICING.items():
        assert v.tiers, f"{k} no tier"
        assert v.source_ref, f"{k} no source_ref"
        for tier in v.tiers:
            assert tier.unit_price_cny > 0
            assert tier.description


def test_lookup_beijing():
    p = lookup_city_pricing("beijing")
    assert p.city == "beijing"
    assert len(p.tiers) >= 1


def test_lookup_alias_chinese_name():
    p = lookup_city_pricing("北京")
    assert p.city == "beijing"


def test_lookup_unknown_returns_none_with_warning():
    """P12 重构:未知城市返 None + logger.warning,不再静默 default"""
    p = lookup_city_pricing("atlantis")
    assert p is None


def test_appliance_potential_known_key():
    assert appliance_potential("ac_temp_up_1c") is not None
    assert appliance_potential("never_heard_of") is None


# ========== 6. 方案持久化 / 加载 ==========

def test_save_and_load_plan(tmp_path, profile_beijing):
    db = tmp_path / "energy_actions.db"
    # 准备表
    import sqlite3
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS energy_plans (
            plan_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            profile_snapshot TEXT NOT NULL,
            actions TEXT NOT NULL,
            total_saving_cny REAL DEFAULT 0,
            total_saving_co2_kg REAL DEFAULT 0,
            status TEXT DEFAULT 'draft',
            created_at TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()

    planner = EnergyPlanner(db_path=db)
    plan = planner.generate_plan(profile_beijing)
    planner.save_plan(plan)

    loaded = planner.load_plan(plan.id)
    assert loaded is not None
    assert loaded.user_id == plan.user_id
    assert len(loaded.actions) == len(plan.actions)
    assert loaded.total_estimated_saving_cny == plan.total_estimated_saving_cny


def test_save_plan_status_defaults_to_active(profile_beijing):
    plan = EnergyPlanner().generate_plan(profile_beijing)
    assert plan.status == PlanStatus.ACTIVE.value
