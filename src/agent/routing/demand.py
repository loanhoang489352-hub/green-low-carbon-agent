"""对话需求数据结构 + 状态推进 + 对话状态存储(与路由逻辑解耦)。"""
from dataclasses import asdict, dataclass, field
import json
import os
import sqlite3
from pathlib import Path

from agent.intent import IntentResult, IntentType


@dataclass
class Demand:
    domain: str = 'general'
    act: str = 'clarify'
    relation: str = 'new'
    intent: str = 'unknown'
    tasks: list = field(default_factory=list)
    question: str = ''
    source: str = 'rules'
    evidence: str = ''
    message: str = ''

    def intent_result(self):
        return IntentResult(IntentType(self.intent), 0.0, [],
            {'understanding': asdict(self), 'confidence_calibrated': False},
            'clarification' if self.question else 'knowledge' if self.act == 'explain' else 'advice')


class DialogueStateStore:
    def __init__(self, path=None):
        from paths import DATA_DIR
        self.path = Path(path or DATA_DIR / 'dialogue_state.db')

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=5)
        conn.execute('CREATE TABLE IF NOT EXISTS dialogue_state (user_id TEXT, conversation_id TEXT, state TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(user_id, conversation_id))')
        return conn

    def load(self, user_id, conversation_id):
        from contextlib import closing
        with closing(self._connect()) as conn:
            row = conn.execute('SELECT state FROM dialogue_state WHERE user_id=? AND conversation_id=?', (user_id, conversation_id)).fetchone()
            return json.loads(row[0]) if row else {}

    def save(self, user_id, conversation_id, state):
        from contextlib import closing
        with closing(self._connect()) as conn:
            conn.execute('INSERT INTO dialogue_state(user_id,conversation_id,state) VALUES(?,?,?) ON CONFLICT(user_id,conversation_id) DO UPDATE SET state=excluded.state,updated_at=CURRENT_TIMESTAMP', (user_id, conversation_id, json.dumps(state, ensure_ascii=False)))
            conn.commit()


def advance_state(state, demand, text):
    state = dict(state)
    state['recent'] = (state.get('recent', []) + [{'role': 'user', 'content': text[:1000]}])[-6:]
    if demand.relation == 'resume':
        state['pending_tasks'] = [t for t in state.get('pending_tasks', []) if t['domain'] != demand.domain]
    if demand.act == 'cancel':
        state.update(active_domain='', expected_slot=None, pending_tasks=[], last_requests={})
    elif demand.tasks:
        state['pending_tasks'] = demand.tasks
    elif demand.act in ('plan', 'update'):
        if state.get('active_domain') != demand.domain:
            state['expected_slot'] = None
        state['active_domain'] = demand.domain
        if demand.act == 'plan':
            state['last_requests'] = {**state.get('last_requests', {}), demand.domain: demand.message}
        state['pending_tasks'] = [t for t in state.get('pending_tasks', []) if t['domain'] != demand.domain]
    state['last_decision'] = asdict(demand)
    return state


def mode_is_shadow():
    return os.getenv("UNDERSTANDING_MODE", "hybrid").lower() == "shadow"
