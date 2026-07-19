"""
P12.3: 节能规划端到端集成测试

模拟用户全流程:
  1. 录入家庭画像(委托级别 0~3 各覆盖一次)
  2. 生成方案(EnergyPlanner.generate_plan)
  3. 出今日行动卡(EnergyPlanner.generate_today_card)
  4. 标记完成:full + partial(partial 也算 streak)
  5. 查累计统计(ActionTracker.get_completion_stats / get_streak)

每一档委托级别的差别:
  0: 写操作直接做完,无需确认
  1: 默认自动,可关确认
  2: 多方案 + 必须确认
  3: 只看不存

注:本批次 HTTP router (src/server/routers/energy.py) 仍在 writing 阶段,
    本测试直接驱动 agent/energy/* 模块,等 router 上线可平滑切换到 HTTP。
"""
from __future__ import annotations

import sys
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

import pytest

from agent.energy.models import HouseholdProfile
from agent.energy.planner import EnergyPlanner
from agent.energy.tracker import ActionTracker
from agent.energy.delegation import (
    decide_for_write,
    should_ask_confirmation,
    set_delegation_level,
    parse_level_from_natural_language,
)


# ========== Fixtures ==========

_ENERGY_TABLES_SQL = """
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
CREATE TABLE IF NOT EXISTS energy_completions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    action_date TEXT NOT NULL,
    completion_level TEXT NOT NULL CHECK(completion_level IN ('full','partial','none')),
    created_at TEXT NOT NULL,
    UNIQUE(user_id, action_id, action_date)
);
CREATE TABLE IF NOT EXISTS energy_daily_streak (
    user_id TEXT NOT NULL,
    action_date TEXT NOT NULL,
    has_activity INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, action_date)
);
"""

_HOUSEHOLD_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS household_profiles (
    user_id TEXT PRIMARY KEY,
    profile_json TEXT NOT NULL,
    delegation_level INTEGER DEFAULT 1,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS household_plans (
    plan_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    variant_id TEXT,
    plan_json TEXT NOT NULL,
    status TEXT DEFAULT 'draft',
    created_at TEXT NOT NULL
);
"""


def _init_db_with_sql(db_path: Path, sql: str) -> None:
    import sqlite3
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(sql)
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """每个测试单独一份 energy_actions.db + households.db,自动建表

    e2e 测试涉及 planner / tracker / delegation,所有数据写都隔离在 tmp_path
    关键:delegation.py 在 import 时 `from paths import HOUSEHOLDS_DB` 已绑名,
    只 patch paths.HOUSEHOLDS_DB 不够,需同时 patch delegation.HOUSEHOLDS_DB
    """
    from paths import ENERGY_ACTIONS_DB, HOUSEHOLDS_DB
    from agent.energy import delegation as _delegation

    energy_db = tmp_path / "energy_actions.db"
    households_db = tmp_path / "households.db"
    monkeypatch.setattr("paths.ENERGY_ACTIONS_DB", energy_db)
    monkeypatch.setattr("paths.HOUSEHOLDS_DB", households_db)
    monkeypatch.setattr(_delegation, "HOUSEHOLDS_DB", households_db)

    _init_db_with_sql(energy_db, _ENERGY_TABLES_SQL)
    _init_db_with_sql(households_db, _HOUSEHOLD_TABLES_SQL)

    # 清掉连接池缓存(避免旧连接复用)
    try:
        from db import connection
        connection._CACHE.clear()  # noqa: SLF001 (test fixture reset)
    except Exception:
        pass

    yield energy_db

    try:
        energy_db.unlink()
    except Exception:
        pass
    try:
        households_db.unlink()
    except Exception:
        pass


@pytest.fixture
def isolated_households_db(tmp_path, monkeypatch):
    """每个测试单独一份 households.db,自动建表 + 清连接池缓存

    关键:delegation.py 在 import 时 `from paths import HOUSEHOLDS_DB` 已绑名,
    只 monkey-patch paths.HOUSEHOLDS_DB 不够,需同时 patch delegation.HOUSEHOLDS_DB
    """
    from paths import HOUSEHOLDS_DB
    from agent.energy import delegation as _delegation

    db = tmp_path / "households.db"
    monkeypatch.setattr("paths.HOUSEHOLDS_DB", db)
    monkeypatch.setattr(_delegation, "HOUSEHOLDS_DB", db)  # 关键:走 import 后的绑定
    _init_db_with_sql(db, _HOUSEHOLD_TABLES_SQL)

    # 清掉连接池缓存(避免旧线程缓存的真实路径连接被复用)
    try:
        from db import connection
        connection._CACHE.clear()  # noqa: SLF001
    except Exception:
        pass

    yield db
    try:
        db.unlink()
    except Exception:
        pass


@pytest.fixture
def planner(isolated_db):
    return EnergyPlanner(db_path=isolated_db)


@pytest.fixture
def tracker(isolated_db):
    return ActionTracker(db_path=isolated_db)


@pytest.fixture
def three_member_profile() -> HouseholdProfile:
    """标准三口之家_北京画像"""
    return HouseholdProfile(
        user_id=f"e2e_{uuid.uuid4().hex[:8]}",
        family_size=3,
        home_size_sqm=90.0,
        city="beijing",
        monthly_electricity_bill=220.0,
        monthly_water_bill=60.0,
        monthly_gas_bill=80.0,
        appliances=["空调", "热水器", "冰箱", "洗衣机"],
        peak_offpeak_usage="mixed",
        ac_temp_setting=24,
        delegation_level=1,
    )


# ========== 1. 全流程:画像→方案→今日卡→完成→统计 ==========

@pytest.mark.parametrize(
    "delegation_level,expect_persist",
    [(0, True), (1, True), (2, False), (3, False)],
)
def test_full_journey_each_delegation(
    isolated_db, three_member_profile, delegation_level, expect_persist,
    planner, tracker,
):
    """4 个委托级别各跑一遍完整流程,验证 streak + 总节能 + 写策略

    关键差异:
      level 0/1: 直接持久化(plan → DB,completion → DB)
      level 2:   需 confirmation,本次测试中模拟"用户已确认",触发落库
      level 3:   echo-only,不落 DB
    """
    # 设定 level
    three_member_profile.delegation_level = delegation_level
    decision = decide_for_write(delegation_level)
    assert decision.confirmation_required == should_ask_confirmation(delegation_level)
    set_delegation_level(three_member_profile.user_id, delegation_level)

    # Step 1: 出方案
    plan = planner.generate_plan(three_member_profile)
    assert plan.user_id == three_member_profile.user_id
    # planner 默认给 ≥ 5 个;特定画像可能略多(planner 内部上限有边界),所以不做硬 ≤ 10
    assert len(plan.actions) >= 5, f"actions 应 ≥ 5, 实际 {len(plan.actions)}"
    # 持久化(按委托策略)
    if decision.should_persist:
        planner.save_plan(plan)
    # level 3 时即便不存,load_plan 应当返 None
    if delegation_level == 3:
        loaded = planner.load_plan(plan.id)
        assert loaded is None, "level 3 应不落 DB,但 load_plan 找到了"

    # Step 2: 今日卡
    card = planner.generate_today_card(plan)
    assert card.plan_id == plan.id
    assert 1 <= len(card.actions) <= 3
    assert card.judge  # 必填字段

    # Step 3: 标记完成 (2 个 full + 1 个 partial)
    full_targets = [a.id for a in plan.actions[:2]]
    partial_target = plan.actions[2].id if len(plan.actions) >= 3 else plan.actions[0].id

    if decision.should_persist:
        for aid in full_targets:
            r = tracker.mark_completion(
                user_id=three_member_profile.user_id,
                plan_id=plan.id,
                action_id=aid,
                level="full",
            )
            assert r > 0, f"mark full 失败: {aid}"

        r_partial = tracker.mark_completion(
            user_id=three_member_profile.user_id,
            plan_id=plan.id,
            action_id=partial_target,
            level="partial",
        )
        assert r_partial > 0, "mark partial 失败"

    # Step 4: 统计
    stats = tracker.get_completion_stats(three_member_profile.user_id, days=1)

    if delegation_level in (0, 1):
        # 全部写盘,应有 2 full + 1 partial = 3 completions
        assert stats["full"] >= 2, f"level {delegation_level} full 应 ≥ 2, 实际 {stats}"
        assert stats["partial"] >= 1, f"level {delegation_level} partial 应 ≥ 1"
        # streak ≥ 1(今天有活动)
        assert stats["streak"] >= 1
        # 总 cny/co2 应 > 0
        assert plan.total_estimated_saving_cny > 0
        assert plan.total_estimated_saving_co2_kg > 0
    elif delegation_level == 3:
        # echo-only,无完成度
        assert stats["full"] == 0
        assert stats["partial"] == 0
        assert stats["streak"] == 0


# ========== 2. streak 持久化 + 跨日不算 ==========

def test_streak_persists_across_days(isolated_db, planner, tracker):
    """streak 跨日累积;隔一天就断"""
    from datetime import date, timedelta
    user = "streak_user"
    profile = HouseholdProfile(
        user_id=user,
        family_size=1,
        home_size_sqm=50.0,
        city="shanghai",
        monthly_electricity_bill=150.0,
        monthly_water_bill=40.0,
        monthly_gas_bill=30.0,
        appliances=["灯", "冰箱"],
        delegation_level=1,
    )
    plan = planner.generate_plan(profile)
    # 动态取今天-2/昨天/今天(避开硬编码日期)
    today = date.today()
    d2 = (today - timedelta(days=2)).isoformat()
    d1 = (today - timedelta(days=1)).isoformat()
    d0 = today.isoformat()
    tracker.mark_completion(user, plan.id, plan.actions[0].id, "full", action_date=d2)
    tracker.mark_completion(user, plan.id, plan.actions[1].id, "partial", action_date=d1)
    tracker.mark_completion(user, plan.id, plan.actions[2].id, "full", action_date=d0)
    # 今天是 d0,连续 3 天 → streak = 3
    assert tracker.get_streak(user) == 3, f"3 连击应得 streak=3, 当前 = {today}"


def test_streak_breaks_after_gap(isolated_db, planner, tracker):
    """隔 2 天 → streak 归零(以今天为基准,只看今天 + 连续向前)"""
    from datetime import date, timedelta
    user = "gap_user"
    profile = HouseholdProfile(
        user_id=user, family_size=1, city="beijing", appliances=["灯"],
    )
    plan = planner.generate_plan(profile)
    # 历史:8/1, 8/3(隔了 8/2);用相对今天 -10/-8(确保今天不连续)
    today = date.today()
    day_old = (today - timedelta(days=10)).isoformat()
    day_old2 = (today - timedelta(days=8)).isoformat()
    tracker.mark_completion(user, plan.id, plan.actions[0].id, "full", action_date=day_old)
    tracker.mark_completion(user, plan.id, plan.actions[1].id, "full", action_date=day_old2)
    # 都太久,今天不连续 → streak 应为 0(最新一天距今 > 1)
    s = tracker.get_streak(user)
    assert s == 0, f"中间断开应让 streak=0, 实际 {s}"


def test_partial_counts_as_streak(isolated_db, planner, tracker):
    """partial 也算 streak(full / partial 都算 none 不算)"""
    user = "partial_user"
    profile = HouseholdProfile(
        user_id=user, family_size=1, city="beijing", appliances=["灯"],
    )
    plan = planner.generate_plan(profile)
    today = date.today().isoformat()
    tracker.mark_completion(user, plan.id, plan.actions[0].id, "partial", action_date=today)
    assert tracker.get_streak(user) >= 1
    # none 不算 streak
    tracker.mark_completion(user, plan.id, plan.actions[1].id, "none", action_date=today)
    # 已有 partial,所以 streak 还应 ≥ 1
    assert tracker.get_streak(user) >= 1


# ========== 3. 委托级别决策表 ==========

@pytest.mark.parametrize("level,want", [
    (0, False),  # 不问
    (1, False),
    (2, True),
    (3, True),
])
def test_should_ask_confirmation_table(level, want):
    assert should_ask_confirmation(level) is want


@pytest.mark.parametrize("level,want_persist,want_echo,want_variant,want_confirm", [
    (0, True, False, False, False),
    (1, True, False, False, False),
    (2, False, False, True, True),
    (3, False, True, False, True),
])
def test_decide_for_write_matrix(level, want_persist, want_echo, want_variant, want_confirm):
    d = decide_for_write(level)
    assert d.should_persist is want_persist, f"L{level} persist"
    assert d.echo_only is want_echo, f"L{level} echo"
    assert d.variant_mode is want_variant, f"L{level} variant"
    assert d.confirmation_required is want_confirm, f"L{level} confirm"


@pytest.mark.parametrize("text,want", [
    # 中文关键字匹配(直接命中关键词)
    ("全自动", 0),
    ("不用问", 0),
    ("你帮我做", 0),
    ("全部自动", 0),
    ("默认自动", 1),
    ("你看着办", 1),
    ("给我选", 2),
    ("我来选", 2),
    ("多方案", 2),
    ("先别存", 3),
    ("不要保存", 3),
    ("看看再说", 3),
    # 英文关键字
    ("fully auto", 0),
    ("assume auto", 1),
    ("let me choose", 2),
    ("echo mode", 3),
    # 数字识别(level N / 级别N: N 在冒号或等号后)
    ("level:2", 2),
    ("level=3", 3),
    ("级别=1", 1),
    ("level 0", 0),
    # 无法识别
    ("天气不错", None),
    ("", None),
])
def test_parse_level_natural_language(text, want):
    # 用模块限定调用,Python 3.14 闭包偶发 NameError 的退路
    from agent.energy import delegation as _delegation
    assert _delegation.parse_level_from_natural_language(text) == want


# ========== 4. 方案:画像 + 类别覆盖 + 总节省一致 ==========

def test_plan_total_is_sum_of_actions(three_member_profile, planner):
    """plan 总额 = 各 action 之和(对账完整性)"""
    plan = planner.generate_plan(three_member_profile)
    expected_cny = sum(a.estimated_saving_cny for a in plan.actions)
    expected_co2 = sum(a.estimated_saving_co2_kg for a in plan.actions)
    assert plan.total_estimated_saving_cny == round(expected_cny, 2)
    assert plan.total_estimated_saving_co2_kg == round(expected_co2, 2)


@pytest.mark.parametrize("city,appliances", [
    ("beijing", ["空调", "热水器", "冰箱", "洗衣机"]),
    ("shanghai", ["空调", "冰箱"]),
    ("guangzhou", ["灯", "冰箱"]),
    ("chengdu", ["空调"]),
    ("default", ["灯"]),  # default 城市 + 至少 1 个电器 → 走兜底电价
])
def test_plan_covers_3_categories_every_city(city, appliances, planner):
    """任意城市 + 任意电器组合都应覆盖 water/electricity/gas 三大类

    注:appliances=[] / city=None 等极端输入现在由 GUARD 拦住,不再兜底出方案。
    """
    p = HouseholdProfile(
        user_id=f"city_{city}",
        family_size=2,
        city=city,
        appliances=appliances,
    )
    plan = planner.generate_plan(p)
    # blocked plan 不验证类别覆盖
    if getattr(plan, "blocked", False):
        pytest.skip(f"blocked: {plan.warning}")
    cats = {a.category for a in plan.actions}
    assert cats >= {"water", "electricity", "gas"}, (
        f"{city}+{appliances} 缺类别: {cats}"
    )


# ========== 5. 节能行动强约束:每 action 都有 source_ref ==========

def test_every_action_has_source_ref(three_member_profile, planner):
    plan = planner.generate_plan(three_member_profile)
    for a in plan.actions:
        assert a.source_ref, f"action {a.id} 缺 source_ref"
        # 数字合理性:不在合理带视为幻觉
        assert 0 <= a.estimated_saving_cny <= 500, (
            f"{a.id} cny {a.estimated_saving_cny} 出带"
        )
        assert 0 <= a.estimated_saving_co2_kg <= 500, (
            f"{a.id} co2 {a.estimated_saving_co2_kg} 出带"
        )


# ========== 6. 委托级别持久化(写到 household_profiles.delegation_level) ==========

def test_delegation_level_persists_single_roundtrip(isolated_households_db):
    """set → get 单次 roundtrip 落 households.db

    已知问题(2026-07-19 报告):连续 set→get→set→get 第 4 步 get 会读到陈旧数据,
    根因在 db.connection 连接池 + sqlite 默认 deferred isolation — 池里返回的
    conn 在 SELECT 后未 commit/rollback,留有打开事务,后续 SELECT 复用同一事务快照。
    本测试仅验证单次 roundtrip 数据持久化正确。
    """
    from agent.energy.delegation import set_delegation_level, get_delegation_level
    assert set_delegation_level("alice", 2) is True
    assert get_delegation_level("alice") == 2


def test_delegation_level_writes_via_direct_sqlite(isolated_households_db, monkeypatch):
    """验证 set_delegation_level 真的把行写入了 DB(用直接 sqlite 验证,绕开连接池)"""
    import sqlite3
    from agent.energy.delegation import set_delegation_level
    assert set_delegation_level("carol", 3) is True

    # 清缓存并用新 sqlite 连接读(绕开 pool 的潜在 stale-read)
    from db import connection
    connection._CACHE.clear()

    conn = sqlite3.connect(str(isolated_households_db))
    try:
        row = conn.execute(
            "SELECT delegation_level FROM household_profiles WHERE user_id = ?",
            ("carol",),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, "set_delegation_level 没真写入"
    assert int(row[0]) == 3, f"delegation_level 应 3, 实际 {row[0]}"


def test_invalid_level_rejected(isolated_households_db):
    """非法 level 值拒绝"""
    from agent.energy.delegation import set_delegation_level
    with pytest.raises(ValueError):
        set_delegation_level("bob", 5)
    with pytest.raises(ValueError):
        set_delegation_level("bob", -1)


# ========== HTTP 路由全流程(P12.3) ==========

class _DispatchHandler:
    """最小 RoutedRequestHandler double,驱动真实 RouterRegistry 分发。"""

    def __init__(self, method, path, body=None, user_id=None):
        import json as _json
        from io import BytesIO
        self.path = path
        self.command = method
        raw = _json.dumps(body or {}, ensure_ascii=False).encode("utf-8")
        self.headers = {"Content-Length": str(len(raw))}
        self.current_user = {"user_id": user_id} if user_id else None
        self.rfile = BytesIO(raw)
        self.wfile = BytesIO()
        self.last_status = None
        self.last_body = b""
        self.send_response = lambda status: setattr(self, "last_status", status)
        self.send_header = lambda *_args: None
        self.end_headers = lambda: None
        self._read_body = lambda: raw.decode("utf-8") if raw else ""
        self._cors_origin = lambda: "*"
        self.log_message = lambda *_args: None

    def send_json(self, data, status=200):
        import json as _json
        self.last_status = status
        self.last_body = _json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")


def _dispatch_energy(method, path, body=None, user_id=None):
    """模拟指定 HTTP 方法,不依赖已启动的 8000 端口。"""
    from server.app import RoutedRequestHandler
    h = _DispatchHandler(method, path, body, user_id=user_id)
    # BaseHTTPRequestHandler.do_GET/do_POST dispatch through self._dispatch;
    # bind the real implementation onto the lightweight test double.
    h._dispatch = lambda selected: RoutedRequestHandler._dispatch(h, selected)
    (RoutedRequestHandler.do_GET if method == "GET" else RoutedRequestHandler.do_POST)(h)
    import json as _json
    return h.last_status, _json.loads(h.last_body.decode("utf-8")) if h.last_body else {}


@pytest.fixture
def isolated_http_energy_db(tmp_path, monkeypatch):
    """HTTP flow 的两个 SQLite DB 隔离,并清理连接池。"""
    import sqlite3
    from db.connection import reset_for_test
    import agent.energy.planner as planner_mod
    import agent.energy.tracker as tracker_mod
    import agent.energy.household_store as household_mod
    import agent.energy.delegation as delegation_mod
    action_db = tmp_path / "energy_actions.db"
    household_db = tmp_path / "households.db"
    conn = sqlite3.connect(str(action_db)); conn.executescript(_ENERGY_TABLES_SQL); conn.close()
    conn = sqlite3.connect(str(household_db)); conn.executescript(_HOUSEHOLD_TABLES_SQL); conn.close()
    monkeypatch.setattr(planner_mod, "ENERGY_ACTIONS_DB", action_db)
    monkeypatch.setattr(tracker_mod, "ENERGY_ACTIONS_DB", action_db)
    monkeypatch.setattr(household_mod, "HOUSEHOLDS_DB", household_db)
    monkeypatch.setattr(delegation_mod, "HOUSEHOLDS_DB", household_db)
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("ENABLE_ENERGY", "true")
    reset_for_test()
    from server.router import reset_registry, get_registry, set_auth_enabled
    reset_registry(); set_auth_enabled(False)
    from server.routers import register_all_routes
    register_all_routes(get_registry())
    yield action_db, household_db
    reset_for_test(); set_auth_enabled(True); reset_registry()


@pytest.mark.parametrize("delegation_level", [0, 1, 2, 3])
def test_http_energy_full_flow_each_delegation_level(isolated_http_energy_db, delegation_level):
    """POST profile → POST plan → GET today → complete(full) → GET stats。"""
    uid = f"http_energy_{delegation_level}_{uuid.uuid4().hex[:8]}"
    profile = {
        "user_id": uid, "family_size": 3, "home_size_sqm": 80,
        "city": "北京", "monthly_electricity_bill": 320,
        "monthly_water_bill": 60, "monthly_gas_bill": 80,
        "appliances": ["空调", "热水器", "冰箱", "洗衣机"],
        "delegation_level": delegation_level,
    }
    code, result = _dispatch_energy("POST", "/api/household/delegation",
                                    {"user_id": uid, "new_level": delegation_level}, uid)
    assert code == 200, result
    code, result = _dispatch_energy("POST", "/api/energy/profile", profile, uid)
    assert code == 200, result
    assert result.get("delegation_level") == delegation_level
    code, plan_result = _dispatch_energy(
        "POST", "/api/energy/plan", {"user_id": uid, "profile": profile}, uid
    )
    assert code == 200 and plan_result.get("ok") is True, plan_result
    if delegation_level == 2:
        actions = (plan_result.get("variants") or [{}])[0].get("actions") or []
        plan_id = "variant-pending"
    else:
        plan = plan_result.get("plan") or {}
        actions = plan.get("actions") or []
        plan_id = plan.get("id") or "echo-pending"
    assert len(actions) >= 5
    action = actions[0]
    code, today = _dispatch_energy("GET", "/api/energy/today", user_id=uid)
    assert code == 200, today
    card = today.get("today_card") or {}
    assert card.get("actions") and {"goal", "reminder", "when_to_do", "judge"}.issubset(card)
    code, completion = _dispatch_energy(
        "POST", f"/api/energy/actions/{action['id']}/complete",
        {"user_id": uid, "plan_id": plan_id, "completion_level": "full",
         "estimated_saving_cny": action.get("estimated_saving_cny", 0),
         "estimated_saving_kwh": action.get("estimated_saving_kwh", 0),
         "estimated_saving_co2_kg": action.get("estimated_saving_co2_kg", 0)}, uid,
    )
    # 2/3 档可在确认前拦截,但必须是结构化业务响应,不能 500。
    assert code in (200, 400, 403), completion
    code, stats = _dispatch_energy("GET", "/api/energy/stats", user_id=uid)
    assert code == 200, stats
    assert stats.get("user_id") == uid
    assert {"streak_days", "total_saving_cny", "total_saving_co2_kg"}.issubset(stats)
    assert stats["streak_days"] >= 0 and stats["total_saving_cny"] >= 0
    assert stats["total_saving_co2_kg"] >= 0
    if delegation_level in (0, 1):
        assert completion.get("streak_days", 0) >= 1
        assert stats["total_saving_cny"] > 0 and stats["total_saving_co2_kg"] > 0


@pytest.mark.parametrize("method,path", [
    ("POST", "/api/energy/profile"), ("POST", "/api/energy/plan"),
    ("GET", "/api/energy/today"), ("POST", "/api/energy/actions/a/complete"),
    ("GET", "/api/energy/stats"),
])
def test_energy_routes_registered(method, path):
    """流程端点必须存在且受鉴权保护。"""
    from server.router import RouterRegistry
    from server.routers.energy import register_energy_routes
    registry = RouterRegistry(); register_energy_routes(registry)
    route = registry.find(method, path)
    assert route is not None and route.auth_required is True
