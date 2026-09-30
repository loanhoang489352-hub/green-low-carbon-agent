import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from agent.energy.models import EnergyAction, HouseholdProfile
from agent.energy.planner import EnergyPlanner
from agent.energy.jev_ranker import LABELS, rank_actions


def _actions():
    return [
        EnergyAction("ac_temp_up_1c", "electricity", "空调调高", "舒适时调高", 10, 20, 3, 1, "夏季", "standard:x"),
        EnergyAction("water_bathing_shorter", "water", "缩短淋浴", "尝试缩短", 0, 2, 0, 2, "随时", "standard:y"),
        EnergyAction("fridge_temp_setting", "electricity", "检查冰箱", "按说明书检查", 4, 8, 1, 1, "随时", "standard:z"),
    ]


def _answer(choice, probs=None, confidence=.95):
    probs = probs or {"fit": 0, "neutral": 0, "poor": 0, "unknown": 0}
    if probs == {"fit": 0, "neutral": 0, "poor": 0, "unknown": 0}:
        probs[choice] = 1
    return {"type": "choice", "choice": choice, "confidence": confidence, "probabilities": probs}


def _transport(choices, inspect=None, status=200):
    def handler(request):
        body = json.loads(request.content)
        if inspect:
            inspect(request, body)
        ids = list(body["questions"])
        payload = {"answers": {qid: _answer(choices[qid]) for qid in ids}}
        return httpx.Response(status, json=payload)
    return httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("JEV_ENERGY_RANKING_MODE", "off")
    monkeypatch.setenv("JEV_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MOCK", "false")
    # Prevent any test from opening a socket, including planner calls missing injection.
    real_client = httpx.Client
    def no_network_client(*args, **kwargs):
        kwargs.setdefault("transport", httpx.MockTransport(lambda request: (_ for _ in ()).throw(httpx.ConnectError("blocked test network", request=request))))
        return real_client(*args, **kwargs)
    monkeypatch.setattr(httpx, "Client", no_network_client)


def test_request_is_bounded_minimal_and_choice_batch(monkeypatch):
    monkeypatch.setenv("JEV_ENERGY_RANKING_MODE", "active")
    profile = HouseholdProfile(user_id="secret-user", city="private-city", appliances=["空调"])
    def inspect(request, body):
        assert request.url == "https://openrouter.ai/api/alpha/decisions"
        assert body["model"] == "typesafe/jev-1.13"
        assert len(body["questions"]) == 3
        assert set(body["state"]) == {"household", "actions"}
        serialized = json.dumps(body, ensure_ascii=False)
        assert "secret-user" not in serialized and "private-city" not in serialized
        assert "billing" not in serialized and all(set(q) == {"type", "instructions", "criteria"} and q["type"] == "choice" for q in body["questions"].values())
        instructions = [q["instructions"] for q in body["questions"].values()]
        assert len(set(instructions)) == 3 and all(f"state.actions[{i}]" in instructions[i] for i in range(3))
    choices = {"a0": "poor", "a1": "fit", "a2": "neutral"}
    out, applied = rank_actions(_actions(), profile, transport=_transport(choices, inspect))
    assert applied and [a.id for a in out] == ["water_bathing_shorter", "fridge_temp_setting", "ac_temp_up_1c"]


@pytest.mark.parametrize("bad", ["keys", "choice", "sum", "argmax", "confidence"])
def test_malformed_batch_falls_back_entirely(monkeypatch, bad):
    monkeypatch.setenv("JEV_ENERGY_RANKING_MODE", "active")
    actions = _actions()
    def handler(request):
        ids = list(json.loads(request.content)["questions"])
        answers = {qid: _answer("fit") for qid in ids}
        if bad == "keys": answers.pop("a2")
        if bad == "choice": answers["a1"]["choice"] = "invented"
        if bad == "sum": answers["a1"]["probabilities"]["fit"] = .7
        if bad == "argmax": answers["a1"]["probabilities"] = {"fit": .2, "neutral": .5, "poor": .2, "unknown": .1}
        if bad == "confidence": answers["a1"]["confidence"] = True
        return httpx.Response(200, json={"answers": answers})
    out, applied = rank_actions(actions, HouseholdProfile("uid"), transport=httpx.MockTransport(handler))
    assert out == actions and not applied and all(a.personalization_rank is None for a in actions)


@pytest.mark.parametrize("status", [429, 500])
def test_http_failure_fallback(monkeypatch, status):
    monkeypatch.setenv("JEV_ENERGY_RANKING_MODE", "active")
    actions = _actions()
    out, applied = rank_actions(actions, HouseholdProfile("uid"), transport=_transport({}, status=status))
    assert out == actions and not applied


def test_low_confidence_and_network_failure_fallback(monkeypatch):
    monkeypatch.setenv("JEV_ENERGY_RANKING_MODE", "active")
    actions = _actions()
    def low(request):
        ids = list(json.loads(request.content)["questions"])
        return httpx.Response(200, json={"answers": {qid: {**_answer("fit"), "confidence": .5} for qid in ids}})
    out, applied = rank_actions(actions, HouseholdProfile("uid"), transport=httpx.MockTransport(low))
    assert out == actions and not applied
    def failure(request): raise httpx.ConnectError("private details", request=request)
    out, applied = rank_actions(actions, HouseholdProfile("uid"), transport=httpx.MockTransport(failure))
    assert out == actions and not applied


def test_unknown_high_confidence_discards_entire_batch(monkeypatch):
    monkeypatch.setenv("JEV_ENERGY_RANKING_MODE", "active")
    actions = _actions()
    out, applied = rank_actions(actions, HouseholdProfile("uid"), transport=_transport({"a0": "fit", "a1": "unknown", "a2": "poor"}))
    assert out == actions and not applied
    assert all(a.personalization_rank is None for a in actions)


def test_timeout_falls_back(monkeypatch):
    monkeypatch.setenv("JEV_ENERGY_RANKING_MODE", "active")
    actions = _actions()
    def failure(request): raise httpx.ReadTimeout("timeout", request=request)
    out, applied = rank_actions(actions, HouseholdProfile("uid"), transport=httpx.MockTransport(failure))
    assert out == actions and not applied


def test_off_shadow_no_mutation_and_stable_ties(monkeypatch):
    actions = _actions()
    choices = {"a0": "fit", "a1": "fit", "a2": "fit"}
    out, applied = rank_actions(actions, HouseholdProfile("uid"), transport=_transport(choices))
    assert out == actions and not applied
    monkeypatch.setenv("JEV_ENERGY_RANKING_MODE", "shadow")
    out, applied = rank_actions(actions, HouseholdProfile("uid"), transport=_transport(choices))
    assert out == actions and not applied
    monkeypatch.setenv("JEV_ENERGY_RANKING_MODE", "active")
    out, applied = rank_actions(actions, HouseholdProfile("uid"), transport=_transport(choices))
    assert [a.id for a in out] == [a.id for a in actions]
    assert not applied


def test_money_priority_skips_semantic_sort(monkeypatch):
    monkeypatch.setenv("JEV_ENERGY_RANKING_MODE", "active")
    actions = _actions()
    out, applied = rank_actions(actions, HouseholdProfile("uid", priority="money"), transport=_transport({}))
    assert out == actions and not applied


def test_active_preserves_data_and_serialization_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("JEV_ENERGY_RANKING_MODE", "active")
    profile = HouseholdProfile("uid", appliances=["空调"], confirmed_fields=["appliances"])
    planner = EnergyPlanner(db_path=tmp_path / "energy.db")
    plan = planner.generate_plan(profile)
    # Test ranking directly with model choices to isolate the network boundary.
    baseline = _actions()
    snapshots = {a.id: a.to_dict().copy() for a in baseline}
    out, applied = rank_actions(baseline, profile, transport=_transport({"a0": "poor", "a1": "fit", "a2": "neutral"}))
    assert applied
    for action in out:
        for field in ("estimated_saving_cny", "estimated_saving_kwh", "estimated_saving_co2_kg", "source_ref", "description"):
            assert getattr(action, field) == snapshots[action.id][field]
    # Persist a plan with applied metadata; existing JSON storage includes new default field.
    plan.actions = out
    planner.db_path.parent.mkdir(parents=True, exist_ok=True)
    import sqlite3
    with sqlite3.connect(planner.db_path) as conn:
        conn.execute("CREATE TABLE energy_plans (plan_id TEXT PRIMARY KEY,user_id TEXT,profile_snapshot TEXT,actions TEXT,total_saving_cny REAL,total_saving_co2_kg REAL,status TEXT,created_at TEXT)")
    planner.save_plan(plan)
    loaded = planner.load_plan(plan.id)
    assert loaded and loaded.actions[0].personalization_rank["status"] == "applied"
    assert loaded.actions[0].id == "water_bathing_shorter"


@pytest.mark.parametrize("appliances, expected_first", [
    (["空调"], "ac_temp_up_1c"),
    (["节水花洒"], "water_bathing_shorter"),
])
def test_contrasting_confirmed_profiles_can_change_order(monkeypatch, appliances, expected_first):
    monkeypatch.setenv("JEV_ENERGY_RANKING_MODE", "active")
    actions = _actions()
    def handler(request):
        body = json.loads(request.content)
        facts = body["state"]["household"]
        assert facts["appliances"] == appliances
        first = "a1" if appliances == ["空调"] else "a0"
        ids = list(body["questions"])
        answers = {qid: _answer("poor" if qid == first else "neutral") for qid in ids}
        answers[first] = _answer("fit")
        return httpx.Response(200, json={"answers": answers})
    profile = HouseholdProfile("uid", appliances=appliances, confirmed_fields=["appliances"])
    baseline = [actions[1], actions[0], actions[2]] if appliances == ["空调"] else actions
    out, applied = rank_actions(baseline, profile,
                                transport=httpx.MockTransport(handler))
    assert applied and out[0].id == expected_first


def test_today_card_preserves_validated_order_only(monkeypatch):
    planner = EnergyPlanner()
    plan = planner.generate_plan(HouseholdProfile("uid"))
    original = list(plan.actions)
    for a in plan.actions:
        a.personalization_rank = {"status": "applied", "judgment": "fit", "confidence": .9, "score": .9}
    assert [a.id for a in planner.generate_today_card(plan).actions] == [a.id for a in original[:3]]
    for a in plan.actions:
        a.personalization_rank = None
    assert [a.id for a in planner.generate_today_card(plan).actions] == [a.id for a in sorted(original, key=lambda a: (a.difficulty, -a.estimated_saving_cny))[:3]]


def test_guard_exclusions_not_resurrected(monkeypatch):
    monkeypatch.setenv("JEV_ENERGY_RANKING_MODE", "active")
    p = HouseholdProfile("uid", appliances=["空调"], excluded_actions=["ac_temp_up_1c"],
                         monthly_water_bill=0, monthly_electricity_bill=200, monthly_gas_bill=0)
    baseline = EnergyPlanner().generate_plan(p)
    assert "ac_temp_up_1c" not in [a.id for a in baseline.actions]
    assert not baseline.blocked


def test_planner_integration_keeps_exclusions_totals_and_today_order(monkeypatch, tmp_path):
    monkeypatch.setenv("JEV_ENERGY_RANKING_MODE", "active")
    profile = HouseholdProfile("uid", appliances=["空调"], confirmed_fields=["appliances"],
        excluded_actions=["ac_temp_up_1c"])
    expected = EnergyPlanner(db_path=tmp_path / "base.db").generate_plan(profile)
    ids = [a.id for a in expected.actions]
    def handler(request):
        body = json.loads(request.content)
        assert "ac_temp_up_1c" not in [a["key"] for a in body["state"]["actions"]]
        answers = {qid: _answer("neutral") for qid in body["questions"]}
        return httpx.Response(200, json={"answers": answers})
    plan = EnergyPlanner(db_path=tmp_path / "ranked.db", ranking_transport=httpx.MockTransport(handler)).generate_plan(profile)
    assert [a.id for a in plan.actions] == ids
    assert all(a.personalization_rank and a.personalization_rank["status"] == "applied" for a in plan.actions)
    assert (plan.total_estimated_saving_cny, plan.total_estimated_saving_co2_kg) == (expected.total_estimated_saving_cny, expected.total_estimated_saving_co2_kg)
    assert [a.id for a in EnergyPlanner().generate_today_card(plan).actions] == ids[:3]
