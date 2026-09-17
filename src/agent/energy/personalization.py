"""Resolve energy needs from the same structured profile projected to Obsidian.

The wiki is an observation view, never a second source of user identity or facts.
Only allowlisted household fields affect calculations; inferred interests do not.
"""
from copy import deepcopy
from datetime import datetime

from .models import HouseholdProfile

FIELDS = (
    'city', 'family_size', 'home_size_sqm', 'appliances', 'uses_gas',
    'monthly_electricity_bill', 'monthly_water_bill', 'monthly_gas_bill',
    'peak_offpeak_usage', 'ac_temp_setting', 'has_incandescent', 'has_drip',
    'priority', 'already_doing', 'excluded_actions', 'shower_minutes',
    'shower_flow_lpm', 'showers_per_person_week', 'water_price_per_m3',
)


def resolve_profile(user_id, main_profile, stored=None):
    """Refresh from current main profile on every turn, not just first use."""
    raw = stored.to_dict() if stored else {'user_id': user_id}
    sources = {k: '家庭画像记录' for k in FIELDS if raw.get(k) not in (None, '', [])}
    usage = (main_profile.get('behavior_profile') or {}).get('home_energy_usage') or {}
    for key in FIELDS:
        if key in usage:  # Explicit false, zero and empty list must replace old values.
            raw[key] = deepcopy(usage[key])
            sources[key] = '主画像中的家庭信息'
    basic = main_profile.get('basic_info') or {}
    family = basic.get('family_type')
    # family_type 是粗分类(onboarding),只在 home_energy_usage 未提供精确 family_size 时才应用。
    # 精确值(聊天 hints/确认写入 usage)优先;family_type 仍可覆盖旧的 stored 值。
    if 'family_size' not in usage:
        if str(family) in ('1', '2', '3', '4'):
            raw['family_size'] = int(family)
            sources['family_size'] = '用户填写的家庭人数'
        elif family == '3-4':
            if raw.get('family_size') not in (3, 4):
                raw['family_size'] = None
        elif family == '5+':
            # A category is not an exact number for savings calculations.
            if not isinstance(raw.get('family_size'), int) or raw['family_size'] < 5:
                raw['family_size'] = None
    if basic.get('region'):
        from .policies import CITY_TIER_PRICING
        region = str(basic['region']).lower()
        raw['city'] = str(basic['region'])
        for key, pricing in CITY_TIER_PRICING.items():
            if key != 'default' and any(alias.lower() in region for alias in pricing.city_aliases):
                raw['city'] = key
                break
        sources['city'] = '用户填写的地区'
    raw['user_id'] = user_id
    if raw.get('uses_gas') is False and isinstance(raw.get('appliances'), list):
        raw['appliances'] = [a for a in raw['appliances'] if '燃气' not in a]
    return HouseholdProfile.from_dict(raw), sources


def resolve_via_ontology(user_id, main_profile, stored=None):
    """P13 升级版 resolve:返回 (profile, sources, violations)

    与 resolve_profile 行为一致,只是在末尾追加 ontology 不变量校验。
    校验失败时 violations 不为空(profile 仍返回,让调用方决定如何处理)。
    """
    from agent.ontology import validate_profile as _validate

    profile, sources = resolve_profile(user_id, main_profile, stored)
    profile_dict = profile.to_dict()
    ok, violations = _validate(profile_dict)
    return profile, sources, violations


def remember_confirmed(manager, user_id, profile, hints):
    """Write only this turn's explicit changes, with field-level provenance."""
    keys = set(hints) & set(FIELDS)
    if hints.get('restored_actions'):
        keys.update(('already_doing', 'excluded_actions'))
    if hints.get('removed_appliances'):
        keys.add('appliances')
    if 'uses_gas' in keys:
        keys.add('appliances')
    if not keys:
        return True
    current = deepcopy(manager.get_profile(user_id))
    behavior = current.get('behavior_profile') or {}
    usage = behavior.get('home_energy_usage') or {}
    evidence = usage.get('_evidence') or {}
    now = datetime.now().isoformat()
    for key in keys:
        usage[key] = deepcopy(getattr(profile, key))
        evidence[key] = {'source': 'chat_explicit', 'confirmed_at': now,
                         'value': deepcopy(usage[key])}
    usage['_evidence'] = evidence
    behavior['home_energy_usage'] = usage
    basic = current.get('basic_info') or {}
    if 'family_size' in keys:
        basic['family_type'] = str(profile.family_size) if profile.family_size < 5 else '5+'
    if 'city' in keys:
        basic['region'] = profile.city
    # Keep one current node per field, rather than accumulating contradictory facts.
    from user_profile.profile_graph import UserProfileGraph, ProfileNode, ProfileEdge
    graph = UserProfileGraph.from_dict(current['graph']) if current.get('graph') else UserProfileGraph(user_id)
    for key in keys:
        node_id = 'energy_' + key
        graph.nodes[node_id] = ProfileNode(node_id, 'household_fact',
            {'field': key, 'value': deepcopy(usage[key]), 'source': 'chat_explicit'}, now, now)
        if not any(e.source == 'user_' + user_id and e.target == node_id for e in graph.edges):
            graph.edges.append(ProfileEdge('user_' + user_id, node_id, 'HAS_HOUSEHOLD_FACT', created_at=now))
    return manager.update_profile(user_id, {'basic_info': basic, 'behavior_profile': behavior, 'graph': graph.to_dict()})


def describe_basis(profile):
    facts = []
    if profile.family_size:
        facts.append(f'{profile.family_size}人家庭')
    if profile.appliances:
        facts.append('设备：' + '、'.join(profile.appliances))
    if profile.uses_gas is False:
        facts.append('不使用燃气')
    facts.append({'comfort': '保持舒适优先', 'money': '省钱优先', 'easy': '少折腾优先'}.get(profile.priority, '按当前偏好'))
    if profile.already_doing or profile.excluded_actions:
        facts.append('避开已在做或明确排除的措施')
    return '这次按你的当前画像安排：' + '；'.join(facts) + '。如有变化，直接在对话里告诉我。'
