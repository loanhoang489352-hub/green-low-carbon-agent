from copy import deepcopy
from types import SimpleNamespace

import pytest

from agent.core import GreenAgent
from agent.energy.models import HouseholdProfile
from agent.energy.personalization import resolve_profile, remember_confirmed
from agent.energy.planner import EnergyPlanner


class Manager:
    def __init__(self, data):
        self.data = deepcopy(data)

    def get_profile(self, uid, refresh=False):
        return deepcopy(self.data)

    def update_profile(self, uid, updates):
        self.data.update(deepcopy(updates))
        return True


def test_family_size_scales_shower_estimate():
    """审计#6 回归: 淋浴估算随家庭人数缩放;无模型的参考/定性动作不伪造人数乘数"""
    def profile(n):
        return HouseholdProfile(
            user_id="u", family_size=n, city="北京",
            appliances=["热水器", "洗衣机"], monthly_electricity_bill=200,
            monthly_water_bill=60, monthly_gas_bill=0, uses_gas=False,
            shower_minutes=10, shower_flow_lpm=9, showers_per_person_week=7,
            water_price_per_m3=4,
        )
    p1 = EnergyPlanner().generate_plan(profile(1))
    p8 = EnergyPlanner().generate_plan(profile(8))
    s1 = next(a for a in p1.actions if a.id == "water_bathing_shorter")
    s8 = next(a for a in p8.actions if a.id == "water_bathing_shorter")
    assert s1.estimate_kind == "calculated"
    # 人数 8 人 ≈ 8 倍用水/省钱(真正用人数驱动估算)
    assert s8.estimated_saving_water_m3 == pytest.approx(s1.estimated_saving_water_m3 * 8, rel=0.01)
    assert s8.estimated_saving_cny == pytest.approx(s1.estimated_saving_cny * 8, rel=0.01)
    # 无 per-person 模型的 action 保持诚实(reference 标注"不是实测",qualitative 不算金额)
    for p in (p1, p8):
        for a in p.actions:
            if a.estimate_kind == "reference":
                assert "不是实测" in (a.estimate_note or "")
            if a.estimate_kind == "qualitative":
                assert a.estimated_saving_cny == 0


def test_refresh_observes_form_updates_from_another_manager(tmp_path):
    from user_profile.user_profile import UserProfileManager
    path = str(tmp_path / 'profiles.db')
    reader, writer = UserProfileManager(path), UserProfileManager(path)
    reader.get_profile('alice')
    writer.update_basic_info('alice', {'family_type': '2'})
    current = reader.get_profile('alice', refresh=True)
    assert resolve_profile('alice', current)[0].family_size == 2


def test_main_profile_changes_replace_stale_household():
    old = HouseholdProfile.from_dict({'user_id': 'alice', 'family_size': 4,
        'appliances': ['燃气灶', '空调'], 'uses_gas': True})
    main = {'basic_info': {'family_type': '2', 'region': '上海'},
            'behavior_profile': {'home_energy_usage': {'appliances': ['冰箱'], 'uses_gas': False, 'monthly_gas_bill': 0}}}
    p, sources = resolve_profile('alice', main, old)
    assert p.family_size == 2 and p.city == 'shanghai'
    assert p.appliances == ['冰箱'] and p.monthly_gas_bill == 0
    assert not any(a.category == 'gas' for a in EnergyPlanner().generate_plan(p).actions)
    assert '用户填写' in sources['family_size']
    main['behavior_profile']['home_energy_usage']['appliances'] = []
    assert resolve_profile('alice', main, p)[0].appliances == []


def test_family_category_is_not_fabricated_number():
    for family in ['3-4', '5+']:
        p, _ = resolve_profile('a', {'basic_info': {'family_type': family}})
        assert p.family_size is None


def test_questions_do_not_create_devices_and_feedback_can_change():
    agent = GreenAgent.__new__(GreenAgent)
    assert 'appliances' not in agent._parse_household_hints('买空调能省电吗？')
    assert not agent._parse_household_hints('假如我家有燃气灶')
    hints = agent._parse_household_hints('我家没有空调和冰箱')
    assert set(hints['removed_appliances']) == {'空调', '冰箱'}
    p = HouseholdProfile.from_dict({'user_id': 'a', 'excluded_actions': ['water_bathing_shorter']})
    agent._merge_household_hints(p, agent._parse_household_hints('现在可以缩短洗澡时间'))
    assert p.excluded_actions == []


def test_conversation_feedback_persists_and_projects_to_wiki():
    manager = Manager({'user_id': 'alice', 'basic_info': {'family_type': '2'},
        'behavior_profile': {'home_energy_usage': {'appliances': ['洗衣机', '空调']}}})
    agent = GreenAgent.__new__(GreenAgent)
    p, _ = resolve_profile('alice', manager.data)
    hints = agent._parse_household_hints('我家现在3人，保持舒适优先，我已经一直满桶洗衣')
    p = agent._merge_household_hints(p, hints)
    assert remember_confirmed(manager, 'alice', p, hints)
    fresh, _ = resolve_profile('alice', manager.data)
    assert fresh.family_size == 3 and fresh.priority == 'comfort'
    actions = {a.id for a in EnergyPlanner().generate_plan(fresh).actions}
    assert not actions & {'washer_full_load', 'ac_temp_up_1c', 'water_bathing_shorter'}
    from user_profile.obsidian_export import _facts
    facts = _facts(manager.data, {})
    assert facts['家庭.priority']['status'] == '对话明确提供'
    assert '家庭.already_doing' in facts
    assert any(n['node_type'] == 'household_fact' for n in manager.data['graph']['nodes'])
    old_count = len(manager.data['graph']['nodes'])
    remember_confirmed(manager, 'alice', p, hints)
    assert len(manager.data['graph']['nodes']) == old_count
    # A later form edit is read immediately, and is not mislabeled as chat evidence.
    manager.data['behavior_profile']['home_energy_usage']['priority'] = 'money'
    assert resolve_profile('alice', manager.data)[0].priority == 'money'
    assert _facts(manager.data, {})['家庭.priority']['status'] == '未确认'


def test_energy_chat_uses_main_profile_without_new_page(monkeypatch):
    import agent.energy.household_store as store
    import agent.energy.delegation as delegation
    import agent.energy.weekly as weekly
    monkeypatch.setattr(store, 'load_profile', lambda uid: None)
    monkeypatch.setattr(store, 'save_profile', lambda *args: True)
    monkeypatch.setattr(store, 'save_plan_variant', lambda *args, **kw: True)
    monkeypatch.setattr(delegation, 'get_delegation_level', lambda uid: 1)
    monkeypatch.setattr(weekly.WeeklyEnergy, 'exclusions', lambda *args: [])
    agent = GreenAgent.__new__(GreenAgent)
    agent.profile_manager = Manager({'basic_info': {'family_type': '2'},
        'behavior_profile': {'home_energy_usage': {'appliances': ['冰箱'], 'uses_gas': False}}})
    result = agent._handle_energy_planning('alice', '帮我家庭节能', 'c1', None)
    assert '2人家庭' in result.message and '冰箱' in result.message
    assert '/energy.html' not in result.message
    assert '家里几个人' not in result.message
    monkeypatch.setattr(delegation, 'get_delegation_level', lambda uid: 3)
    before = deepcopy(agent.profile_manager.data)
    agent._handle_energy_planning('alice', '保持舒适优先', 'c1', None)
    assert agent.profile_manager.data == before


def test_react_energy_uses_same_profile_pipeline(monkeypatch, tmp_path):
    from agent.intent import IntentRecognizer
    import agent.energy.household_store as store
    monkeypatch.setenv('USE_REACT', 'true')
    monkeypatch.setattr(store, 'load_profile', lambda uid: None)
    agent = GreenAgent.__new__(GreenAgent)
    agent.intent_recognizer = IntentRecognizer()
    agent.active_conversations = {'c': SimpleNamespace(user_id='alice', last_domain='')}
    agent.user_conversations = {'alice': ['c']}
    agent._manage_conversation = lambda *args: 'c'
    from agent.understanding import DialogueStateStore
    agent._dialogue_store = DialogueStateStore(tmp_path / 'dialogue.db')
    agent._handle_energy_planning = lambda *args: SimpleNamespace(message='personalized', trace=[])
    agent.chat_react = lambda *args, **kw: (_ for _ in ()).throw(AssertionError('bypassed energy'))
    assert agent.chat_enhanced('alice', '帮我规划家庭节能', 'c').message == 'personalized'
