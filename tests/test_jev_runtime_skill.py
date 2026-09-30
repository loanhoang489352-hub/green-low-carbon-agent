import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.routing.demand import Demand
from agent.skills import SkillContext, SkillExecutor
from agent.tools.registry import ToolRegistry
from plugin_system.loader import PluginAPI
from server.router import RouterRegistry


@pytest.fixture
def plugin(monkeypatch):
    spec = importlib.util.spec_from_file_location('jev_skill_test', Path(__file__).parents[1] / 'plugins/jev_skill.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv('JEV_PROVIDER', 'openrouter')
    monkeypatch.setenv('JEV_ROUTING_MODE', 'active')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-key-never-return')
    monkeypatch.setenv('LLM_MOCK', 'false')
    monkeypatch.setenv('UNDERSTANDING_MODE', 'hybrid')
    return module


def test_official_skill_and_runtime_registered(plugin, monkeypatch):
    tools, skills, routes = ToolRegistry(), SkillExecutor(), RouterRegistry()
    monkeypatch.setattr(plugin.JevRoutingSkill, 'write_skill_md', lambda self: None)
    plugin.register(PluginAPI(tools, skills, routes))
    assert tools.get('jev_route') and skills.get('jev-decision').validate() == []
    guide = tools.get('jev_route').execute(operation='guide')
    assert guide.success and 'name: typesafe-ai' in guide.data['instructions']
    assert 'Code owns the workflow' in guide.data['instructions']
    assert 'Choice: demand routing' in guide.data['implemented']
    route = routes.find('GET', '/api/jev/status')
    assert route.auth_required
    received = []
    route.handler(SimpleNamespace(send_json=received.append))
    assert received[0]['key_configured'] and received[0]['skill_installed']
    assert received[0]['network_verified'] is False
    assert 'test-key-never-return' not in json.dumps(received)


def test_runtime_tool_is_visible_to_react_prompt(plugin, monkeypatch):
    import agent.tools
    from agent.core import GreenAgent
    registry = ToolRegistry()
    registry.register(plugin.JevRouteTool())
    monkeypatch.setattr(agent.tools, 'get_registry', lambda: registry)
    prompt = GreenAgent.__new__(GreenAgent)._react_system_prompt()
    assert 'jev_route' in prompt and 'operation=guide' in prompt
    assert '概率不是事实证据' in prompt


def test_skill_executes_shared_backend_without_profile_or_identity(plugin, monkeypatch):
    calls = []
    def propose(message, state):
        calls.append((message, state))
        return Demand(domain='energy', act='plan', intent='energy_planning', source='jev')
    monkeypatch.setattr(plugin.jev, 'propose', propose)
    skill = plugin.JevRoutingSkill()
    for uid in ('alice', 'bob'):
        result = skill.execute(SkillContext(user_id=uid, message='给我家节能建议',
                                          profile={'secret': 'do-not-send'}))
        assert result.success and result.data['source'] == 'jev'
        assert result.metadata['advisory_only'] is True
    assert calls == [('给我家节能建议', {})] * 2


@pytest.mark.parametrize('arguments', [
    {'operation': 'shell'}, {'message': ''}, {'message': 'x' * 6001},
    {'message': 'hi', 'state': {'user_id': 'bob'}},
    {'message': 'hi', 'state': {'active_domain': 'invalid'}},
    {'message': 'hi', 'state': {'recent': 'not-a-list'}},
    {'message': 'hi', 'state': {'expected_slot': {'secret': 1}}},
    {'message': 'hi', 'api_key': 'must-not-be-accepted'},
])
def test_invalid_inputs_do_not_call_provider(plugin, monkeypatch, arguments):
    monkeypatch.setattr(plugin.jev, 'propose', lambda *a: pytest.fail('must validate first'))
    assert not plugin.JevRouteTool().execute(**arguments).success


def test_failed_decision_never_fabricates_success(plugin, monkeypatch):
    monkeypatch.setattr(plugin.jev, 'propose', lambda *a: None)
    result = plugin.JevRouteTool().execute(message='给我家節能方案')
    assert not result.success and result.data is None
    assert result.metadata['next_step'] == 'fallback_or_clarify'


def test_missing_download_is_visible(plugin, monkeypatch, tmp_path):
    monkeypatch.setattr(plugin, 'SKILL_FILE', tmp_path / 'missing.md')
    assert not plugin.JevRouteTool().execute(operation='guide').success
    assert not plugin.configuration_status()['skill_installed']
