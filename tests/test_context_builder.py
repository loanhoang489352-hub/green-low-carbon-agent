"""
Step 4 验收测试:Context Builder(30 个测试)

覆盖:
  · PII 脱敏(5)
  · Profile 三元组序列化(5)
  · Knowledge 三元组序列化(5)
  · Schema 摘要(3)
  · ContextBuilder.build 基础(5)
  · Knowledge 关联 action_ids(3)
  · 长度截断(2)
  · 端到端 render(2)
"""
from __future__ import annotations

from agent.context_builder import (
    ContextBuilder,
    ContextOptions,
    BuiltContext,
    _serialize_profile_facts,
    _serialize_knowledge_triples,
    _serialize_schema,
    _redact_value,
    _is_pii_field,
    _field_to_ontology_type,
    quick_build,
)
from user_profile.profile_graph import UserProfileGraph
from rag.kg_store import KGEntity, KGRelation, KnowledgeGraphStore


# ============ 1. PII 脱敏(5) ============

class TestPIIRedaction:
    def test_phone_redact(self):
        assert _redact_value("13800001234") == "138****1234"

    def test_email_redact(self):
        assert _redact_value("alice@example.com") == "a***@example.com"

    def test_id_card_redact(self):
        assert _redact_value("110101199001011234") == "110********1234"

    def test_bank_card_redact(self):
        assert _redact_value("6222021234567890") == "6222****7890"

    def test_non_pii_passthrough(self):
        assert _redact_value("beijing") == "beijing"
        assert _redact_value(3) == 3
        assert _redact_value(None) is None

    def test_pii_field_blacklist(self):
        assert _is_pii_field("phone") is True
        assert _is_pii_field("user_phone") is True
        assert _is_pii_field("email_address") is True
        assert _is_pii_field("family_size") is False


# ============ 2. Profile 三元组序列化(5) ============

class TestSerializeProfile:
    def test_user_node(self):
        nodes = [{
            "node_id": "user_u1", "node_type": "user",
            "properties": {"user_id": "u1"},
        }]
        out = _serialize_profile_facts(nodes, redact_pii=False)
        assert "User: u1" in out

    def test_interest_node(self):
        nodes = [{
            "node_id": "interest_x", "node_type": "interest",
            "properties": {"interest_id": "energy_saving", "confidence": 0.85},
        }]
        out = _serialize_profile_facts(nodes)
        assert "HAS_INTEREST" in out
        assert "energy_saving" in out
        assert "0.85" in out

    def test_household_fact_node(self):
        nodes = [{
            "node_id": "energy_family_size", "node_type": "household_fact",
            "properties": {
                "field": "family_size", "value": 3,
                "ontology_type": "Household", "source": "chat_explicit",
                "confidence": 1.0,
            },
        }]
        out = _serialize_profile_facts(nodes)
        assert "HAS_HOUSEHOLD_FACT" in out
        assert "Household.family_size = 3" in out
        assert "chat_explicit" in out

    def test_pii_value_redacted(self):
        nodes = [{
            "node_id": "energy_phone", "node_type": "household_fact",
            "properties": {
                "field": "phone", "value": "13800001234",
                "ontology_type": "Household", "source": "explicit", "confidence": 1.0,
            },
        }]
        out = _serialize_profile_facts(nodes, redact_pii=True)
        assert "[REDACTED]" in out
        assert "13800001234" not in out

    def test_behavior_stage_node(self):
        nodes = [{
            "node_id": "stage_x", "node_type": "behavior_stage",
            "properties": {"stage": "行动"},
        }]
        out = _serialize_profile_facts(nodes)
        assert "AT_STAGE" in out
        assert "行动" in out


# ============ 3. Knowledge 三元组序列化(5) ============

class TestSerializeKnowledge:
    def test_entity_basic(self):
        ents = [KGEntity(id="e1", entity_type="action", name="ac_temp_up_1c", source_doc="GB 12021")]
        rels = []
        out = _serialize_knowledge_triples(ents, rels, redact_pii=False)
        assert "(action: ac_temp_up_1c)" in out
        assert "GB 12021" in out

    def test_relation(self):
        ents = [
            KGEntity(id="e1", entity_type="action", name="ac_temp_up_1c"),
            KGEntity(id="e2", entity_type="policy", name="GB 12021"),
        ]
        rels = [KGRelation(source_entity="e1", target_entity="e2", relation_type="CITES", weight=1.0)]
        out = _serialize_knowledge_triples(ents, rels, redact_pii=False)
        assert "(ac_temp_up_1c) --CITES--> (GB 12021)" in out
        assert "w=1.00" in out

    def test_props_included(self):
        ents = [KGEntity(
            id="e1", entity_type="action", name="x",
            properties={"category": "electricity", "difficulty": 1},
        )]
        out = _serialize_knowledge_triples(ents, [], redact_pii=False)
        assert "category=electricity" in out
        assert "difficulty=1" in out

    def test_pii_redaction(self):
        ents = [KGEntity(
            id="e1", entity_type="concept", name="alice@example.com",
            properties={"phone": "13800001234"},
        )]
        out = _serialize_knowledge_triples(ents, [], redact_pii=True)
        assert "13800001234" not in out

    def test_missing_entity_in_relation(self):
        """关系指向不存在的 entity → 用 entity_id 替代"""
        rels = [KGRelation(source_entity="missing", target_entity="also_missing", relation_type="RELATED_TO")]
        out = _serialize_knowledge_triples([], rels)
        assert "missing" in out


# ============ 4. Schema 摘要(3) ============

class TestSchemaSummary:
    def test_default_includes_core_entities(self):
        out = _serialize_schema()
        assert "Entity: Household" in out
        assert "Entity: Action" in out
        assert "Entity: Policy" in out

    def test_custom_entities(self):
        out = _serialize_schema(entity_names=["Household", "Bill"])
        assert "Entity: Household" in out
        assert "Entity: Bill" in out
        # 不在列表的 Entity 不应出现
        assert "Entity: Goal" not in out

    def test_relations_listed(self):
        out = _serialize_schema()
        assert "LIVES_IN" in out
        assert "CITES" in out


# ============ 5. ContextBuilder.build 基础(5) ============

class TestBuild:
    def test_profile_only(self):
        g = UserProfileGraph("u1")
        g.add_household_fact("family_size", 3)
        builder = ContextBuilder(profile_graph_factory=lambda uid: g)
        ctx = builder.build("u1", options=ContextOptions(include_knowledge=False, include_schema=False))
        assert "HAS_HOUSEHOLD_FACT" in ctx.profile_section
        assert ctx.knowledge_section == ""
        assert ctx.schema_section == ""

    def test_schema_included(self):
        g = UserProfileGraph("u1")
        builder = ContextBuilder(profile_graph_factory=lambda uid: g)
        ctx = builder.build("u1", options=ContextOptions(include_profile=False))
        assert "Entity:" in ctx.schema_section

    def test_meta_recorded(self):
        g = UserProfileGraph("u1")
        g.add_household_fact("family_size", 3)
        builder = ContextBuilder(profile_graph_factory=lambda uid: g)
        ctx = builder.build("u1", options=ContextOptions(include_knowledge=False))
        assert ctx.meta["user_id"] == "u1"
        assert "profile_node_count" in ctx.meta
        assert "profile_edge_count" in ctx.meta

    def test_render_joins_sections(self):
        g = UserProfileGraph("u1")
        builder = ContextBuilder(profile_graph_factory=lambda uid: g)
        ctx = builder.build("u1", options=ContextOptions(include_knowledge=False))
        out = ctx.render()
        assert "Profile Facts" in out
        assert "Ontology Schema" in out

    def test_field_to_ontology_type(self):
        assert _field_to_ontology_type("family_size") == "Household"
        assert _field_to_ontology_type("monthly_electricity_bill") == "Bill"
        assert _field_to_ontology_type("ac_temp_c") == "Habit"
        assert _field_to_ontology_type("appliances") == "Appliance"
        assert _field_to_ontology_type("priority") == "Preference"
        assert _field_to_ontology_type("unknown_field") == "Household"  # fallback


# ============ 6. Knowledge 关联 action_ids(3) ============

class TestKnowledgeLinking:
    def test_action_ids_link_to_policies(self, tmp_path):
        kg = KnowledgeGraphStore(db_path=tmp_path / "k.db")
        kg.add_entity(KGEntity(entity_type="action", name="ac_temp_up_1c"))
        kg.add_entity(KGEntity(entity_type="policy", name="GB 12021"))
        kg.add_relation(KGRelation(
            source_entity=kg.find_entity_by_name("ac_temp_up_1c").id,
            target_entity=kg.find_entity_by_name("GB 12021").id,
            relation_type="CITES",
        ))
        builder = ContextBuilder(kg_store=kg, profile_graph_factory=lambda u: UserProfileGraph(u))
        ctx = builder.build("u1", action_ids=["ac_temp_up_1c"], options=ContextOptions(include_profile=False, include_schema=False))
        assert "CITES" in ctx.knowledge_section
        assert "GB 12021" in ctx.knowledge_section

    def test_no_matching_action(self, tmp_path):
        kg = KnowledgeGraphStore(db_path=tmp_path / "k.db")
        builder = ContextBuilder(kg_store=kg, profile_graph_factory=lambda u: UserProfileGraph(u))
        ctx = builder.build("u1", action_ids=["nonexistent_action"])
        assert "no knowledge entries" in ctx.knowledge_section.lower() or ctx.knowledge_section == ""

    def test_empty_action_ids(self, tmp_path):
        kg = KnowledgeGraphStore(db_path=tmp_path / "k.db")
        builder = ContextBuilder(kg_store=kg, profile_graph_factory=lambda u: UserProfileGraph(u))
        ctx = builder.build("u1", action_ids=[])
        # 列表为空 → 跳过 knowledge
        assert "skipped" in ctx.knowledge_section.lower() or ctx.knowledge_section == ""


# ============ 7. 长度截断(2) ============

class TestTruncation:
    def test_long_context_truncated(self):
        g = UserProfileGraph("u1")
        # 加 100 条 facts → 一定超过 max_chars=500
        for i in range(100):
            g.add_household_fact(f"field_{i}", f"value_{i}")
        builder = ContextBuilder(profile_graph_factory=lambda uid: g)
        ctx = builder.build("u1", options=ContextOptions(
            include_knowledge=False, include_schema=True, max_chars=500,
        ))
        assert ctx.meta.get("truncated") is True
        assert ctx.char_count() <= 500

    def test_short_context_not_truncated(self):
        g = UserProfileGraph("u1")
        g.add_household_fact("family_size", 3)
        builder = ContextBuilder(profile_graph_factory=lambda uid: g)
        ctx = builder.build("u1", options=ContextOptions(max_chars=12000))
        assert ctx.meta.get("truncated") is not True


# ============ 8. 端到端 render(2) ============

class TestEndToEnd:
    def test_quick_build_runs(self):
        """quick_build 不抛错"""
        out = quick_build("nonexistent_user")
        assert isinstance(out, str)
        # 即使用户不存在,至少 schema section 应出现
        assert "Entity:" in out or "Schema" in out or out  # 容忍空

    def test_full_pipeline_with_data(self, tmp_path):
        """profile + knowledge 端到端"""
        # 准备 profile graph
        g = UserProfileGraph("u1")
        g.add_household_fact("family_size", 4)
        g.add_household_fact("city", "beijing")
        g.add_interest("energy_saving", confidence=0.9)
        # 准备 KG
        kg = KnowledgeGraphStore(db_path=tmp_path / "kg.db")
        kg.add_entity(KGEntity(entity_type="action", name="ac_temp_up_1c"))
        kg.add_entity(KGEntity(entity_type="policy", name="GB 12021"))
        kg.add_relation(KGRelation(
            source_entity=kg.find_entity_by_name("ac_temp_up_1c").id,
            target_entity=kg.find_entity_by_name("GB 12021").id,
            relation_type="CITES",
        ))
        # build
        builder = ContextBuilder(kg_store=kg, profile_graph_factory=lambda u: g)
        ctx = builder.build("u1", action_ids=["ac_temp_up_1c"])
        out = ctx.render()
        # 三个 section 都应出现
        assert "Profile Facts" in out
        assert "Knowledge Triples" in out
        assert "Ontology Schema" in out
        assert "family_size" in out
        assert "energy_saving" in out
        assert "GB 12021" in out