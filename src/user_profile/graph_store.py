"""SQLite graph projection. Profile fields remain the compatibility source of truth.

No credentials or private wiki text are imported. Call sync inside the profile
transaction so a failed graph write cannot acknowledge a successful profile edit.
"""
import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Protocol


class GraphStore(Protocol):
    def sync(self, user_id, profile): ...
    def load(self, user_id): ...


class SQLiteGraphStore:
    def __init__(self, connection):
        self.conn = connection
        for sql in (
            'CREATE TABLE IF NOT EXISTS profile_graph_nodes (user_id TEXT, node_id TEXT, payload TEXT NOT NULL, PRIMARY KEY(user_id,node_id))',
            'CREATE TABLE IF NOT EXISTS profile_graph_edges (user_id TEXT, source TEXT, target TEXT, relation TEXT, payload TEXT NOT NULL, PRIMARY KEY(user_id,source,target,relation))',
            'CREATE TABLE IF NOT EXISTS profile_fact_evidence (user_id TEXT, field TEXT, version INTEGER, value_json TEXT NOT NULL, source TEXT NOT NULL, status TEXT NOT NULL, observed_at TEXT NOT NULL, PRIMARY KEY(user_id,field,version))',
        ):
            self.conn.execute(sql)

    def sync(self, user_id, profile):
        from agent.energy.personalization import FIELDS
        from user_profile.profile_graph import UserProfileGraph
        graph = deepcopy(profile.get('graph') or UserProfileGraph(user_id).to_dict())
        graph['user_id'] = user_id
        usage = profile.get('behavior_profile', {}).get('home_energy_usage') or {}
        evidence = usage.get('_evidence') or {}
        facts = {k: (v, 'legacy_profile', 'unconfirmed') for k, v in usage.items() if k in FIELDS}
        for key in facts:
            ev = evidence.get(key) or {}
            if ev.get('value') == usage[key] and ev.get('source') in ('chat_explicit', 'user_form'):
                facts[key] = (usage[key], ev['source'], 'confirmed')
        basic = profile.get('basic_info') or {}
        if 'family_size' not in facts and str(basic.get('family_type')) in ('1','2','3','4'):
            facts['family_size'] = (int(basic['family_type']), 'user_form', 'confirmed')
        if basic.get('region'):
            facts['city'] = (basic['region'], 'user_form', 'confirmed')
        now = datetime.now(timezone.utc).isoformat()
        nodes = {n['node_id']: n for n in graph['nodes']}
        for key, (value, source, status) in facts.items():
            encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
            old = self.conn.execute('SELECT version,value_json,source,status FROM profile_fact_evidence WHERE user_id=? AND field=? ORDER BY version DESC LIMIT 1', (user_id,key)).fetchone()
            if old is None or tuple(old[1:]) != (encoded,source,status):
                self.conn.execute('INSERT INTO profile_fact_evidence VALUES (?,?,?,?,?,?,?)', (user_id,key,old[0]+1 if old else 1,encoded,source,status,now))
            nid = 'energy_' + key
            # Replace obsolete household-fact nodes for the same field.
            obsolete = {i for i,n in nodes.items() if n.get('node_type') == 'household_fact' and n.get('properties',{}).get('field') == key}
            for i in obsolete:
                nodes.pop(i)
            graph['edges'] = [e for e in graph['edges'] if e['target'] not in obsolete]
            nodes[nid] = dict(node_id=nid,node_type='household_fact',properties=dict(field=key,value=value,source=source,status=status),created_at=now,updated_at=now)
            graph['edges'].append(dict(source='user_'+user_id,target=nid,relation_type='HAS_HOUSEHOLD_FACT',weight=1.0,properties={},created_at=now))
        graph['nodes'] = list(nodes.values())
        self.conn.execute('DELETE FROM profile_graph_edges WHERE user_id=?', (user_id,))
        self.conn.execute('DELETE FROM profile_graph_nodes WHERE user_id=?', (user_id,))
        for n in graph['nodes']:
            self.conn.execute('INSERT INTO profile_graph_nodes VALUES (?,?,?)',(user_id,n['node_id'],json.dumps(n,ensure_ascii=False)))
        for e in graph['edges']:
            if e['source'] in nodes and e['target'] in nodes:
                self.conn.execute('INSERT OR REPLACE INTO profile_graph_edges VALUES (?,?,?,?,?)',(user_id,e['source'],e['target'],e['relation_type'],json.dumps(e,ensure_ascii=False)))
        return self.load(user_id)

    def load(self, user_id):
        return dict(user_id=user_id,
            nodes=[json.loads(r[0]) for r in self.conn.execute('SELECT payload FROM profile_graph_nodes WHERE user_id=? ORDER BY node_id',(user_id,))],
            edges=[json.loads(r[0]) for r in self.conn.execute('SELECT payload FROM profile_graph_edges WHERE user_id=? ORDER BY source,target,relation',(user_id,))])
