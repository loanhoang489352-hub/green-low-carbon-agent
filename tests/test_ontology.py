"""
Step 1 验收测试:Ontology 模块(50 个测试)

覆盖:
  · schema 加载与单例(5)
  · 实体 / 关系 / 不变量 schema 描述(5)
  · profile 校验:字段类型 / 范围 / 必填(15)
  · profile 校验:不变量 INV_HOUSEHOLD_BOUNDS(5)
  · profile 校验:不变量 INV_PREFERENCE_EXCLUDES(5)
  · action 校验:字段类型 / 范围 / 必填(5)
  · action 校验:不变量 INV_ACTION_NEEDS_SOURCE(5)
  · action 校验:不变量 INV_ACTION_SOURCE_NONEMPTY(3)
  · plan_actions 端到端校验(2)
  · LLM 辅助接口(2)
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from agent.ontology import (
    Ontology,
    Violation,
    get_ontology,
    reset_ontology_cache,
    validate_profile,
    validate_action,
    validate_plan_actions,
    list_entity_names,
    list_relation_names,
    entity_spec_for_llm,
)


# ============ fixture ============

@pytest.fixture(autouse=True)
def _reset_singleton():
    """每个测试前重置 ontology 单例"""
    reset_ontology_cache()
    yield
    reset_ontology_cache()


# ============ 1. 加载与单例(5) ============

class TestSchemaLoading:
    def test_default_schema_loads(self):
        onto = get_ontology()
        assert onto is not None
        assert onto.domain == "green_lifestyle"

    def test_version_present(self):
        onto = get_ontology()
        assert onto.version  # 非空

    def test_singleton_returns_same_instance(self):
        a = get_ontology()
        b = get_ontology()
        assert a is b

    def test_custom_schema_path(self, tmp_path):
        # 写一个最小 schema
        custom = {
            "version": "0.0.1",
            "domain": "test",
            "entities": {"X": {"description": "X", "properties": {}}},
            "relations": {},
            "invariants": [],
            "node_type_mapping": {},
        }
        p = tmp_path / "onto.json"
        p.write_text(json.dumps(custom), encoding="utf-8")
        onto = get_ontology(schema_path=p)
        assert onto.domain == "test"
        assert "X" in onto.entities

    def test_missing_schema_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            get_ontology(schema_path=tmp_path / "nope.json")


# ============ 2. Schema 描述(5) ============

class TestSchemaDescription:
    def test_entity_count(self):
        onto = get_ontology()
        # 至少 8 个核心实体
        assert len(onto.entities) >= 8
        assert "Household" in onto.entities
        assert "Action" in onto.entities
        assert "Policy" in onto.entities

    def test_relation_count(self):
        onto = get_ontology()
        assert len(onto.relations) >= 9
        assert "LIVES_IN" in onto.relations
        assert "CITES" in onto.relations

    def test_invariant_count(self):
        onto = get_ontology()
        assert len(onto.invariants) >= 4
        ids = {iv.id for iv in onto.invariants}
        assert "INV_HOUSEHOLD_BOUNDS" in ids
        assert "INV_ACTION_NEEDS_SOURCE" in ids
        assert "INV_PREFERENCE_EXCLUDES" in ids

    def test_node_type_mapping_present(self):
        onto = get_ontology()
        assert "UserProfileGraph" in onto.node_type_mapping
        assert "KnowledgeGraph" in onto.node_type_mapping

    def test_entity_lookup(self):
        onto = get_ontology()
        hh = onto.entity("Household")
        assert hh is not None
        assert "family_size" in hh.properties


# ============ 3. Profile 字段校验(15) ============

class TestProfileFieldValidation:
    def _profile(self, **overrides):
        base = {
            "family_size": 3,
            "home_size_sqm": 90.0,
            "city": "beijing",
            "appliances": ["ac", "water_heater"],
            "priority": "easy",
        }
        base.update(overrides)
        return base

    def test_valid_profile_passes(self):
        ok, vs = validate_profile(self._profile())
        assert ok, f"unexpected violations: {vs}"

    def test_family_size_too_small(self):
        ok, vs = validate_profile(self._profile(family_size=0))
        assert not ok
        assert any(v.rule_id == "RANGE_ERROR" for v in vs)

    def test_family_size_too_big(self):
        ok, vs = validate_profile(self._profile(family_size=21))
        assert not ok
        assert any(v.rule_id == "RANGE_ERROR" for v in vs)

    def test_family_size_at_boundary_low(self):
        ok, vs = validate_profile(self._profile(family_size=1))
        assert ok, vs

    def test_family_size_at_boundary_high(self):
        ok, vs = validate_profile(self._profile(family_size=20))
        assert ok, vs

    def test_home_size_too_small(self):
        ok, vs = validate_profile(self._profile(home_size_sqm=5))
        assert not ok
        assert any(v.rule_id == "RANGE_ERROR" for v in vs)

    def test_home_size_too_big(self):
        ok, vs = validate_profile(self._profile(home_size_sqm=3000))
        assert not ok

    def test_priority_invalid_enum(self):
        ok, vs = validate_profile(self._profile(priority="random"))
        assert not ok
        assert any(v.rule_id == "ENUM_ERROR" for v in vs)

    def test_priority_valid_comfort(self):
        ok, _ = validate_profile(self._profile(priority="comfort"))
        assert ok

    def test_priority_valid_money(self):
        ok, _ = validate_profile(self._profile(priority="money"))
        assert ok

    def test_priority_valid_eco(self):
        ok, _ = validate_profile(self._profile(priority="eco"))
        assert ok

    def test_appliances_must_be_list(self):
        ok, vs = validate_profile(self._profile(appliances="not a list"))
        assert not ok

    def test_appliances_empty_list_passes(self):
        # appliances 本身在 HouseholdProfile 是可选,空列表不算错
        ok, _ = validate_profile(self._profile(appliances=[]))
        assert ok

    def test_excluded_actions_list_of_strings(self):
        ok, vs = validate_profile(self._profile(excluded_actions=["ac_temp_up_1c", 123]))
        assert not ok
        assert any(v.rule_id == "ARRAY_ITEM_TYPE" for v in vs)

    def test_missing_optional_family_size(self):
        ok, _ = validate_profile({k: v for k, v in self._profile().items() if k != "family_size"})
        # family_size 非必填,应当通过
        assert ok


# ============ 4. INV_HOUSEHOLD_BOUNDS(5) ============

class TestHouseholdBoundsInvariant:
    def test_negative_family_size(self):
        ok, vs = validate_profile({"family_size": -1})
        assert not ok
        assert any(v.rule_id == "INV_HOUSEHOLD_BOUNDS" for v in vs)

    def test_zero_home_size(self):
        ok, vs = validate_profile({"home_size_sqm": 0})
        assert not ok
        assert any(v.rule_id == "INV_HOUSEHOLD_BOUNDS" for v in vs)

    def test_huge_bill(self):
        ok, vs = validate_profile({
            "family_size": 3,
            "monthly_electricity_bill": 10000,
        })
        assert not ok
        assert any(v.rule_id == "RANGE_ERROR" for v in vs)

    def test_negative_bill(self):
        ok, vs = validate_profile({
            "family_size": 3,
            "monthly_water_bill": -50,
        })
        assert not ok

    def test_valid_bills_pass(self):
        ok, _ = validate_profile({
            "family_size": 4,
            "home_size_sqm": 120,
            "monthly_electricity_bill": 200,
            "monthly_water_bill": 50,
            "monthly_gas_bill": 80,
            "priority": "easy",
        })
        assert ok


# ============ 5. INV_PREFERENCE_EXCLUDES(5) ============

class TestPreferenceExcludesInvariant:
    def test_no_exclusion_passes(self):
        ok, _ = validate_profile({
            "family_size": 3,
            "priority": "easy",
            "excluded_actions": [],
            "_recommendation_action_ids": ["ac_temp_up_1c"],
        })
        assert ok

    def test_excluded_action_not_recommended(self):
        ok, _ = validate_profile({
            "family_size": 3,
            "priority": "easy",
            "excluded_actions": ["ac_temp_up_1c"],
            "_recommendation_action_ids": ["ac_clean_filter"],  # 不同的 action
        })
        assert ok

    def test_excluded_action_recommended_violates(self):
        ok, vs = validate_profile({
            "family_size": 3,
            "priority": "easy",
            "excluded_actions": ["ac_temp_up_1c"],
            "_recommendation_action_ids": ["ac_temp_up_1c"],  # 命中排除
        })
        assert not ok
        assert any(v.rule_id == "INV_PREFERENCE_EXCLUDES" for v in vs)

    def test_multiple_excluded(self):
        ok, vs = validate_profile({
            "family_size": 3,
            "priority": "easy",
            "excluded_actions": ["ac_temp_up_1c", "water_bathing_shorter"],
            "_recommendation_action_ids": ["water_bathing_shorter", "ac_clean_filter"],
        })
        assert not ok
        assert len([v for v in vs if v.rule_id == "INV_PREFERENCE_EXCLUDES"]) == 1

    def test_empty_recommendations_passes(self):
        ok, _ = validate_profile({
            "family_size": 3,
            "priority": "easy",
            "excluded_actions": ["ac_temp_up_1c"],
            "_recommendation_action_ids": [],
        })
        assert ok


# ============ 6. Action 字段校验(5) ============

class TestActionFieldValidation:
    def _action(self, **overrides):
        base = {
            "id": "ac_temp_up_1c",
            "category": "electricity",
            "difficulty": 1,
            "estimate_kind": "reference",
            "source_ref": "standard:GB 12021.2-2015",
            "estimated_saving_cny": 26.0,
        }
        base.update(overrides)
        return base

    def test_valid_action(self):
        ok, vs = validate_action(self._action(cited_policies=["GB 12021.2-2015"]))
        assert ok, vs

    def test_missing_required_id(self):
        ok, vs = validate_action(self._action(id=None))
        assert not ok
        assert any(v.rule_id == "MISSING_REQUIRED" for v in vs)

    def test_difficulty_out_of_range(self):
        ok, vs = validate_action(self._action(difficulty=5))
        assert not ok

    def test_category_invalid(self):
        ok, vs = validate_action(self._action(category="magic"))
        assert not ok
        assert any(v.rule_id == "ENUM_ERROR" for v in vs)

    def test_estimate_kind_invalid(self):
        ok, vs = validate_action(self._action(estimate_kind="approximate"))
        assert not ok


# ============ 7. INV_ACTION_NEEDS_SOURCE(5) ============

class TestActionNeedsSourceInvariant:
    def test_reference_with_cites_passes(self):
        ok, vs = validate_action({
            "id": "ac_temp_up_1c",
            "category": "electricity",
            "difficulty": 1,
            "estimate_kind": "reference",
            "source_ref": "standard:GB 12021.2-2015",
            "estimated_saving_cny": 26.0,
            "cited_policies": ["GB 12021.2-2015"],
        })
        assert ok, vs

    def test_reference_without_cites_violates(self):
        ok, vs = validate_action({
            "id": "ac_temp_up_1c",
            "category": "electricity",
            "difficulty": 1,
            "estimate_kind": "reference",
            "source_ref": "standard:GB 12021.2-2015",
            "estimated_saving_cny": 26.0,
            "cited_policies": [],  # 空
        })
        assert not ok
        assert any(v.rule_id == "INV_ACTION_NEEDS_SOURCE" for v in vs)

    def test_calculated_with_cites_passes(self):
        ok, vs = validate_action({
            "id": "water_bathing_shorter",
            "category": "water",
            "difficulty": 1,
            "estimate_kind": "calculated",
            "source_ref": "profile:人数×分钟×L/min",
            "estimated_saving_cny": 12.0,
            "cited_policies": ["GB-T 18870-2011"],
        })
        assert ok, vs

    def test_qualitative_no_cites_ok(self):
        # qualitative 不要求 CITES
        ok, vs = validate_action({
            "id": "ac_clean_filter",
            "category": "electricity",
            "difficulty": 1,
            "estimate_kind": "qualitative",
            "source_ref": "standard:GB 12021.2-2015",
        })
        assert ok, vs

    def test_cites_policy_with_dict(self):
        ok, vs = validate_action({
            "id": "ac_temp_up_1c",
            "category": "electricity",
            "difficulty": 1,
            "estimate_kind": "reference",
            "source_ref": "x",
            "cited_policies": [{"doc_id": "GB 12021.2-2015"}],
        })
        assert ok, vs


# ============ 8. INV_ACTION_SOURCE_NONEMPTY(3) ============

class TestActionSourceRefNonempty:
    def test_empty_source_violates(self):
        ok, vs = validate_action({
            "id": "ac_temp_up_1c",
            "category": "electricity",
            "difficulty": 1,
            "estimate_kind": "qualitative",
            "source_ref": "",  # 空
        })
        assert not ok
        assert any(v.rule_id == "INV_ACTION_SOURCE_NONEMPTY" for v in vs)

    def test_whitespace_source_violates(self):
        ok, vs = validate_action({
            "id": "x",
            "category": "electricity",
            "difficulty": 1,
            "estimate_kind": "qualitative",
            "source_ref": "   ",
        })
        assert not ok

    def test_valid_source_passes(self):
        ok, _ = validate_action({
            "id": "x",
            "category": "electricity",
            "difficulty": 1,
            "estimate_kind": "qualitative",
            "source_ref": "policy:abc",
        })
        assert ok


# ============ 9. Plan Actions 端到端(2) ============

class TestPlanActionsE2E:
    def test_clean_plan_passes(self):
        ok, vs = validate_plan_actions({
            "actions": [
                {
                    "id": "ac_temp_up_1c",
                    "category": "electricity",
                    "difficulty": 1,
                    "estimate_kind": "reference",
                    "source_ref": "standard:GB 12021.2-2015",
                    "cited_policies": ["GB 12021.2-2015"],
                },
                {
                    "id": "ac_clean_filter",
                    "category": "electricity",
                    "difficulty": 1,
                    "estimate_kind": "qualitative",
                    "source_ref": "standard:vendor建议",
                },
            ]
        })
        assert ok, vs

    def test_mixed_plan_violations_indexed(self):
        ok, vs = validate_plan_actions({
            "actions": [
                {  # 第 0 个:缺 source_ref
                    "id": "x1",
                    "category": "electricity",
                    "difficulty": 1,
                    "estimate_kind": "qualitative",
                    "source_ref": "",
                },
                {  # 第 1 个:可量化无 CITES
                    "id": "x2",
                    "category": "electricity",
                    "difficulty": 1,
                    "estimate_kind": "reference",
                    "source_ref": "y",
                    "cited_policies": [],
                },
            ]
        })
        assert not ok
        paths = [v.field_path for v in vs]
        assert any("actions[0]" in p for p in paths)
        assert any("actions[1]" in p for p in paths)


# ============ 10. LLM 辅助接口(2) ============

class TestLLMAuxiliary:
    def test_list_entity_names(self):
        names = list_entity_names()
        assert "Household" in names
        assert "Action" in names

    def test_entity_spec_for_llm_is_readable(self):
        spec_text = entity_spec_for_llm("Household")
        assert "Entity: Household" in spec_text
        assert "family_size" in spec_text
        # 检查约束(范围 / 必填 之一)
        assert ("REQUIRED" in spec_text) or ("∈" in spec_text) or ("range" in spec_text.lower())

    def test_entity_spec_unknown_returns_marker(self):
        text = entity_spec_for_llm("NonExistent")
        assert "(unknown entity" in text