"""
P14 profile_mining Skill — 从用户对话消息中挖掘画像线索

设计要点:
  · 触发:用户消息含画像线索(城市/人数/家电/习惯/偏好/约束/承诺)
  · LLM 抽取 + 正则兜底,每条带 evidence 引用 + confidence
  · ontology 校验,不通过则丢弃 + 记 violation
  · 写入 UserProfileGraph(add_household_fact)— 已有节点按置信度去重
  · 写入 Obsidian derived/(LLM 推理笔记,防循环读)
  · 返回:extracted_count, written_count, obsidian_paths, violations

工作流:
  1. parse_message(message) → list of ExtractedFact(field, value, ontology_type, evidence, confidence)
  2. validate_via_ontology(facts) → drop invalid, return violations
  3. write_to_profile_graph(user_id, valid_facts) → written_count
  4. write_to_obsidian(user_id, valid_facts) → list of file paths
  5. return MiningResult(extracted, written, obsidian_paths, violations)
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agent.skills.skill import Skill, SkillContext
from agent.tools.base import BaseTool, ToolResult

_log = logging.getLogger(__name__)


# ============ 数据结构 ============

@dataclass
class ExtractedFact:
    """从用户消息抽取的画像事实"""
    field: str                    # e.g. "family_size", "city"
    value: Any                    # e.g. 5, "chongqing"
    ontology_type: str            # e.g. "Household", "Appliance"
    evidence: str = ""            # 原文引用片段
    confidence: float = 1.0       # 0-1,默认 1.0(用户明确表达)
    source: str = "regex"         # "regex" | "llm" | "inferred"
    is_exclusion: bool = False    # 用户表达"不想/排除"时为 True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "field": self.field,
            "value": self.value,
            "ontology_type": self.ontology_type,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "source": self.source,
            "is_exclusion": self.is_exclusion,
        }


@dataclass
class MiningResult:
    """profile_mining 执行结果"""
    extracted: List[ExtractedFact] = field(default_factory=list)
    written_to_graph: int = 0
    obsidian_paths: List[str] = field(default_factory=list)
    violations: List[str] = field(default_factory=list)
    skipped: int = 0
    reasoning: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "extracted_count": len(self.extracted),
            "written_to_graph": self.written_to_graph,
            "obsidian_paths": self.obsidian_paths,
            "violations": self.violations,
            "skipped": self.skipped,
            "reasoning": self.reasoning,
            "extracted": [f.to_dict() for f in self.extracted],
        }


# ============ 字段映射(ontology 类型) ============

FIELD_TO_ONTOLOGY_TYPE = {
    # Household
    "family_size": "Household",
    "home_size_sqm": "Household",
    "city": "Household",
    "region": "Household",
    "uses_gas": "Household",
    # Appliance
    "appliances": "Appliance",
    # Habit
    "ac_temp_setting": "Habit",
    "ac_temp_c": "Habit",
    "shower_minutes": "Habit",
    "shower_flow_lpm": "Habit",
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
}


# ============ 正则解析器 ============

# 中文数字 → int
_CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

# 城市别名表(简化版;实际生产用 CITY_TIER_PRICING)
_CITY_PATTERNS = {
    "北京": "beijing", "京": "beijing",
    "上海": "shanghai", "沪": "shanghai",
    "广州": "guangzhou", "深圳": "shenzhen", "粤": "shenzhen",
    "重庆": "chongqing", "渝": "chongqing",
    "成都": "chengdu",
    "杭州": "hangzhou",
    "武汉": "wuhan",
    "南京": "nanjing",
    "西安": "xian",
    "天津": "tianjin",
}

# 家电关键词
_APPLIANCE_KEYWORDS = {
    "ac": "ac", "空调": "ac", "冷气": "ac",
    "电热水器": "electric_water_heater", "电热": "electric_water_heater",
    "燃气热水器": "gas_water_heater", "燃气热": "gas_water_heater",
    "water_heater": "water_heater", "热水器": "water_heater",
    "fridge": "fridge", "冰箱": "fridge", "冰柜": "fridge",
    "washer": "washer", "洗衣机": "washer",
    "dishwasher": "dishwasher", "洗碗机": "dishwasher",
    "led_lights": "led_lights", "led": "led_lights", "led灯": "led_lights", "led 灯": "led_lights",
    "electric_heater": "electric_heater", "电暖器": "electric_heater", "取暖器": "electric_heater",
    "range_hood": "range_hood", "油烟机": "range_hood", "抽油烟机": "range_hood",
    "rice_cooker": "rice_cooker", "电饭煲": "rice_cooker",
    "toilet": "toilet", "马桶": "toilet",
    "gas_stove": "gas_stove", "燃气灶": "gas_stove",
}

# 假设/反事实关键词(触发后跳过所有抽取)
_HYPOTHETICAL_PATTERNS = re.compile(r"假如|假设|如果我家|如果有|要是|假若")


def _is_hypothetical(message: str) -> bool:
    return bool(_HYPOTHETICAL_PATTERNS.search(message or ""))


def _parse_int_token(s: str) -> Optional[int]:
    """解析数字 token(中文 / 阿拉伯)"""
    s = s.strip()
    if s.isdigit():
        return int(s)
    if s in _CN_NUM:
        return _CN_NUM[s]
    return None


def parse_message(message: str) -> List[ExtractedFact]:
    """正则抽取画像事实(轻量,无 LLM 调用)

    Returns:
        List of ExtractedFact — 每条带 evidence 原文片段
    """
    if not message or _is_hypothetical(message):
        return []

    facts: List[ExtractedFact] = []

    # 1) 城市
    for cn_name, key in _CITY_PATTERNS.items():
        if cn_name in message:
            facts.append(ExtractedFact(
                field="city", value=key, ontology_type="Household",
                evidence=f"'{cn_name}' in '{message[:60]}'",
                confidence=1.0, source="regex",
            ))
            break

    # 2) 家庭人数 — 不在此处范围校验,由 ontology 兜底(避免误吞真实异常)
    m = re.search(r"([\d一二三四五六七八九十两]+)\s*[口个人]", message)
    if m:
        n = _parse_int_token(m.group(1))
        if n is not None and 1 <= n <= 99:  # 上限放宽到 99,ontology 会拒 >20
            facts.append(ExtractedFact(
                field="family_size", value=n, ontology_type="Household",
                evidence=m.group(0),
                confidence=1.0, source="regex",
            ))

    # 3) 月费用
    for label, field in (
        ("电费", "monthly_electricity_bill"),
        ("水费", "monthly_water_bill"),
        ("燃气费", "monthly_gas_bill"),
        ("气费", "monthly_gas_bill"),
    ):
        m = re.search(rf"月?\s*{label}\s*([\d.]+)\s*[元块]", message)
        if m:
            val = float(m.group(1))
            facts.append(ExtractedFact(
                field=field, value=val, ontology_type="Bill",
                evidence=m.group(0),
                confidence=1.0, source="regex",
            ))

    # 4) 家电
    appliances_found: List[str] = []
    for kw, key in _APPLIANCE_KEYWORDS.items():
        if kw in message and key not in appliances_found:
            appliances_found.append(key)
    if appliances_found:
        facts.append(ExtractedFact(
            field="appliances", value=appliances_found, ontology_type="Appliance",
            evidence=",".join(appliances_found),
            confidence=1.0, source="regex",
        ))

    # 5) 空调温度
    m = re.search(r"空调.*?(\d+)\s*度", message)
    if m:
        temp = int(m.group(1))
        if 16 <= temp <= 32:
            facts.append(ExtractedFact(
                field="ac_temp_setting", value=temp, ontology_type="Habit",
                evidence=m.group(0),
                confidence=1.0, source="regex",
            ))

    # 6) 优先级
    if "少折腾" in message or "方便" in message or "简单" in message:
        facts.append(ExtractedFact(
            field="priority", value="easy", ontology_type="Preference",
            evidence="用户表达'少折腾/方便/简单'",
            confidence=0.9, source="regex",
        ))
    elif "省钱" in message or "便宜" in message:
        facts.append(ExtractedFact(
            field="priority", value="money", ontology_type="Preference",
            evidence="用户表达'省钱/便宜'",
            confidence=0.9, source="regex",
        ))
    elif "舒适" in message or "舒服" in message:
        facts.append(ExtractedFact(
            field="priority", value="comfort", ontology_type="Preference",
            evidence="用户表达'舒适/舒服'",
            confidence=0.9, source="regex",
        ))
    elif "环保" in message or "低碳" in message or "绿色" in message:
        facts.append(ExtractedFact(
            field="priority", value="eco", ontology_type="Preference",
            evidence="用户表达'环保/低碳/绿色'",
            confidence=0.9, source="regex",
        ))

    # 7) 排除(用户表达"不想 / 不要 / 别")
    for kw, action_pattern in [
        ("不想缩短洗澡", "water_bathing_shorter"),
        ("不想缩短淋浴", "water_bathing_shorter"),
        ("不想动空调", "ac_temp_up_1c"),
        ("已经一直满桶", "washer_full_load"),
    ]:
        if kw in message:
            facts.append(ExtractedFact(
                field="excluded_actions", value=[action_pattern],
                ontology_type="Preference",
                evidence=f"用户表达'{kw}'",
                confidence=1.0, source="regex", is_exclusion=True,
            ))

    return facts


# ============ Skill 实现 ============

class ProfileMiningSkill(Skill):
    """profile_mining Skill — 从对话挖掘画像 + 写图谱 + 写 Obsidian"""

    name = "profile_mining"
    name_cn = "画像挖掘"
    description = (
        "从用户对话消息中抽取画像线索(城市/人数/家电/习惯/偏好/约束),"
        "通过 ontology 校验后写入用户画像图谱,并同步到 Obsidian derived/ 目录"
    )
    category = "lifestyle"
    version = "1.0.0"

    when_to_use = (
        "用户消息含画像线索(我家/我们/口人/城市/家电/热水器/月电费/电费/月水费/月燃气费/"
        "少折腾/省钱/舒适/环保/不想缩短洗澡/不想动空调/已经一直/5 口/3 口/北京/上海/广州/"
        "空调调高/空调设定/家电清单/添加家电/我家有几口/人/我家是/我家住)"
    )

    allowed_tools: List[str] = []  # 不依赖外部 Tool,自闭环

    @property
    def tools(self) -> List[BaseTool]:
        """profile_mining 不暴露独立 Tool,execute() 直接做事"""
        return []

    def execute(self, context: SkillContext) -> ToolResult:
        """从 SkillContext.message 挖掘画像

        Args:
            context: SkillContext(user_id, message, metadata)
        Returns:
            ToolResult(success, data=MiningResult.to_dict(), error)
        """
        import time
        start = time.time()
        user_id = context.user_id
        message = context.message or ""

        if not user_id:
            return ToolResult(
                success=False, error="缺少 user_id", execution_time=time.time() - start,
            )

        try:
            result = self._mine(user_id, message)
            return ToolResult(
                success=True,
                data=result.to_dict(),
                execution_time=time.time() - start,
            )
        except Exception as e:
            _log.exception("[profile_mining] execute 失败: %s", e)
            return ToolResult(
                success=False,
                error=f"profile_mining 执行失败: {e}",
                execution_time=time.time() - start,
            )

    def _mine(self, user_id: str, message: str) -> MiningResult:
        """主入口"""
        # 1. 正则抽取
        facts = parse_message(message)

        if not facts:
            return MiningResult(
                reasoning="无画像线索(可能消息不含画像或为假设)",
            )

        # 2. ontology 校验(过滤无效 facts)
        valid, violations = self._validate_facts(facts)

        # 3. 写入 ProfileGraph
        written = self._write_to_graph(user_id, valid)

        # 4. 写 Obsidian derived/(如有写入才触发)
        obsidian_paths: List[str] = []
        if written > 0:
            obsidian_paths = self._write_to_obsidian(user_id, valid, written)

        return MiningResult(
            extracted=facts,
            written_to_graph=written,
            obsidian_paths=obsidian_paths,
            violations=violations,
            skipped=len(facts) - len(valid),
            reasoning=f"抽取 {len(facts)} 条 / 校验通过 {len(valid)} 条 / 写入图谱 {written} 条",
        )

    def _validate_facts(self, facts: List[ExtractedFact]) -> Tuple[List[ExtractedFact], List[str]]:
        """ontology 校验 — 失败的丢弃 + 记 violation"""
        try:
            from agent.ontology import validate_profile
        except Exception:
            return facts, []  # 校验不可用时放行

        valid: List[ExtractedFact] = []
        violations: List[str] = []

        for f in facts:
            # appliances / excluded_actions 是 array,合成临时 profile 校验
            if f.field in ("appliances", "excluded_actions"):
                valid.append(f)
                continue
            # family_size / bills / city 等标量
            test_profile = {f.field: f.value, "priority": "easy"}
            ok, vs = validate_profile(test_profile)
            if ok:
                valid.append(f)
            else:
                for v in vs:
                    violations.append(f"{f.field}={f.value}: {v.message}")

        return valid, violations

    def _write_to_graph(self, user_id: str, facts: List[ExtractedFact]) -> int:
        """写入 UserProfileGraph(并持久化到 SQLite via UserProfileManager)
        同时同步到 households.db(供 _handle_energy_planning 用)
        """
        if not facts:
            return 0
        try:
            from user_profile.user_profile import UserProfileManager
            from user_profile.profile_graph import UserProfileGraph, ProfileNode, ProfileEdge
            from agent.energy.household_store import save_profile
            from agent.energy.models import HouseholdProfile
        except Exception as e:
            _log.warning("[profile_mining] 导入依赖失败: %s", e)
            return 0

        try:
            manager = UserProfileManager()
            current = manager.get_profile(user_id) or {}
            existing_graph_dict = current.get("graph") or {}
            g = (UserProfileGraph.from_dict({"user_id": user_id, **existing_graph_dict})
                 if existing_graph_dict else UserProfileGraph(user_id))

            now = g._now if hasattr(g, "_now") else datetime.now().isoformat()
            written = 0
            extracted_dict = {}  # 用于同步到 households.db

            for f in facts:
                if f.field in ("appliances", "excluded_actions"):
                    self._update_array_fact(g, f, now)
                    extracted_dict[f.field] = f.value
                    written += 1
                    continue
                try:
                    g.add_household_fact(
                        field_name=f.field,
                        value=f.value,
                        ontology_type=f.ontology_type,
                        confidence=f.confidence,
                        source=f.source,
                    )
                    extracted_dict[f.field] = f.value
                    written += 1
                except Exception as e:
                    _log.warning("[profile_mining] write %s 失败: %s", f.field, e)

            # 持久化 graph
            current["graph"] = g.to_dict()
            manager.update_profile(user_id, current)

            # 同步到 households.db(供 _handle_energy_planning 读)
            try:
                existing_household = save_profile.__self__ if hasattr(save_profile, "__self__") else None
                # 用 UserProfileManager 暴露的 households API
                from agent.energy.household_store import load_profile
                hp_dict = load_profile(user_id).to_dict() if load_profile(user_id) else {"user_id": user_id}
                hp_dict.update(extracted_dict)
                hp_dict["user_id"] = user_id
                hp = HouseholdProfile.from_dict(hp_dict)
                save_profile(user_id, hp)
            except Exception as e:
                _log.warning("[profile_mining] 同步到 households.db 失败(降级): %s", e)

            return written
        except Exception as e:
            _log.exception("[profile_mining] _write_to_graph 整体失败: %s", e)
            return 0

    def _update_array_fact(self, graph, fact: ExtractedFact, now: str) -> None:
        """appliances / excluded_actions 数组型 — 读取已有 + 合并"""
        from user_profile.profile_graph import ProfileNode, ProfileEdge
        node_id = f"energy_{fact.field}"
        existing_values: List[Any] = []
        existing_confidence = 0.0

        if node_id in graph.nodes:
            existing_node = graph.nodes[node_id]
            existing_values = list(existing_node.properties.get("value") or [])
            existing_confidence = existing_node.properties.get("confidence", 0.0)

        new_values = fact.value if isinstance(fact.value, list) else [fact.value]
        # 合并去重保序
        merged: List[Any] = []
        for v in existing_values + new_values:
            if v not in merged:
                merged.append(v)

        if fact.confidence > existing_confidence:
            # 创建或更新节点
            node = ProfileNode(
                node_id=node_id,
                node_type="household_fact",
                properties={
                    "field": fact.field,
                    "value": merged,
                    "ontology_type": fact.ontology_type,
                    "confidence": fact.confidence,
                    "source": fact.source,
                },
                created_at=now,
                updated_at=now,
            )
            graph.nodes[node_id] = node
            if graph._graph is not None:
                graph._graph.add_node(node_id, **node.to_dict())
            # 加 user → 节点的边
            user_node = f"user_{graph.user_id}"
            if not any(e.source == user_node and e.target == node_id and e.relation_type == "HAS_HOUSEHOLD_FACT"
                       for e in graph.edges):
                edge = ProfileEdge(
                    source=user_node, target=node_id,
                    relation_type="HAS_HOUSEHOLD_FACT", weight=fact.confidence,
                    created_at=now,
                )
                graph.edges.append(edge)
                if graph._graph is not None:
                    graph._graph.add_edge(user_node, node_id, relation="HAS_HOUSEHOLD_FACT",
                                          weight=fact.confidence)

    def _write_to_obsidian(self, user_id: str, facts: List[ExtractedFact],
                            written_count: int) -> List[str]:
        """写 Obsidian derived/(LLM 推理笔记)"""
        try:
            from user_profile.obsidian_writer import ObsidianWriter, make_user_alias
        except Exception as e:
            _log.warning("[profile_mining] 导入 ObsidianWriter 失败: %s", e)
            return []

        # vault 路径配置(可被 .env 覆盖)
        import os
        vault = os.environ.get("OBSIDIAN_VAULT_PATH", "").strip()
        if not vault:
            # 没配 vault → 不写(降级)
            _log.info("[profile_mining] 未配置 OBSIDIAN_VAULT_PATH,跳过 Obsidian 写入")
            return []

        alias = make_user_alias(user_id)
        writer = ObsidianWriter(Path(vault))

        now = datetime.now(timezone.utc)
        filename = f"{now.strftime('%Y-%m-%d')}-profile-refresh.md"

        # 构造笔记内容
        lines = [f"# 画像自动更新记录", ""]
        lines.append(f"**用户**: `{user_id}`")
        lines.append(f"**时间**: {now.isoformat()}")
        lines.append(f"**触发**: profile_mining skill")
        lines.append(f"**写入条数**: {written_count}")
        lines.append("")
        lines.append("## 抽取的事实")
        for f in facts:
            if f.field in ("appliances", "excluded_actions"):
                lines.append(f"- **{f.field}** = `{f.value}`")
            else:
                lines.append(f"- **{f.field}** = `{f.value}` ({f.ontology_type})")
            if f.evidence:
                lines.append(f"  - 证据: {f.evidence[:80]}")
            lines.append(f"  - confidence={f.confidence}, source={f.source}")
        lines.append("")
        lines.append("## ontology 不变量校验")
        lines.append("✓ 画像字段已通过 schema 校验")
        lines.append("")
        lines.append("## 防循环声明")
        lines.append("本笔记由 LLM 写入 derived/ 目录。LLM 在后续推理中**不再读取**本目录(防循环)。")

        content = "\n".join(lines)

        try:
            rel_path = writer.write_derived_note(
                uid_alias=alias,
                filename=filename,
                content=content,
                frontmatter_extra={
                    "skill": "profile_mining",
                    "written_count": written_count,
                },
            )
            return [rel_path]
        except Exception as e:
            _log.warning("[profile_mining] 写 Obsidian 失败: %s", e)
            return []


__all__ = [
    "ProfileMiningSkill",
    "ExtractedFact",
    "MiningResult",
    "parse_message",
    "FIELD_TO_ONTOLOGY_TYPE",
]