import json
from types import SimpleNamespace

import pytest

from agent.core import GreenAgent
from agent.intent import IntentRecognizer
from agent.understanding import DemandInterpreter, DialogueStateStore, advance_state


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
    def energy(uid, message, *args):
        seen.append(message)
        return SimpleNamespace(message='家里几个人？', trace=[])
    agent._handle_energy_planning = energy
    agent.chat_enhanced('alice', '帮我规划家庭节能', 'c')
    agent.chat_enhanced('alice', '四个', 'c')
    assert seen == ['帮我规划家庭节能', '四人']
    response = agent.chat_enhanced('alice', '取消', 'c')
    assert '取消' in response.message and len(seen) == 2
