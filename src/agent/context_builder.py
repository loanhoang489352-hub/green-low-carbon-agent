"""
P13 Step 4: Context Builder

功能:
  · 从 ProfileGraph 取 N-hop 子图(profile facts)
  · 从 KnowledgeGraph 取相关子图(policies / actions cited)
  · 把三元组序列化成 LLM prompt 友好的文本
  · 自动注入 ontology schema 摘要(LLM 知道有哪些实体/关系可引用)
  · 防泄漏:PII 脱敏 + 长度截断 + 字段黑名单

输出格式(示例):
  === Profile Facts ===
  (User u1) HAS_HOUSEHOLD_FACT (Household.family_size = 3) [evidence: chat_explicit, confidence=1.0]
  (User u1) HAS_HOUSEHOLD_FACT (Household.city = chongqing)
  ...
  === Knowledge Triples ===
  (Action ac_temp_up_1c) CITES (Policy GB 12021.2-2015)
  ...
  === Ontology Schema ===
  Entity: Household — 家庭(画像域)
    - family_size: int ∈ (1, 20) REQUIRED
    ...
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from agent.ontology import (
    entity_spec_for_llm,
    list_entity_names,
    list_relation_names,
)

_log = logging.getLogger(__name__)


# ============ 配置 ============

# 字段黑名单(不进入 LLM context 的敏感字段)
PII_FIELD_BLACKLIST = {
    "phone", "email", "id_card", "bank_card", "address",
    "user_id_raw", "ip", "ua",
}

# 长度上限(避免 prompt 爆炸)
MAX_CONTEXT_TOKENS = 4000
MAX_FACTS = 60
MAX_TRIPLES = 40


# ============ 数据结构 ============

@dataclass
class ContextOptions:
    """Context Builder 的可选配置"""
    include_profile: bool = True
    include_knowledge: bool = True
    include_schema: bool = True
    profile_hop: int = 2
    knowledge_hop: int = 1
    redact_pii: bool = True
    max_chars: int = 12000


@dataclass
class BuiltContext:
    """组装好的 LLM 上下文"""
    profile_section: str = ""
    knowledge_section: str = ""
    schema_section: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

    def render(self) -> str:
        """合并为单一字符串(可直接喂给 LLM)"""
        parts: List[str] = []
        if self.profile_section:
            parts.append("=== Profile Facts ===\n" + self.profile_section)
        if self.knowledge_section:
            parts.append("\n=== Knowledge Triples ===\n" + self.knowledge_section)
        if self.schema_section:
            parts.append("\n=== Ontology Schema ===\n" + self.schema_section)
        return "\n".join(parts)

    def char_count(self) -> int:
        return len(self.profile_section) + len(self.knowledge_section) + len(self.schema_section)


# ============ PII 脱敏 ============

def _redact_value(value: Any) -> Any:
    """值级 PII 脱敏(简单字符串规则,不依赖 utils.pii 避免循环)"""
    if value is None:
        return None
    if isinstance(value, str):
        v = value.strip()
        # 手机号
        if len(v) == 11 and v.isdigit():
            return v[:3] + "****" + v[-4:]
        # 邮箱
        if "@" in v and "." in v:
            local, _, domain = v.partition("@")
            if len(local) > 1:
                return local[0] + "***@" + domain
        # 身份证(15/18 位)
        if len(v) in (15, 18) and v[:-1].isdigit():
            return v[:3] + "********" + v[-4:]
        # 银行卡(16-19 位数字)
        if len(v) >= 16 and v.isdigit():
            return v[:4] + "****" + v[-4:]
    return value


def _is_pii_field(field_name: str) -> bool:
    """字段名命中 PII 黑名单"""
    f_lower = field_name.lower()
    return any(p in f_lower for p in PII_FIELD_BLACKLIST)


# ============ 序列化器 ============

def _serialize_profile_facts(facts: List[Dict[str, Any]], redact_pii: bool = True) -> str:
    """把 profile graph 节点序列化成三元组文本

    输入:graph.n_hop_subgraph(...)["nodes"] 的列表
    """
    lines: List[str] = []
    for node in facts:
        node_id = node.get("node_id", "?")
        node_type = node.get("node_type", "?")
        props = node.get("properties", {}) or {}

        # user 节点: 锚点,跳过
        if node_type == "user":
            lines.append(f"User: {props.get('user_id', node_id)}")
            continue

        # interest / behavior_stage / knowledge_level
        if node_type == "interest":
            lines.append(f"  HAS_INTEREST ({props.get('interest_id', node_type)}) [confidence={props.get('confidence', 0):.2f}]")
            continue
        if node_type == "behavior_stage":
            lines.append(f"  AT_STAGE ({props.get('stage', '?')})")
            continue
        if node_type == "knowledge_level":
            lines.append(f"  HAS_KNOWLEDGE ({props.get('level', '?')})")
            continue
        if node_type == "preference":
            lines.append(f"  PREFERS ({props.get('value', '?')})")
            continue

        # household_fact (P13 新增)
        if node_type == "household_fact":
            field_name = props.get("field", "?")
            value = props.get("value", "?")
            onto_type = props.get("ontology_type", "Household")
            source = props.get("source", "unknown")
            confidence = props.get("confidence", 1.0)

            # PII 脱敏
            if redact_pii and _is_pii_field(field_name):
                value = "[REDACTED]"
            elif redact_pii:
                value = _redact_value(value)

            evidence = f"evidence: {source}, confidence={confidence:.2f}"
            lines.append(f"  HAS_HOUSEHOLD_FACT ({onto_type}.{field_name} = {value}) [{evidence}]")
            continue

        # 兜底
        lines.append(f"  {node_type.upper()} ({props})")

    return "\n".join(lines)


def _serialize_knowledge_triples(entities: List[Any], relations: List[Any], redact_pii: bool = True) -> str:
    """把 KG 子图序列化成三元组文本"""
    lines: List[str] = []

    # 实体 → name map
    ent_by_id = {e.id: e for e in entities}

    # 先列实体
    for e in entities:
        etype = getattr(e, "entity_type", "?")
        name = getattr(e, "name", "?")
        props = getattr(e, "properties", {}) or {}
        src = getattr(e, "source_doc", "") or ""

        # PII 字段值脱敏
        if redact_pii:
            props = {k: (_redact_value(v) if _is_pii_field(k) else v)
                     for k, v in props.items()}
            name = _redact_value(name) if _is_pii_field("name") else name

        props_str = ""
        if props:
            props_str = " {" + ", ".join(f"{k}={v}" for k, v in props.items()) + "}"
        src_str = f" [src: {src}]" if src else ""
        lines.append(f"  ({etype}: {name}){props_str}{src_str}")

    # 关系
    for r in relations:
        src_ent = ent_by_id.get(r.source_entity)
        tgt_ent = ent_by_id.get(r.target_entity)
        src_name = src_ent.name if src_ent else r.source_entity
        tgt_name = tgt_ent.name if tgt_ent else r.target_entity
        lines.append(f"  ({src_name}) --{r.relation_type}--> ({tgt_name}) [w={r.weight:.2f}]")

    return "\n".join(lines)


def _serialize_schema(entity_names: Optional[List[str]] = None) -> str:
    """ontology schema 摘要(LLM 知道有哪些字段/关系可引用)"""
    if entity_names is None:
        entity_names = ["Household", "Action", "Policy", "Preference", "Appliance", "Habit"]
    parts: List[str] = []
    for name in entity_names:
        spec_text = entity_spec_for_llm(name)
        parts.append(spec_text)
    parts.append("\n# Allowed relations:")
    parts.append("  " + ", ".join(sorted(list_relation_names())))
    return "\n".join(parts)


# ============ 主 API ============

class ContextBuilder:
    """LLM 上下文组装器"""

    def __init__(self,
                 kg_store: Optional[Any] = None,
                 profile_graph_factory: Optional[Any] = None) -> None:
        """Args:
            kg_store: 知识图谱存储(默认懒加载)
            profile_graph_factory: 从 user_id 生成 ProfileGraph 的工厂函数(默认从 SQLite 读取)
        """
        self._kg_store = kg_store
        self._profile_factory = profile_graph_factory

    def _ensure_kg(self):
        if self._kg_store is None:
            from rag.kg_store import get_kg_store
            self._kg_store = get_kg_store()
        return self._kg_store

    def _ensure_profile(self, user_id: str):
        if self._profile_factory is not None:
            return self._profile_factory(user_id)
        # 默认从 SQLite 读 main_profile → 构造 graph
        from user_profile.user_profile import UserProfileManager
        from user_profile.profile_graph import UserProfileGraph
        mgr = UserProfileManager()
        profile_dict = mgr.get_profile(user_id)
        graph = UserProfileGraph(user_id)
        # 加载 graph 子字段(若存在)
        if isinstance(profile_dict, dict) and profile_dict.get("graph"):
            try:
                graph = UserProfileGraph.from_dict({
                    "user_id": user_id,
                    **profile_dict["graph"],
                })
            except Exception:
                pass
        # 把 home_energy_usage 转 household_fact 节点
        usage = ((profile_dict or {}).get("behavior_profile") or {}).get("home_energy_usage") or {}
        for field_name, value in usage.items():
            if field_name.startswith("_") or not isinstance(value, (str, int, float, bool, list)):
                continue
            onto_type = _field_to_ontology_type(field_name)
            graph.add_household_fact(field_name, value, ontology_type=onto_type, source="chat_explicit" if usage.get("_evidence", {}).get(field_name) else "inferred")
        return graph

    def build(self, user_id: str,
              action_ids: Optional[List[str]] = None,
              options: Optional[ContextOptions] = None) -> BuiltContext:
        """组装 LLM 上下文

        Args:
            user_id: 用户ID
            action_ids: 当前 plan 的 action IDs(用于查 KG 中的相关 policies)
            options: 上下文选项
        """
        opts = options or ContextOptions()
        ctx = BuiltContext(meta={
            "user_id": user_id,
            "include_profile": opts.include_profile,
            "include_knowledge": opts.include_knowledge,
            "include_schema": opts.include_schema,
            "action_ids": action_ids or [],
        })

        # 1) Profile subgraph
        if opts.include_profile:
            graph = self._ensure_profile(user_id)
            sg = graph.n_hop_subgraph(hop=opts.profile_hop)
            facts = sg.get("nodes", [])[:MAX_FACTS]
            ctx.profile_section = _serialize_profile_facts(facts, redact_pii=opts.redact_pii)
            ctx.meta["profile_node_count"] = len(facts)
            ctx.meta["profile_edge_count"] = len(sg.get("edges", []))

        # 2) Knowledge subgraph(围绕 action_ids 找相关 policies)
        if opts.include_knowledge and action_ids:
            kg = self._ensure_kg()
            # 找 action 实体(name = action_id)
            roots: List[str] = []
            for aid in action_ids:
                ent = kg.find_entity_by_name(aid, entity_type="action")
                if ent:
                    roots.append(ent.id)
            if roots:
                kg_sg = kg.n_hop_subgraph(roots, hop=opts.knowledge_hop)
                ents = kg_sg.entities[:MAX_TRIPLES]
                rels = kg_sg.relations[:MAX_TRIPLES]
                ctx.knowledge_section = _serialize_knowledge_triples(ents, rels, redact_pii=opts.redact_pii)
                ctx.meta["knowledge_entity_count"] = len(ents)
                ctx.meta["knowledge_relation_count"] = len(rels)
            else:
                ctx.knowledge_section = "(no knowledge entries for the given action_ids)"
        elif opts.include_knowledge:
            ctx.knowledge_section = "(no action_ids provided, knowledge section skipped)"

        # 3) Schema 摘要
        if opts.include_schema:
            ctx.schema_section = _serialize_schema()

        # 4) 长度截断(硬上限,按优先级:schema → profile → knowledge 各自不超过配额)
        total = ctx.char_count()
        if total > opts.max_chars:
            _log.warning("[context_builder] context too long (%d > %d), truncating", total, opts.max_chars)
            # 配额分配:schema 至少留 25%,profile 最多 40%,knowledge 最多 35%
            schema_quota = max(200, opts.max_chars // 4)
            profile_quota = opts.max_chars // 2
            knowledge_quota = opts.max_chars - schema_quota - profile_quota
            if schema_quota > 0 and len(ctx.schema_section) > schema_quota:
                ctx.schema_section = ctx.schema_section[:schema_quota] + "\n[schema truncated]"
            if profile_quota > 0 and len(ctx.profile_section) > profile_quota:
                ctx.profile_section = ctx.profile_section[:profile_quota] + "\n[profile truncated]"
            if knowledge_quota > 0 and len(ctx.knowledge_section) > knowledge_quota:
                ctx.knowledge_section = ctx.knowledge_section[:knowledge_quota] + "\n[knowledge truncated]"
            ctx.meta["truncated"] = True
            ctx.meta["original_chars"] = total

        return ctx


# ============ 工具函数 ============

def _field_to_ontology_type(field_name: str) -> str:
    """household_usage 字段 → ontology 实体类型"""
    mapping = {
        # Household
        "family_size": "Household",
        "home_size_sqm": "Household",
        "city": "Household",
        "region": "Household",
        # Appliance
        "appliances": "Appliance",
        # Habit
        "ac_temp_c": "Habit",
        "ac_temp_setting": "Habit",
        "shower_minutes": "Habit",
        "shower_flow_lpm": "Habit",
        "showers_per_person_week": "Habit",
        "peak_offpeak_usage": "Habit",
        # Bill
        "monthly_electricity_bill": "Bill",
        "monthly_water_bill": "Bill",
        "monthly_gas_bill": "Bill",
        "monthly_electricity_kwh": "Bill",
        # Preference
        "priority": "Preference",
        "already_doing": "Preference",
        "excluded_actions": "Preference",
        # House facts
        "uses_gas": "Household",
        "has_incandescent": "Household",
        "has_drip": "Household",
        "water_price_per_m3": "Bill",
    }
    return mapping.get(field_name, "Household")


def quick_build(user_id: str, action_ids: Optional[List[str]] = None) -> str:
    """便捷 API:返回完整 LLM context 字符串"""
    builder = ContextBuilder()
    ctx = builder.build(user_id, action_ids=action_ids)
    return ctx.render()


__all__ = [
    "ContextBuilder",
    "ContextOptions",
    "BuiltContext",
    "quick_build",
    "_serialize_profile_facts",
    "_serialize_knowledge_triples",
    "_serialize_schema",
]