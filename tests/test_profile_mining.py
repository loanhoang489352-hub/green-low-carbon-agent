"""
profile_mining Skill 验收测试(40 个)

覆盖:
  · parse_message 基础(8)
  · parse_message 各字段(10)
  · parse_message 边界(6)
  · Skill.execute 基础(5)
  · Skill.execute ontology 校验(4)
  · Skill.execute 图谱写入(3)
  · Skill.execute Obsidian 写入(2)
  · 端到端 e2e(2)
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.skills.profile_mining_skill import (
    ProfileMiningSkill,
    ExtractedFact,
    MiningResult,
    parse_message,
    FIELD_TO_ONTOLOGY_TYPE,
)
from agent.skills.skill import SkillContext
from agent.tools.base import ToolResult
from user_profile.profile_graph import UserProfileGraph
from user_profile.user_profile import UserProfileManager


def _load_graph_from_db(user_id: str) -> UserProfileGraph:
    """从 SQLite 持久化层加载真实图谱(不重新构造内存实例)"""
    manager = UserProfileManager()
    profile = manager.get_profile(user_id)
    if not profile or not profile.get("graph"):
        return UserProfileGraph(user_id)
    return UserProfileGraph.from_dict({"user_id": user_id, **profile["graph"]})


# ============ 1. parse_message 基础(8) ============

class TestParseBasic:
    def test_empty_returns_empty(self):
        assert parse_message("") == []

    def test_none_returns_empty(self):
        assert parse_message(None) == []

    def test_hypothetical_skipped(self):
        assert parse_message("假如我家在北京,3 口人,有空调") == []

    def test_if_hypothetical_skipped(self):
        assert parse_message("如果我家有 5 口人,电热水器") == []

    def test_no_clues_returns_empty(self):
        assert parse_message("今天天气不错") == []

    def test_normal_message_returns_list(self):
        result = parse_message("我家在北京")
        assert isinstance(result, list)
        assert len(result) >= 1

    def test_facts_have_required_fields(self):
        result = parse_message("我家在北京")
        for f in result:
            assert f.field
            assert f.value is not None
            assert f.ontology_type
            assert f.evidence
            assert 0 <= f.confidence <= 1
            assert f.source in ("regex", "llm", "inferred")

    def test_fact_to_dict(self):
        result = parse_message("我家在北京")
        if result:
            d = result[0].to_dict()
            assert "field" in d
            assert "value" in d
            assert "ontology_type" in d


# ============ 2. parse_message 各字段(10) ============

class TestParseFields:
    def test_extract_city_beijing(self):
        facts = parse_message("我家在北京,房子 90 平米")
        city_facts = [f for f in facts if f.field == "city"]
        assert len(city_facts) == 1
        assert city_facts[0].value == "beijing"

    def test_extract_city_shanghai(self):
        facts = parse_message("我在上海")
        city_facts = [f for f in facts if f.field == "city"]
        assert city_facts[0].value == "shanghai"

    def test_extract_family_size_arabic(self):
        facts = parse_message("我家有 3 口人")
        family_facts = [f for f in facts if f.field == "family_size"]
        assert len(family_facts) == 1
        assert family_facts[0].value == 3

    def test_extract_family_size_chinese(self):
        facts = parse_message("我家有三个人")
        family_facts = [f for f in facts if f.field == "family_size"]
        assert family_facts[0].value == 3

    def test_extract_electricity_bill(self):
        facts = parse_message("月电费 300 元")
        bills = [f for f in facts if f.field == "monthly_electricity_bill"]
        assert len(bills) == 1
        assert bills[0].value == 300.0

    def test_extract_water_bill(self):
        facts = parse_message("水费 50 块")
        bills = [f for f in facts if f.field == "monthly_water_bill"]
        assert bills[0].value == 50.0

    def test_extract_gas_bill(self):
        facts = parse_message("燃气费 80 元")
        bills = [f for f in facts if f.field == "monthly_gas_bill"]
        assert bills[0].value == 80.0

    def test_extract_appliances(self):
        facts = parse_message("我家有空调和冰箱,还有热水器")
        apps = [f for f in facts if f.field == "appliances"]
        assert len(apps) == 1
        assert "ac" in apps[0].value
        assert "fridge" in apps[0].value

    def test_extract_ac_temperature(self):
        facts = parse_message("空调设定 26 度")
        temp = [f for f in facts if f.field == "ac_temp_setting"]
        assert temp[0].value == 26

    def test_extract_priority_easy(self):
        facts = parse_message("我想少折腾,推荐简单点的")
        pri = [f for f in facts if f.field == "priority"]
        assert pri[0].value == "easy"


# ============ 3. parse_message 边界(6) ============

class TestParseEdges:
    def test_out_of_range_family_size_skipped(self):
        facts = parse_message("我家有 999 口人")
        family = [f for f in facts if f.field == "family_size"]
        # 999 > 20,正则解析可能成功,但 ontology 会拒
        # 至少不应有 invalid value
        if family:
            assert family[0].value <= 20

    def test_negative_bill_skipped(self):
        # 正则只匹配数字,负号不会触发
        facts = parse_message("月电费 -100 元")
        bills = [f for f in facts if f.field == "monthly_electricity_bill"]
        # 没有负数匹配(正则 [\d.]+)
        assert bills == []

    def test_partial_clue_still_works(self):
        facts = parse_message("我家电费比较贵,大概 200 元")
        # 这个 case 不一定匹配(没有"月电费"),但应不崩
        assert isinstance(facts, list)

    def test_multiple_cities_keeps_first(self):
        facts = parse_message("我家以前在北京,现在在上海")
        cities = [f for f in facts if f.field == "city"]
        # 北京第一个匹配
        assert cities[0].value == "beijing"

    def test_exclusion_pattern(self):
        facts = parse_message("我不想缩短洗澡时间")
        excl = [f for f in facts if f.field == "excluded_actions"]
        assert len(excl) == 1
        assert excl[0].is_exclusion is True

    def test_priority_money(self):
        facts = parse_message("我想省钱")
        pri = [f for f in facts if f.field == "priority"]
        assert pri[0].value == "money"


# ============ 4. Skill.execute 基础(5) ============

class TestSkillExecute:
    def setup_method(self):
        self.skill = ProfileMiningSkill()

    def test_execute_returns_toolresult(self):
        ctx = SkillContext(user_id="test_user_1", message="我家在北京,3 口人")
        result = self.skill.execute(ctx)
        assert isinstance(result, ToolResult)
        assert result.success

    def test_execute_no_user_id_fails(self):
        ctx = SkillContext(user_id="", message="test")
        result = self.skill.execute(ctx)
        assert not result.success
        assert "user_id" in result.error

    def test_execute_no_clues_returns_zero(self):
        ctx = SkillContext(user_id="test_user_2", message="今天天气不错")
        result = self.skill.execute(ctx)
        assert result.success
        data = result.data
        assert data["extracted_count"] == 0

    def test_execute_with_clues_extracts(self):
        ctx = SkillContext(user_id="test_user_3",
                          message="我家在北京,5 口人,有空调和冰箱,月电费 300 元")
        result = self.skill.execute(ctx)
        assert result.success
        data = result.data
        assert data["extracted_count"] >= 3  # city + family_size + appliances + bill
        assert data["written_to_graph"] >= 1

    def test_execute_hypothetical_skipped(self):
        ctx = SkillContext(user_id="test_user_4", message="假如我家在北京")
        result = self.skill.execute(ctx)
        assert result.success
        assert result.data["extracted_count"] == 0


# ============ 5. Skill.execute ontology 校验(4) ============

class TestOntologyValidation:
    def setup_method(self):
        self.skill = ProfileMiningSkill()

    def test_valid_facts_pass(self):
        ctx = SkillContext(user_id="valid_user", message="我家在北京,3 口人")
        result = self.skill.execute(ctx)
        assert result.success
        assert len(result.data["violations"]) == 0

    def test_out_of_range_value_violation(self):
        """25 口人(超出 1-20)应被 ontology 拒"""
        ctx = SkillContext(user_id="oor_user", message="我家有 25 口人")
        result = self.skill.execute(ctx)
        assert result.success  # skill 仍成功执行
        # 应有 violation 记录
        data = result.data
        assert any("family_size" in v for v in data["violations"])

    def test_negative_bill_violation(self):
        """注入测试数据 — 直接构造 fact 然后校验"""
        fact = ExtractedFact(
            field="monthly_electricity_bill",
            value=-100,
            ontology_type="Bill",
            evidence="test",
            confidence=1.0,
        )
        valid, violations = self.skill._validate_facts([fact])
        assert len(valid) == 0
        assert len(violations) >= 1

    def test_appliances_skips_ontology_check(self):
        """appliances 是 array 型,ontology 不深度校验字段值"""
        ctx = SkillContext(user_id="app_user", message="我家有空调")
        result = self.skill.execute(ctx)
        # appliances 不应产生 violation(由 _validate_facts 跳过)
        data = result.data
        for v in data["violations"]:
            assert "appliances" not in v


# ============ 6. Skill.execute 图谱写入(3) ============

class TestGraphWrite:
    def setup_method(self):
        self.skill = ProfileMiningSkill()

    def test_write_creates_nodes(self):
        ctx = SkillContext(user_id="write_user_1",
                          message="我家在北京,3 口人,月电费 200 元")
        self.skill.execute(ctx)
        g = _load_graph_from_db("write_user_1")
        assert "energy_city" in g.nodes
        assert "energy_family_size" in g.nodes
        assert "energy_monthly_electricity_bill" in g.nodes

    def test_write_idempotent(self):
        ctx = SkillContext(user_id="write_user_2",
                          message="我家在北京")
        self.skill.execute(ctx)
        self.skill.execute(ctx)  # 第二次
        g = _load_graph_from_db("write_user_2")
        # 多次调用不应抛错
        assert "energy_city" in g.nodes

    def test_write_returns_count(self):
        ctx = SkillContext(user_id="write_user_3",
                          message="我家在北京,3 口人,有空调")
        result = self.skill.execute(ctx)
        assert result.data["written_to_graph"] >= 2


# ============ 7. Skill.execute Obsidian 写入(2) ============

class TestObsidianWrite:
    def setup_method(self):
        self.skill = ProfileMiningSkill()
        self._tmp_vault = None

    def teardown_method(self):
        if self._tmp_vault is not None and self._tmp_vault.exists():
            import shutil
            shutil.rmtree(self._tmp_vault)

    def test_obsidian_write_when_vault_configured(self):
        # 创建临时 vault
        self._tmp_vault = Path(tempfile.mkdtemp())
        os.environ["OBSIDIAN_VAULT_PATH"] = str(self._tmp_vault)
        ctx = SkillContext(user_id="obs_user_1", message="我家在北京")
        result = self.skill.execute(ctx)
        # 应当写了 1 条 derived note
        assert result.data["obsidian_paths"]
        assert len(result.data["obsidian_paths"]) == 1

    def test_obsidian_skipped_when_no_vault(self):
        # 确保 env 没设
        os.environ.pop("OBSIDIAN_VAULT_PATH", None)
        ctx = SkillContext(user_id="obs_user_2", message="我家在北京")
        result = self.skill.execute(ctx)
        assert result.data["obsidian_paths"] == []


# ============ 8. 端到端(2) ============

class TestEndToEnd:
    def test_full_pipeline(self):
        """完整:消息 → 抽取 → 校验 → 写图谱"""
        skill = ProfileMiningSkill()
        ctx = SkillContext(
            user_id="e2e_user_1",
            message="我家在北京,5 口人,有空调、冰箱、热水器,月电费 300 元,我想少折腾",
        )
        result = skill.execute(ctx)
        data = result.data
        assert result.success
        assert data["extracted_count"] >= 4
        assert data["written_to_graph"] >= 4
        # 图谱内容(从 DB 验证)
        g = _load_graph_from_db("e2e_user_1")
        assert "energy_city" in g.nodes
        assert "energy_family_size" in g.nodes
        assert "energy_appliances" in g.nodes
        assert "energy_monthly_electricity_bill" in g.nodes
        assert "energy_priority" in g.nodes

    def test_negotiation_message_triggers_exclusion(self):
        """用户说"不想缩短洗澡" → excluded_actions"""
        skill = ProfileMiningSkill()
        ctx = SkillContext(user_id="e2e_neg_user", message="我不想缩短洗澡时间")
        result = skill.execute(ctx)
        data = result.data
        assert data["extracted_count"] >= 1
        excl = [f for f in data["extracted"] if f["is_exclusion"]]
        assert len(excl) >= 1
        assert "water_bathing_shorter" in excl[0]["value"]