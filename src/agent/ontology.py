"""
P13 Ontology — 全领域本体模型(画像图谱 + 知识图谱共享 schema)

设计要点:
  · 启动时加载 config/ontology.json(只读)
  · 暴露 Entity / Relation / Invariant 三个 dataclass
  · validate(profile_dict) 返回 (is_valid, violations[]) — 可用于画像校验、LLM 输出反向校验
  · 字段约束(ranges / enums)从 schema 自动推导,不需要手写
  · 不依赖 networkx,纯 dataclass + dict 实现(减小依赖面)

使用示例:
    from agent.ontology import get_ontology, validate_profile, validate_action

    onto = get_ontology()                      # 单例加载
    ok, violations = validate_profile(profile_dict)
    for v in violations:
        log.warning(f"[ontology] {v.rule_id}: {v.message} (path={v.field_path})")
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_log = logging.getLogger(__name__)

# 默认 schema 路径(可被 get_ontology(schema_path=...) 覆盖,便于测试)
_DEFAULT_SCHEMA = Path(__file__).resolve().parents[2] / "config" / "ontology.json"


# ============ 数据结构 ============

@dataclass(frozen=True)
class PropertySpec:
    """实体属性的 schema 描述"""
    name: str
    type: str  # "string"|"int"|"float"|"bool"|"array"|"object"
    required: bool = False
    range: Optional[Tuple[float, float]] = None
    enum: Optional[List[str]] = None
    item_type: Optional[str] = None  # for arrays
    min_length: Optional[int] = None
    description: str = ""


@dataclass(frozen=True)
class EntitySpec:
    """实体类型的 schema 描述"""
    name: str
    description: str
    properties: Dict[str, PropertySpec] = field(default_factory=dict)


@dataclass(frozen=True)
class RelationSpec:
    """关系类型的 schema 描述"""
    name: str
    from_type: str
    to_type: str
    cardinality: str  # "1:1" | "1:N" | "N:1" | "N:N"
    description: str = ""


@dataclass(frozen=True)
class InvariantSpec:
    """不变量规则的 schema 描述(规则字符串 + 自然语言描述)"""
    id: str
    scope: str
    rule: str  # 半形式化规则(供人读,不做形式化执行)
    message: str


@dataclass
class Violation:
    """校验失败记录"""
    rule_id: str
    message: str
    field_path: str = ""
    actual_value: Any = None


@dataclass
class Ontology:
    """本体模型实例(从 schema 加载)"""
    version: str
    domain: str
    entities: Dict[str, EntitySpec]
    relations: Dict[str, RelationSpec]
    invariants: List[InvariantSpec]
    node_type_mapping: Dict[str, Dict[str, str]]

    def entity(self, name: str) -> Optional[EntitySpec]:
        return self.entities.get(name)

    def relation(self, name: str) -> Optional[RelationSpec]:
        return self.relations.get(name)


# ============ 单例加载器 ============

_ontology: Optional[Ontology] = None
_ontology_lock = threading.Lock()


def _load_schema(path: Path) -> Ontology:
    """从 JSON 文件加载 ontology"""
    raw = json.loads(path.read_text(encoding="utf-8"))

    entities: Dict[str, EntitySpec] = {}
    for ename, edef in raw.get("entities", {}).items():
        props: Dict[str, PropertySpec] = {}
        for pname, pdef in edef.get("properties", {}).items():
            rng = pdef.get("range")
            props[pname] = PropertySpec(
                name=pname,
                type=pdef.get("type", "string"),
                required=pdef.get("required", False),
                range=tuple(rng) if rng else None,
                enum=pdef.get("enum"),
                item_type=pdef.get("item_type"),
                min_length=pdef.get("min_length"),
                description=pdef.get("description", ""),
            )
        entities[ename] = EntitySpec(
            name=ename,
            description=edef.get("description", ""),
            properties=props,
        )

    relations: Dict[str, RelationSpec] = {}
    for rname, rdef in raw.get("relations", {}).items():
        relations[rname] = RelationSpec(
            name=rname,
            from_type=rdef["from"],
            to_type=rdef["to"],
            cardinality=rdef.get("cardinality", "N:N"),
            description=rdef.get("description", ""),
        )

    invariants: List[InvariantSpec] = []
    for iv in raw.get("invariants", []):
        invariants.append(InvariantSpec(
            id=iv["id"],
            scope=iv["scope"],
            rule=iv["rule"],
            message=iv["message"],
        ))

    return Ontology(
        version=raw.get("version", "0.0.0"),
        domain=raw.get("domain", "unknown"),
        entities=entities,
        relations=relations,
        invariants=invariants,
        node_type_mapping=raw.get("node_type_mapping", {}),
    )


def get_ontology(schema_path: Optional[Path] = None) -> Ontology:
    """线程安全的单例加载"""
    global _ontology
    if _ontology is not None and schema_path is None:
        return _ontology
    with _ontology_lock:
        if _ontology is not None and schema_path is None:
            return _ontology
        path = Path(schema_path) if schema_path else _DEFAULT_SCHEMA
        if not path.exists():
            raise FileNotFoundError(f"ontology schema not found: {path}")
        _ontology = _load_schema(path)
        _log.info("[ontology] loaded v%s domain=%s entities=%d relations=%d invariants=%d",
                  _ontology.version, _ontology.domain,
                  len(_ontology.entities), len(_ontology.relations), len(_ontology.invariants))
        return _ontology


def reset_ontology_cache() -> None:
    """测试用 — 重置单例以便重新加载"""
    global _ontology
    with _ontology_lock:
        _ontology = None


# ============ 校验逻辑 ============

def _validate_property(value: Any, spec: PropertySpec, path: str) -> List[Violation]:
    """校验单个属性,返回 violations 列表(空 = 通过)"""
    violations: List[Violation] = []

    # 1) required
    if spec.required and value is None:
        violations.append(Violation(
            rule_id="MISSING_REQUIRED",
            message=f"必填字段缺失: {spec.name}",
            field_path=path,
            actual_value=None,
        ))
        return violations  # 缺失必填字段后跳过其他检查

    # 2) None 跳过(可选字段)
    if value is None:
        return violations

    # 3) type
    if spec.type == "int":
        if not isinstance(value, int) or isinstance(value, bool):
            violations.append(Violation(
                rule_id="TYPE_ERROR",
                message=f"期望 int, 实际 {type(value).__name__}",
                field_path=path,
                actual_value=value,
            ))
            return violations
    elif spec.type == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            violations.append(Violation(
                rule_id="TYPE_ERROR",
                message=f"期望 float, 实际 {type(value).__name__}",
                field_path=path,
                actual_value=value,
            ))
            return violations
    elif spec.type == "bool":
        if not isinstance(value, bool):
            violations.append(Violation(
                rule_id="TYPE_ERROR",
                message=f"期望 bool, 实际 {type(value).__name__}",
                field_path=path,
                actual_value=value,
            ))
            return violations
    elif spec.type == "string":
        if not isinstance(value, str):
            violations.append(Violation(
                rule_id="TYPE_ERROR",
                message=f"期望 string, 实际 {type(value).__name__}",
                field_path=path,
                actual_value=value,
            ))
            return violations
        if spec.min_length is not None and len(value) < spec.min_length:
            violations.append(Violation(
                rule_id="MIN_LENGTH",
                message=f"字符串长度 < {spec.min_length}",
                field_path=path,
                actual_value=value,
            ))
    elif spec.type == "array":
        if not isinstance(value, list):
            violations.append(Violation(
                rule_id="TYPE_ERROR",
                message=f"期望 array, 实际 {type(value).__name__}",
                field_path=path,
                actual_value=value,
            ))
            return violations
        if spec.item_type == "string":
            non_str = [x for x in value if not isinstance(x, str)]
            if non_str:
                violations.append(Violation(
                    rule_id="ARRAY_ITEM_TYPE",
                    message=f"array 应全为 string, 找到 {len(non_str)} 个非 string",
                    field_path=path,
                    actual_value=non_str[0],
                ))

    # 4) range
    if spec.range is not None and isinstance(value, (int, float)) and not isinstance(value, bool):
        lo, hi = spec.range
        if not (lo <= value <= hi):
            violations.append(Violation(
                rule_id="RANGE_ERROR",
                message=f"值 {value} 超出范围 [{lo}, {hi}]",
                field_path=path,
                actual_value=value,
            ))

    # 5) enum
    if spec.enum is not None and value not in spec.enum:
        violations.append(Violation(
            rule_id="ENUM_ERROR",
            message=f"值 '{value}' 不在允许集 {spec.enum}",
            field_path=path,
            actual_value=value,
        ))

    return violations


def _validate_entity(obj: Dict[str, Any], spec: EntitySpec, path_prefix: str = "") -> List[Violation]:
    """校验一个实体对象"""
    violations: List[Violation] = []
    for pname, pspec in spec.properties.items():
        ppath = f"{path_prefix}.{pname}" if path_prefix else pname
        value = obj.get(pname)
        violations.extend(_validate_property(value, pspec, ppath))
    return violations


# ============ 公共校验 API ============

def validate_profile(profile_dict: Dict[str, Any]) -> Tuple[bool, List[Violation]]:
    """校验 HouseholdProfile 字典(画像域)

    返回 (is_valid, violations)。
    """
    onto = get_ontology()
    all_violations: List[Violation] = []

    # Household 实体
    household_spec = onto.entity("Household")
    if household_spec:
        all_violations.extend(_validate_entity(profile_dict, household_spec, "Household"))

    # Appliances(数组)
    apps = profile_dict.get("appliances") or []
    if not isinstance(apps, list):
        all_violations.append(Violation(
            rule_id="TYPE_ERROR",
            message="appliances 应为 array",
            field_path="appliances",
            actual_value=apps,
        ))
    else:
        for i, a in enumerate(apps):
            if isinstance(a, str) and a:
                # 字符串 appliance:只校验非空
                continue
            if isinstance(a, dict):
                app_spec = onto.entity("Appliance")
                if app_spec:
                    all_violations.extend(_validate_entity(a, app_spec, f"appliances[{i}]"))

    # Habit 实体
    habit_spec = onto.entity("Habit")
    habits = profile_dict.get("habits") or {}
    if habit_spec and isinstance(habits, dict):
        for hkey, hval in habits.items():
            all_violations.extend(_validate_property(hval, PropertySpec(
                name=hkey, type="float" if isinstance(hval, float) else "int" if isinstance(hval, int) and not isinstance(hval, bool) else "string"
            ), f"habits.{hkey}"))

    # Bill(可多条)
    for bill_key in ("monthly_electricity_bill", "monthly_water_bill", "monthly_gas_bill"):
        bill_val = profile_dict.get(bill_key)
        if bill_val is not None:
            all_violations.extend(_validate_property(
                bill_val,
                PropertySpec(name=bill_key, type="float", range=(0, 5000)),
                bill_key,
            ))

    # Preference
    pref_spec = onto.entity("Preference")
    if pref_spec:
        pref_obj = {k: profile_dict.get(k) for k in ("priority", "excluded_actions", "already_doing") if k in profile_dict}
        all_violations.extend(_validate_entity(pref_obj, pref_spec, "Preference"))

    # INV_HOUSEHOLD_BOUNDS
    family_size = profile_dict.get("family_size")
    home_size = profile_dict.get("home_size_sqm")
    if family_size is not None and (family_size < 1 or family_size > 20):
        all_violations.append(Violation(
            rule_id="INV_HOUSEHOLD_BOUNDS",
            message="家庭人数 ∈ [1, 20]",
            field_path="family_size",
            actual_value=family_size,
        ))
    if home_size is not None and (home_size < 10 or home_size > 2000):
        all_violations.append(Violation(
            rule_id="INV_HOUSEHOLD_BOUNDS",
            message="家庭面积 ∈ [10, 2000] m²",
            field_path="home_size_sqm",
            actual_value=home_size,
        ))

    # INV_PREFERENCE_EXCLUDES
    excluded = set(profile_dict.get("excluded_actions") or [])
    rec_action_ids = profile_dict.get("_recommendation_action_ids") or []
    for aid in rec_action_ids:
        if aid in excluded:
            all_violations.append(Violation(
                rule_id="INV_PREFERENCE_EXCLUDES",
                message=f"推荐了用户已排除的行动: {aid}",
                field_path="_recommendation_action_ids",
                actual_value=aid,
            ))

    return (len(all_violations) == 0, all_violations)


def validate_action(action_dict: Dict[str, Any]) -> Tuple[bool, List[Violation]]:
    """校验 Action 字典(画像 / 知识域共有)

    返回 (is_valid, violations)。
    """
    onto = get_ontology()
    action_spec = onto.entity("Action")
    if not action_spec:
        return (True, [])

    all_violations = _validate_entity(action_dict, action_spec, "Action")

    # INV_ACTION_NEEDS_SOURCE: 可量化行动必须有 CITES ≥ 1 Policy
    if action_dict.get("estimate_kind") in ("reference", "calculated"):
        cites = action_dict.get("cited_policies") or []
        if not cites:
            all_violations.append(Violation(
                rule_id="INV_ACTION_NEEDS_SOURCE",
                message=f"行动 {action_dict.get('id', '?')} 可量化但无 CITES 政策溯源",
                field_path="cited_policies",
                actual_value=cites,
            ))

    # INV_ACTION_SOURCE_NONEMPTY
    src = action_dict.get("source_ref") or ""
    if not src.strip():
        all_violations.append(Violation(
            rule_id="INV_ACTION_SOURCE_NONEMPTY",
            message=f"行动 {action_dict.get('id', '?')} source_ref 为空",
            field_path="source_ref",
            actual_value=src,
        ))

    return (len(all_violations) == 0, all_violations)


def validate_plan_actions(plan_dict: Dict[str, Any]) -> Tuple[bool, List[Violation]]:
    """校验整张方案的所有 actions(端到端用)"""
    actions = plan_dict.get("actions") or []
    all_violations: List[Violation] = []
    for i, a in enumerate(actions):
        _, vs = validate_action(a)
        for v in vs:
            v.field_path = f"actions[{i}].{v.field_path}"
            all_violations.append(v)
    return (len(all_violations) == 0, all_violations)


# ============ 便捷查询 ============

def list_entity_names() -> List[str]:
    """所有实体名(供 LLM 提示使用)"""
    return list(get_ontology().entities.keys())


def list_relation_names() -> List[str]:
    """所有关系名(供 LLM 提示使用)"""
    return list(get_ontology().relations.keys())


def entity_spec_for_llm(entity_name: str) -> str:
    """生成 LLM 可读的实体 schema 描述"""
    spec = get_ontology().entity(entity_name)
    if not spec:
        return f"(unknown entity: {entity_name})"
    lines = [f"Entity: {entity_name} ({spec.description})"]
    for pname, p in spec.properties.items():
        constraint = ""
        if p.range:
            constraint = f" ∈ {p.range}"
        elif p.enum:
            constraint = f" ∈ {p.enum}"
        req = " REQUIRED" if p.required else ""
        lines.append(f"  - {pname}: {p.type}{req}{constraint} — {p.description}")
    return "\n".join(lines)


__all__ = [
    "Ontology",
    "EntitySpec",
    "RelationSpec",
    "InvariantSpec",
    "PropertySpec",
    "Violation",
    "get_ontology",
    "reset_ontology_cache",
    "validate_profile",
    "validate_action",
    "validate_plan_actions",
    "list_entity_names",
    "list_relation_names",
    "entity_spec_for_llm",
]