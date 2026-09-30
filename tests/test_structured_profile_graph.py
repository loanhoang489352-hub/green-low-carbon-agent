import sqlite3
import pytest

from user_profile.graph_store import SQLiteGraphStore
from user_profile.user_profile import UserProfileManager
from agent.energy.personalization import remember_confirmed, resolve_profile
from agent.energy.models import HouseholdProfile


def test_chat_correction_survives_new_manager_and_drives_plan(tmp_path):
    path = str(tmp_path / 'profiles.db')
    m = UserProfileManager(path)
    m.get_profile('alice')
    p = HouseholdProfile(user_id='alice', family_size=5, appliances=['冰箱'], uses_gas=False)
    assert remember_confirmed(m, 'alice', p, {'family_size':5,'appliances':['冰箱'],'uses_gas':False})
    p.family_size = 2
    assert remember_confirmed(m, 'alice', p, {'family_size':2})
    fresh = UserProfileManager(path).get_profile('alice', refresh=True)
    assert resolve_profile('alice', fresh)[0].family_size == 2
    with sqlite3.connect(path) as c:
        store = SQLiteGraphStore(c)
        facts = [n for n in store.load('alice')['nodes'] if n['node_type']=='household_fact']
        assert next(n for n in facts if n['properties']['field']=='family_size')['properties']['value']==2
        assert c.execute("SELECT count(*) FROM profile_fact_evidence WHERE user_id='alice' AND field='family_size'").fetchone()[0]==2
        assert store.load('bob')['nodes']==[]


def test_form_backfill_and_repeat_reads_are_idempotent(tmp_path):
    path = str(tmp_path / 'profiles.db')
    m=UserProfileManager(path)
    m.update_basic_info('alice', {'family_type':'3','region':'北京'})
    for _ in range(3):
        m.get_profile('alice', refresh=True)
    with sqlite3.connect(path) as c:
        assert c.execute('SELECT count(*) FROM profile_fact_evidence').fetchone()[0]==2
        graph=SQLiteGraphStore(c).load('alice')
        assert len(graph['edges'])==2


def test_stale_evidence_does_not_confirm_changed_value():
    with sqlite3.connect(':memory:') as c:
        store=SQLiteGraphStore(c)
        p={'behavior_profile':{'home_energy_usage':{'uses_gas':False,'appliances':[], '_evidence':{'uses_gas':{'value':True,'source':'chat_explicit'}}}}}
        g=store.sync('a',p)
        facts={n['properties'].get('field'):n['properties'] for n in g['nodes']}
        assert facts['uses_gas']['value'] is False
        assert facts['uses_gas']['status']=='unconfirmed'
        assert facts['appliances']['value']==[]


def test_form_correction_overrides_chat_number(tmp_path):
    m=UserProfileManager(str(tmp_path/'p.db'))
    m.get_profile('a')
    p=HouseholdProfile(user_id='a',family_size=5,appliances=['冰箱'])
    remember_confirmed(m,'a',p,{'family_size':5})
    m.update_basic_info('a',{'family_type':'2'})
    assert resolve_profile('a',m.get_profile('a',refresh=True))[0].family_size==2


def test_profile_write_failure_rolls_back_graph(tmp_path):
    path=str(tmp_path/'p.db')
    m=UserProfileManager(path)
    m.update_basic_info('a',{'family_type':'2'})
    with sqlite3.connect(path) as c:
        c.execute("CREATE TRIGGER reject_profile BEFORE UPDATE ON user_profiles BEGIN SELECT RAISE(ABORT,'test failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        m.update_basic_info('a',{'family_type':'3'})
    with sqlite3.connect(path) as c:
        values=c.execute("SELECT value_json FROM profile_fact_evidence WHERE user_id='a' AND field='family_size'").fetchall()
        assert values==[('2',)]
    assert m.get_profile('a',refresh=True)['basic_info']['family_type']=='2'
