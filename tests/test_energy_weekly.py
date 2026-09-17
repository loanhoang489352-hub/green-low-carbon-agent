from contextlib import closing
from datetime import date, timedelta
import json
import sqlite3
from types import SimpleNamespace

import pytest

from agent.energy.models import HouseholdProfile
from agent.energy.planner import EnergyPlanner
from agent.energy.weekly import WeeklyEnergy


def profile(**kwargs):
    return HouseholdProfile.from_dict({"user_id": "alice", "family_size": 3,
        "appliances": ["空调", "冰箱", "洗衣机", "灯"], "uses_gas": False, **kwargs})


def test_no_invented_profile_at_boundary():
    p = HouseholdProfile.from_dict({"user_id": "alice"})
    assert p.family_size is None and p.appliances == [] and p.monthly_gas_bill is None
    assert EnergyPlanner().generate_plan(p).blocked


def test_chat_intake_preserves_zero_and_negative_device_statements():
    from agent.core import GreenAgent
    agent = GreenAgent.__new__(GreenAgent)
    p = HouseholdProfile.from_dict({"user_id": "alice"})
    p = agent._merge_household_hints(p, agent._parse_household_hints("3人，有冰箱和电热水器，不用燃气，燃气费0元"))
    assert p.family_size == 3 and p.monthly_gas_bill == 0 and p.uses_gas is False
    assert p.appliances == ["电热水器", "冰箱"]
    assert p.city == "" and p.monthly_electricity_bill is None
    p = agent._merge_household_hints(p, agent._parse_household_hints("没有电热水器"))
    assert "电热水器" not in p.appliances


def test_applicability_and_annual_reference():
    planner = EnergyPlanner()
    plan = planner.generate_plan(profile(ac_temp_setting=28, has_incandescent=False, has_drip=False))
    ids = {a.id for a in plan.actions}
    assert not plan.blocked
    assert not {"ac_temp_up_1c", "led_replace_incandescent", "water_repair_drip"} & ids
    assert not any(a.category == "gas" for a in plan.actions)
    washer = next(a for a in plan.actions if a.id == "washer_full_load")
    assert washer.estimate_period == "year" and washer.estimated_saving_kwh == 50
    fridge = next(a for a in plan.actions if a.id == "fridge_temp_setting")
    assert fridge.estimate_kind == "qualitative" and fridge.estimated_saving_cny == 0
    assert "省 " not in planner.generate_today_card(plan).goal


def test_shower_model_responds_to_family_and_habits():
    planner = EnergyPlanner()
    args = dict(shower_minutes=10, shower_flow_lpm=8, showers_per_person_week=7, water_price_per_m3=5)
    a = next(x for x in planner.generate_plan(profile(family_size=1, **args)).actions if x.id == "water_bathing_shorter")
    b = next(x for x in planner.generate_plan(profile(family_size=3, **args)).actions if x.id == "water_bathing_shorter")
    assert b.estimated_saving_water_m3 == round(3 * 8 * 7 * 52 / 1000, 3)
    assert b.estimated_saving_cny == round(a.estimated_saving_cny * 3, 2)
    assert b.estimated_saving_co2_kg == 0 and b.estimate_kind == "calculated"
    assert "52" in b.estimate_note


@pytest.mark.parametrize("kwargs", [{"family_size": 0}, {"family_size": 2.5}, {"shower_flow_lpm": float("nan")}, {"monthly_gas_bill": -1}, {"appliances": "冰箱"}, {"uses_gas": "false"}])
def test_invalid_inputs_block_without_exception(kwargs):
    assert EnergyPlanner().generate_plan(profile(**kwargs)).blocked


def test_week_idempotent_and_correctable(tmp_path):
    service = WeeklyEnergy(tmp_path / "week.db")
    plan = EnergyPlanner().generate_plan(profile())
    today = date(2026, 9, 8)
    aid = plan.actions[0].id
    started = service.start("alice", plan, [aid], today)["week"]
    assert service.start("alice", plan, [aid], today)["week"]["week_id"] == started["week_id"]
    for _ in range(2):
        result = service.feedback("alice", started["week_id"], aid, "full", "unsupported", today=today)["week"]
    assert result["record_count"] == 1 and result["active_days"] == 1
    assert result["verified_savings"] is None
    assert aid in service.exclusions("alice")
    result = service.feedback("alice", started["week_id"], aid, "none", "forgot", today=today)["week"]
    assert result["active_days"] == 0 and result["barriers"]["unsupported"] == 0
    assert aid not in service.exclusions("alice")
    assert any("习惯" in x for x in result["next_week_suggestions"])


def test_week_owner_and_date_boundaries(tmp_path):
    service = WeeklyEnergy(tmp_path / "week.db")
    plan = EnergyPlanner().generate_plan(profile())
    day = date(2026, 9, 8)
    aid = plan.actions[0].id
    week = service.start("alice", plan, [aid], day)["week"]
    for user, action, dt in [("bob", aid, str(day)), ("alice", "unknown", str(day)),
                             ("alice", aid, str(day + timedelta(days=1))), ("alice", aid, "2026-09-07")]:
        with pytest.raises(ValueError):
            service.feedback(user, week["week_id"], action, "full", action_date=dt, today=day)
    assert service.get("bob")["week"] is None


def test_next_week_archives_previous(tmp_path):
    service = WeeklyEnergy(tmp_path / "week.db")
    plan = EnergyPlanner().generate_plan(profile())
    day = date(2026, 9, 8)
    aid = plan.actions[0].id
    week = service.start("alice", plan, [aid], day)["week"]
    assert service.get("alice", day + timedelta(days=7))["week"]["completed"]
    new = service.start("alice", plan, [aid], day + timedelta(days=7))["week"]
    assert new["week_id"] != week["week_id"]
    with closing(sqlite3.connect(service.db_path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM energy_week_history").fetchone()[0] == 1


def test_route_generation_start_feedback_today(tmp_path, monkeypatch):
    from server.routers.energy import register_energy_routes
    import agent.energy.household_store as hs
    import agent.energy.weekly as weekly
    import agent.energy.delegation as delegation
    db = tmp_path / "households.db"
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("CREATE TABLE household_plans (plan_id TEXT PRIMARY KEY, user_id TEXT, variant_id TEXT, plan_json TEXT, status TEXT, created_at TEXT)")
    connections = []
    def connection():
        c = sqlite3.connect(db); c.row_factory = sqlite3.Row; connections.append(c); return c
    monkeypatch.setattr(hs, "_get_conn", connection)
    monkeypatch.setattr(weekly, "HOUSEHOLDS_DB", db)
    monkeypatch.setattr(delegation, "get_delegation_level", lambda uid: 1)
    monkeypatch.setattr("server.routers.energy._audit", lambda *a, **k: None)
    routes = {}
    registry = SimpleNamespace(add_route=lambda method, path, fn, **kw: routes.update({(method, path): (fn, kw)}))
    register_energy_routes(registry)
    def call(method, path, data, user="alice"):
        handler = SimpleNamespace(current_user={"user_id": user}, command=method, path=path)
        handler.send_json = lambda value: setattr(handler, "result", value)
        fn, options = routes[method, path]
        assert options["auth_required"] is True
        fn(handler, data)
        return handler.result
    try:
        result = call("POST", "/api/energy/plan", {"profile": profile().to_dict(), "user_id": "bob"})
        plan = result["plan"]
        assert plan["user_id"] == "alice" and plan["status"] == "draft"
        week = call("POST", "/api/energy/week", {"plan_id": plan["id"], "action_ids": [plan["actions"][0]["id"]]})["week"]
        today = call("GET", "/api/energy/today", {})
        assert today["plan_id"] == plan["id"] and len(today["today_card"]["actions"]) == 1
        result = call("POST", "/api/energy/week/feedback", {"week_id": week["week_id"], "action_id": plan["actions"][0]["id"], "level": "partial", "barrier": "comfort"})
        assert result["week"]["active_days"] == 1
        from server.errors import APIError
        with pytest.raises(APIError):
            call("POST", "/api/energy/week", {"plan_id": plan["id"], "action_ids": [plan["actions"][0]["id"]]}, "bob")
    finally:
        for c in connections: c.close()
