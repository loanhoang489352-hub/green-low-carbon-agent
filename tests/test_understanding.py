import json
from types import SimpleNamespace

import pytest

from agent.core import GreenAgent
from agent.intent import IntentRecognizer
from agent.understanding import DemandInterpreter, DialogueStateStore, advance_state


@pytest.fixture(autouse=True)
def isolated_routing_environment(monkeypatch):
    # No external calls, real profile writes or Obsidian export in routing tests.
    from agent.skills.profile_mining_skill import ProfileMiningSkill
    monkeypatch.setenv('JEV_ROUTING_MODE', 'off')
    monkeypatch.setenv('JEV_PROVIDER', 'typesafe')
    monkeypatch.delenv('JEV_MODEL', raising=False)
    monkeypatch.delenv('JEV_MIN_CONFIDENCE', raising=False)
    monkeypatch.delenv('JEV_TIMEOUT_SECONDS', raising=False)
    monkeypatch.setenv('LLM_MOCK', 'true')
    monkeypatch.setattr(ProfileMiningSkill, 'execute',
                        lambda *a: SimpleNamespace(success=False, data=None))


@pytest.fixture
def interpreter(monkeypatch):
    monkeypatch.setenv('UNDERSTANDING_MODE', 'rules')
    return DemandInterpreter(IntentRecognizer())


@pytest.mark.parametrize('text,intent,act', [
    ('什么是节气？', 'knowledge_query', 'explain'),
    ('节水为什么能减碳？', 'knowledge_query', 'explain'),
    ('我不需要节能方案，只想知道电费怎么算', 'knowledge_query', 'explain'),
    ('假如我家有燃气灶，如何节能', 'knowledge_query', 'explain'),
    ('帮我规划家里如何节电节水', 'energy_planning', 'plan'),
    ('帮我降低电费', 'energy_planning', 'plan'),
    ('制定家庭节能方案', 'energy_planning', 'plan'),
    ('从北京站到故宫怎么走', 'travel_planning', 'plan'),
    ('今天坐地铁回家了', 'action_report', 'report'),
    ('我昨天骑自行车上班了', 'action_report', 'report'),
    ('我已经步行回家', 'action_report', 'report'),
    ('明天从家到公司怎么走', 'travel_planning', 'plan'),
    ('取消当前任务', 'feedback', 'cancel'),
    ('你好', 'greeting', 'greet'),
    ('asdfghjkl', 'unknown', 'clarify'),
    ('帮我一些低碳生活建议', 'advice_request', 'advise'),
])
def test_speech_act_before_topic(interpreter, text, intent, act):
    d = interpreter.understand(text)
    assert (d.intent, d.act) == (intent, act)
    assert d.intent_result().context['confidence_calibrated'] is False


def test_expected_slot_interrupt_resume_and_cancel(interpreter, tmp_path):
    store = DialogueStateStore(tmp_path / 'state.db')
    state = advance_state({}, interpreter.understand('帮我规划家庭节能'), '帮我规划家庭节能')
    state['expected_slot'] = 'family_size'
    store.save('alice', 'c', state)
    state = DialogueStateStore(store.path).load('alice', 'c')
    assert interpreter.understand('四个', state).act == 'update'
    assert interpreter.understand('三个人', state).act == 'update'
    question = interpreter.understand('北京天气如何', state, hints={'city': 'beijing'})
    assert question.act == 'explain'
    state = advance_state(state, question, '北京天气如何')
    assert state['expected_slot'] == 'family_size'
    assert interpreter.understand('继续刚才的方案', state).relation == 'resume'
    state = advance_state(state, interpreter.understand('取消', state), '取消')
    assert not state['active_domain'] and not state['last_requests']
    assert interpreter.understand('四个', state).act == 'clarify'
    assert store.load('bob', 'c') == {} and store.load('alice', 'other') == {}


def test_multi_request_keeps_unselected_task(interpreter):
    text = '先规划明天的地铁路线，再帮我看看家里怎么节电'
    d = interpreter.understand(text)
    assert d.act == 'clarify' and len(d.tasks) == 2
    state = advance_state({}, d, text)
    chosen = interpreter.understand('先出行', state)
    assert chosen.domain == 'travel' and chosen.act == 'plan'
    state = advance_state(state, chosen, '先出行')
    assert [t['domain'] for t in state['pending_tasks']] == ['energy']
    assert interpreter.understand('继续家庭节能', state).domain == 'energy'


def test_switch_and_explicit_resume(interpreter):
    state = advance_state({}, interpreter.understand('帮我规划家庭节能'), '帮我规划家庭节能')
    state['expected_slot'] = 'family_size'
    state = advance_state(state, interpreter.understand('从车站到公园怎么走', state), '从车站到公园怎么走')
    assert state['expected_slot'] is None and state['active_domain'] == 'travel'
    d = interpreter.understand('继续节能', state)
    assert d.domain == 'energy' and '当前画像' in d.message


def test_feedback_does_not_guess_referent(interpreter):
    d = interpreter.understand('这个太麻烦换一个', {'active_domain': 'energy'})
    assert d.act == 'clarify' and '哪条' in d.question
    hints = GreenAgent.__new__(GreenAgent)._parse_household_hints('保持舒适优先')
    assert interpreter.understand('保持舒适优先', {'active_domain': 'energy'}, hints=hints).act == 'update'


@pytest.mark.parametrize('payload', [
    'not json', '{}', '{"domain":"energy"}',
    json.dumps({'domain': 'energy', 'act': 'plan', 'relation': 'new', 'question': '', 'profile_updates': {'family_size': 5}}),
    json.dumps({'domain': 'general', 'act': 'plan', 'relation': 'new', 'question': ''}),
    json.dumps({'domain': 'energy', 'act': 'update', 'relation': 'new', 'question': ''}),
    json.dumps({'domain': 'general', 'act': 'clarify', 'relation': 'new', 'question': ''}),
])
def test_invalid_model_proposal_falls_back_without_profile_writes(monkeypatch, payload):
    monkeypatch.setenv('UNDERSTANDING_MODE', 'hybrid')
    model = SimpleNamespace(chat=lambda *a, **kw: SimpleNamespace(content=payload, error=None))
    d = DemandInterpreter(IntentRecognizer(), model).understand('这件事怎么弄')
    assert d.source == 'rules' and d.act == 'clarify'


def test_valid_model_proposal_and_shadow(monkeypatch):
    monkeypatch.setenv('UNDERSTANDING_MODE', 'hybrid')
    model = SimpleNamespace(chat=lambda *a, **kw: SimpleNamespace(content=json.dumps({
        'domain': 'energy', 'act': 'plan', 'relation': 'new', 'question': ''}), error=None))
    interpreter = DemandInterpreter(IntentRecognizer(), model)
    assert interpreter.understand('我家用能开销想降下来').source == 'model'
    monkeypatch.setenv('UNDERSTANDING_MODE', 'shadow')
    assert interpreter.understand('我家用能开销想降下来').source == 'rules'


def test_model_not_called_for_explicit_explanation(monkeypatch):
    monkeypatch.setenv('UNDERSTANDING_MODE', 'hybrid')
    def fail(*args, **kw):
        raise AssertionError('unnecessary call')
    interpreter = DemandInterpreter(IntentRecognizer(), SimpleNamespace(chat=fail))
    assert interpreter.understand('电费怎么算').act == 'explain'


def test_model_timeout_is_bounded_without_retry():
    from llm.client import OpenAIClient
    client = OpenAIClient.__new__(OpenAIClient)
    client.model, client.temperature, client.max_tokens = 'test', 0, 10
    calls = []
    def timeout(**kwargs):
        calls.append(kwargs)
        raise TimeoutError('test timeout')
    client._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=timeout)))
    response = client._call_openai_sdk([], {'timeout': 8, 'max_retries': 0}, error_label='test', trace_id='test')
    assert response.error and len(calls) == 1 and calls[0]['timeout'] == 8


def test_compound_explanation_keeps_its_speech_act(interpreter):
    text = '先解释电费怎么算，再帮我规划出行路线'
    d = interpreter.understand(text)
    assert len(d.tasks) == 2
    state = advance_state({}, d, text)
    selected = interpreter.understand('先节能', state)
    assert selected.act == 'explain'
    state = advance_state(state, selected, '先节能')
    assert len(state['pending_tasks']) == 1


@pytest.mark.parametrize('engine', ['normal', 'react', 'langgraph'])
def test_core_uses_one_entry_and_short_answer(engine, tmp_path, monkeypatch):
    import agent.energy.household_store as households
    monkeypatch.setenv('UNDERSTANDING_MODE', 'rules')
    monkeypatch.setenv('USE_REACT', 'true' if engine == 'react' else 'false')
    monkeypatch.setattr(households, 'load_profile', lambda uid: None)
    agent = GreenAgent.__new__(GreenAgent)
    agent.use_langgraph = engine == 'langgraph'
    agent.intent_recognizer = IntentRecognizer()
    agent._dialogue_store = DialogueStateStore(tmp_path / 'state.db')
    agent.active_conversations = {'c': SimpleNamespace(user_id='alice', last_domain='')}
    agent._manage_conversation = lambda *a: 'c'
    seen = []
    def energy(uid, message, *args, **kwargs):
        assert 'profile_mining_meta' in kwargs and 'llm_truly_available' in kwargs
        seen.append(message)
        return SimpleNamespace(message='家里几个人？', trace=[])
    agent._handle_energy_planning = energy
    agent.chat_enhanced('alice', '帮我规划家庭节能', 'c')
    agent.chat_enhanced('alice', '四个', 'c')
    assert seen == ['帮我规划家庭节能', '四人']
    response = agent.chat_enhanced('alice', '取消', 'c')
    assert '取消' in response.message and len(seen) == 2


def jev_response(choice='energy_plan', confidence=0.95):
    from agent.routing.jev import CRITERIA
    return {'model': 'jev-1.13.0', 'answers': {'route': {
        'type': 'choice', 'choice': choice, 'confidence': confidence,
        'probabilities': {k: 1.0 if k == choice else 0.0 for k in CRITERIA}}},
        'usage': {'input_tokens': 200, 'output_tokens': 10}}


@pytest.fixture(params=['typesafe', 'openrouter'])
def jev_http(monkeypatch, request):
    import httpx
    from agent.routing import jev
    monkeypatch.setenv('JEV_ROUTING_MODE', 'active')
    monkeypatch.setenv('JEV_PROVIDER', request.param)
    monkeypatch.setenv('TYPESAFE_API_KEY', 'test-secret-not-real')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-openrouter-secret-not-real')
    monkeypatch.setenv('LLM_MOCK', 'false')
    monkeypatch.setenv('UNDERSTANDING_MODE', 'hybrid')
    calls, control = [], {'body': jev_response(), 'status': 200}
    real_client = httpx.Client

    def handle(request):
        calls.append(request)
        if 'error' in control:
            raise control['error']
        if 'content' in control:
            return httpx.Response(control['status'], content=control['content'])
        return httpx.Response(control['status'], json=control['body'])

    monkeypatch.setattr(jev.httpx, 'Client', lambda **kwargs: real_client(
        transport=httpx.MockTransport(handle), **kwargs))
    return calls, control


def test_jev_contract_and_personalized_request(jev_http):
    import os
    from agent.routing.jev import PROVIDERS
    calls, _ = jev_http
    state = {'recent': [{'role': 'user', 'content': '联系我13800001234', 'user_id': 'private'}],
             'user_id': 'private', 'profile': {'secret': 'never-send'}}
    demand = DemandInterpreter(IntentRecognizer()).understand('给我家个性化定制节能方案', state)
    assert (demand.domain, demand.act, demand.intent, demand.source) == (
        'energy', 'plan', 'energy_planning', 'jev')
    endpoint, _, model = PROVIDERS[os.environ['JEV_PROVIDER']]
    assert len(calls) == 1 and str(calls[0].url) == endpoint
    payload = json.loads(calls[0].content)
    assert payload['model'] == model
    expected_key = 'test-openrouter-secret-not-real' if os.environ['JEV_PROVIDER'] == 'openrouter' else 'test-secret-not-real'
    assert calls[0].headers['Authorization'] == 'Bearer ' + expected_key
    assert payload['questions']['route']['type'] == 'choice'
    assert 'private' not in calls[0].content.decode() and 'never-send' not in calls[0].content.decode()
    assert '13800001234' not in calls[0].content.decode()
    assert state['recent'][0]['content'] == '联系我13800001234'
    assert calls[0].extensions['timeout']['read'] == 3


@pytest.mark.parametrize('status', [401, 402, 403, 429, 500, 529, 302])
def test_jev_http_failure_does_not_retry_or_expose_body(jev_http, caplog, status):
    from agent.routing.jev import propose
    calls, control = jev_http
    control.update(status=status, content=b'test-secret-not-real sensitive-body')
    with caplog.at_level('INFO'):
        assert propose('给我家个性化定制节能方案', {}) is None
    assert len(calls) == 1 and f'http_{status}' in caplog.text
    assert 'test-secret-not-real' not in caplog.text and 'sensitive-body' not in caplog.text


@pytest.mark.parametrize('kind', ['timeout', 'network', 'json', 'oversized', 'missing', 'choice',
                                 'nan', 'boolean', 'negative', 'sum', 'not_max', 'low'])
def test_jev_bad_responses_fall_back(jev_http, kind):
    import httpx
    from agent.routing.jev import propose
    calls, control = jev_http
    answer = control['body']['answers']['route']
    if kind in ('timeout', 'network'):
        control['error'] = (httpx.ReadTimeout if kind == 'timeout' else httpx.ConnectError)('secret')
    elif kind == 'json':
        control['content'] = b'not json'
    elif kind == 'oversized':
        control['content'] = b'x' * 65537
    elif kind == 'missing':
        control['body'] = {}
    elif kind == 'choice':
        answer['choice'] = 'execute_shell'
    elif kind in ('nan', 'boolean', 'low'):
        answer['confidence'] = {'nan': float('nan'), 'boolean': True, 'low': 0.3}[kind]
    elif kind == 'negative':
        answer['probabilities']['explain'] = -1
    elif kind == 'sum':
        answer['probabilities']['explain'] = 0.5
    elif kind == 'not_max':
        answer['choice'] = 'explain'
    if kind == 'nan':
        control['content'] = json.dumps(control['body']).encode()
    assert propose('个性化用能建议', {}) is None
    assert len(calls) == 1


@pytest.mark.parametrize('setting,value', [('JEV_ROUTING_MODE', 'off'), ('JEV_ROUTING_MODE', 'typo'),
    ('TYPESAFE_API_KEY', ''), ('JEV_MIN_CONFIDENCE', 'NaN'), ('JEV_MIN_CONFIDENCE', '2'),
    ('JEV_TIMEOUT_SECONDS', '-1')])
def test_jev_configuration_fails_closed(jev_http, monkeypatch, setting, value):
    import os
    from agent.routing.jev import propose
    if setting == 'TYPESAFE_API_KEY' and os.environ['JEV_PROVIDER'] == 'openrouter':
        setting = 'OPENROUTER_API_KEY'
    monkeypatch.setenv(setting, value)
    assert propose('个性化用能建议', {}) is None
    assert not jev_http[0]


def test_jev_shadow_and_low_confidence_keep_existing_route(jev_http, monkeypatch):
    from agent.routing import router
    calls, control = jev_http
    monkeypatch.setattr(router, '_fast_classifier', lambda: None)
    monkeypatch.setenv('JEV_ROUTING_MODE', 'shadow')
    interpreter = DemandInterpreter(IntentRecognizer())
    assert interpreter.understand('帮我降低电费').source == 'rules'
    monkeypatch.setenv('JEV_ROUTING_MODE', 'active')
    control['body'] = jev_response(confidence=0.1)
    assert interpreter.understand('帮我降低电费').source == 'rules'
    assert len(calls) == 2


def test_jev_multi_turn_transition_and_update_guard(jev_http):
    from agent.routing.jev import propose
    _, control = jev_http
    control['body'] = jev_response('travel_plan')
    assert propose('换成明早到公司', {'active_domain': 'energy'}).relation == 'switch'
    assert propose('换成明早到公司', {'active_domain': 'travel'}).relation == 'continue'
    control['body'] = jev_response('energy_update')
    assert propose('三人', {}) is None
    interpreter = DemandInterpreter(IntentRecognizer())
    # A model may not invent writable facts; existing parsed hints are required.
    assert interpreter.understand('更新一下', {'active_domain': 'energy'}).act == 'clarify'


@pytest.mark.parametrize('text,state', [('取消', {'active_domain': 'energy'}),
    ('假如我家有燃气灶，如何节能', {}), ('四个', {'active_domain': 'energy', 'expected_slot': 'family_size'})])
def test_deterministic_controls_do_not_call_jev(jev_http, text, state):
    DemandInterpreter(IntentRecognizer()).understand(text, state)
    assert not jev_http[0]


def test_jev_energy_clarification_reaches_chat_ui(tmp_path, monkeypatch):
    import agent.understanding as understanding
    from agent.routing.demand import Demand
    monkeypatch.setattr(understanding.DemandInterpreter, 'understand',
                        lambda *a: Demand(domain='energy', act='clarify', question='请指定哪条建议', source='jev'))
    agent = GreenAgent.__new__(GreenAgent)
    agent._dialogue_store = DialogueStateStore(tmp_path / 'state.db')
    agent.intent_recognizer = IntentRecognizer()
    agent.active_conversations = {'c': SimpleNamespace(user_id='alice', last_domain='')}
    agent._manage_conversation = lambda *a: 'c'
    agent._handle_energy_planning = lambda *a, **kw: pytest.fail('clarification must not generate a plan')
    response = agent.chat_enhanced('alice', '那个调整一下', 'c')
    assert response.message == '请指定哪条建议'
    assert response.personalization_info['understanding']['source'] == 'jev'


def test_jev_input_limit_and_history_budget(jev_http):
    from agent.routing.jev import propose
    calls, _ = jev_http
    assert propose('x' * 6001, {}) is None and not calls
    propose('个性化用能建议', {'recent': [{'role': 'user', 'content': 'x' * 5000}] * 10})
    recent = json.loads(calls[0].content)['state']['recent']
    assert len(recent) == 4 and all(len(m['content']) == 1000 for m in recent)


@pytest.mark.parametrize('text,state,expected', [
    ('给我家个性化定制节能方案，尽量省事，不想换家电', {}, 'energy'),
    ('明早从重庆北站到解放碑，公交地铁优先，不骑车', {}, 'travel'),
    ('还是按我家现在的情况重新安排一下用能吧', {'active_domain': 'energy', 'recent': [
        {'role': 'assistant', 'content': '刚才讨论了你家空调与热水器的节能安排。'}]}, 'energy'),
])
def test_jev_live_opt_in(monkeypatch, text, state, expected):
    import os
    from agent.routing.jev import propose
    if os.getenv('RUN_JEV_LIVE') != '1':
        pytest.skip('Real provider acceptance is opt-in; mock tests are not live evidence')
    from agent.routing.jev import PROVIDERS
    # Normal tests isolate configuration; live provider must be explicitly chosen.
    provider = os.getenv('JEV_LIVE_PROVIDER', 'typesafe')
    assert provider in PROVIDERS, 'Invalid JEV_LIVE_PROVIDER'
    monkeypatch.setenv('JEV_PROVIDER', provider)
    assert os.getenv(PROVIDERS[provider][1]), 'Configure the selected provider key locally before live acceptance'
    monkeypatch.setenv('JEV_ROUTING_MODE', 'active')
    monkeypatch.setenv('UNDERSTANDING_MODE', 'hybrid')
    monkeypatch.setenv('LLM_MOCK', 'false')
    demand = propose(text, state)
    assert demand is not None, 'Jev did not return an accepted decision; inspect jev_route outcome'
    assert demand.source == 'jev' and demand.act == 'plan' and demand.domain == expected


@pytest.mark.parametrize('provider,model', [('openrouter', 'jev-1.13.0'),
    ('openrouter', 'typesafe/jev-router'), ('typesafe', 'typesafe/jev-1.13'),
    ('unknown', 'jev-1.13.0')])
def test_jev_wrong_provider_model_never_sends_credentials(jev_http, monkeypatch, provider, model):
    from agent.routing.jev import propose
    monkeypatch.setenv('JEV_PROVIDER', provider)
    monkeypatch.setenv('JEV_MODEL', model)
    assert propose('帮我定制节能方案', {}) is None
    assert not jev_http[0]


def test_jev_no_cross_provider_credential_fallback(jev_http, monkeypatch):
    import os
    from agent.routing.jev import propose, PROVIDERS
    monkeypatch.delenv(PROVIDERS[os.environ['JEV_PROVIDER']][1])
    assert propose('帮我定制节能方案', {}) is None
    assert not jev_http[0]
