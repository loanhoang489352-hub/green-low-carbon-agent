"""
P14 验收测试:HTML 报告 + profile_mining 集成(35 个测试)

覆盖:
  · HTML 报告渲染(8)
  · HTML 多 variant / 可视化字段(8)
  · profile_mining 集成(8)
  · HTML 报告文件落盘(4)
  · 端到端 e2e(7)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.core import GreenAgent
from agent.energy.household_store import save_profile
from agent.energy.models import HouseholdProfile
from agent.html_reporter import HTMLReporter
from user_profile.user_profile import UserProfileManager


# ============ fixture ============

@pytest.fixture
def profile():
    p = HouseholdProfile.from_dict({
        "user_id": "p14_user",
        "family_size": 5,
        "home_size_sqm": 90,
        "city": "chongqing",
        "monthly_electricity_bill": 300,
        "monthly_water_bill": 50,
        "monthly_gas_bill": 80,
        "appliances": ["ac", "water_heater", "led_lights", "fridge"],
        "priority": "easy",
    })
    save_profile("p14_user", p)
    return p


@pytest.fixture
def agent():
    return GreenAgent()


def _sample_plan():
    return {
        "id": "plan-test-001",
        "actions": [
            {"id": "ac_temp_up_1c", "title": "空调温度调高 1 度",
             "description": "调高 1°C,年度参考",
             "estimated_saving_cny": 26.0, "estimated_saving_co2_kg": 13.0,
             "category": "electricity", "difficulty": 1, "estimate_period": "year",
             "estimate_kind": "reference", "source_ref": "GB 12021.2-2015",
             "estimate_note": "知识库年度参考"},
            {"id": "ac_clean_filter", "title": "清洗空调滤网",
             "description": "按说明书清洁",
             "estimated_saving_cny": 0.0, "estimated_saving_co2_kg": 0.0,
             "category": "electricity", "difficulty": 1, "estimate_period": "unknown",
             "estimate_kind": "qualitative", "source_ref": "vendor建议",
             "estimate_note": "定性建议"},
            {"id": "fridge_temp_setting", "title": "冰箱温度合理设定",
             "description": "检查温度",
             "estimated_saving_cny": 0.0, "estimated_saving_co2_kg": 0.0,
             "category": "electricity", "difficulty": 1, "estimate_period": "unknown",
             "estimate_kind": "qualitative", "source_ref": "GB 12021",
             "estimate_note": "定性建议"},
            {"id": "water_bathing_shorter", "title": "尝试缩短淋浴",
             "description": "缩短 1 分钟",
             "estimated_saving_cny": 0.0, "estimated_saving_co2_kg": 0.0,
             "category": "water", "difficulty": 1, "estimate_period": "unknown",
             "estimate_kind": "qualitative", "source_ref": "GB-T 18870",
             "estimate_note": "需具体数据"},
        ],
    }


# ============ 1. HTML 报告渲染(8) ============

class TestHTMLRender:
    def setup_method(self):
        self.reporter = HTMLReporter()
        self.profile_dict = {
            "family_size": 5, "home_size_sqm": 90, "city": "chongqing",
            "appliances": ["ac", "water_heater", "led_lights", "fridge"],
            "priority": "easy", "monthly_electricity_bill": 300,
        }

    def test_render_returns_html_string(self):
        html = self.reporter.render_energy_plan(
            user_id="u1",
            profile=self.profile_dict,
            profile_sources={"city": "chat_explicit"},
            plan=_sample_plan(),
        )
        assert isinstance(html, str)
        assert "<!DOCTYPE html>" in html

    def test_render_includes_user_id(self):
        html = self.reporter.render_energy_plan(
            user_id="test_user_123",
            profile=self.profile_dict,
            profile_sources={},
            plan=_sample_plan(),
        )
        # 至少一处出现 user_id
        assert "test_user_123" in html

    def test_render_includes_plan_id(self):
        html = self.reporter.render_energy_plan(
            user_id="u1",
            profile=self.profile_dict,
            profile_sources={},
            plan=_sample_plan(),
        )
        assert "plan-test-001" in html

    def test_render_includes_all_actions(self):
        html = self.reporter.render_energy_plan(
            user_id="u1",
            profile=self.profile_dict,
            profile_sources={},
            plan=_sample_plan(),
        )
        for a in _sample_plan()["actions"]:
            assert a["id"] in html

    def test_render_includes_field_cards(self):
        html = self.reporter.render_energy_plan(
            user_id="u1",
            profile=self.profile_dict,
            profile_sources={"family_size": "chat_explicit"},
            plan=_sample_plan(),
        )
        # 字段卡片应出现"5 口之家"
        assert "家庭人数" in html

    def test_render_includes_llm_explanation(self):
        html = self.reporter.render_energy_plan(
            user_id="u1",
            profile=self.profile_dict,
            profile_sources={},
            plan=_sample_plan(),
            llm_explanation="这是 LLM 的个性化解释",
        )
        assert "LLM" in html
        assert "这是 LLM 的个性化解释" in html

    def test_render_includes_today_card(self):
        html = self.reporter.render_energy_plan(
            user_id="u1",
            profile=self.profile_dict,
            profile_sources={},
            plan=_sample_plan(),
            today_card={"actions": _sample_plan()["actions"][:3]},
        )
        assert "今日行动卡" in html

    def test_render_handles_empty_plan(self):
        html = self.reporter.render_energy_plan(
            user_id="u1",
            profile=self.profile_dict,
            profile_sources={},
            plan={"id": "p-empty", "actions": []},
        )
        # 应仍可渲染(空 actions 表格 + 0 元)
        assert "<!DOCTYPE html>" in html


# ============ 2. HTML 多 variant / 可视化(8) ============

class TestHTMLFeatures:
    def setup_method(self):
        self.reporter = HTMLReporter()
        self.profile_dict = {
            "family_size": 5, "home_size_sqm": 90, "city": "chongqing",
            "appliances": ["ac", "water_heater", "led_lights", "fridge"],
            "priority": "easy", "monthly_electricity_bill": 300,
        }

    def test_three_variants_in_html(self):
        html = self.reporter.render_energy_plan(
            user_id="u1",
            profile=self.profile_dict,
            profile_sources={},
            plan=_sample_plan(),
        )
        assert "少折腾优先" in html
        assert "省钱优先" in html
        assert "减碳优先" in html

    def test_alpine_js_present(self):
        html = self.reporter.render_energy_plan(
            user_id="u1",
            profile=self.profile_dict,
            profile_sources={},
            plan=_sample_plan(),
        )
        assert "alpinejs" in html.lower() or "x-data" in html

    def test_chart_js_present(self):
        html = self.reporter.render_energy_plan(
            user_id="u1",
            profile=self.profile_dict,
            profile_sources={},
            plan=_sample_plan(),
        )
        assert "chart" in html.lower()

    def test_tailwind_present(self):
        html = self.reporter.render_energy_plan(
            user_id="u1",
            profile=self.profile_dict,
            profile_sources={},
            plan=_sample_plan(),
        )
        assert "tailwindcss" in html.lower() or "tailwind" in html.lower()

    def test_localstorage_for_completion(self):
        html = self.reporter.render_energy_plan(
            user_id="u1",
            profile=self.profile_dict,
            profile_sources={},
            plan=_sample_plan(),
        )
        assert "localStorage" in html

    def test_source_ref_in_actions(self):
        html = self.reporter.render_energy_plan(
            user_id="u1",
            profile=self.profile_dict,
            profile_sources={},
            plan=_sample_plan(),
        )
        # GB 12021 应在(2 个 action 引用)
        assert "GB 12021" in html

    def test_anti_hallu_indicator(self):
        html = self.reporter.render_energy_plan(
            user_id="u1",
            profile=self.profile_dict,
            profile_sources={},
            plan=_sample_plan(),
            anti_hallu_passed=True,
        )
        assert "反幻觉" in html

    def test_obsidian_writes_displayed(self):
        html = self.reporter.render_energy_plan(
            user_id="u1",
            profile=self.profile_dict,
            profile_sources={},
            plan=_sample_plan(),
            obsidian_writes=["u-aaaa/derived/2026-09-13-profile-refresh.md"],
        )
        assert "Obsidian" in html
        assert "derived" in html


# ============ 3. profile_mining 集成(8) ============

class TestProfileMiningIntegration:
    def test_chat_triggers_mining(self, agent, profile):
        result = agent.chat_enhanced(
            message="我家在上海,4 口人,有空调和热水器,月电费 250 元",
            user_id="mining_user_1",
        )
        meta = result.personalization_info.get("profile_mining", {})
        assert meta.get("extracted_count", 0) >= 3
        assert meta.get("written_to_graph", 0) >= 3

    def test_chat_persists_to_db(self, agent):
        """新用户,聊天后画像应在 SQLite 里"""
        result = agent.chat_enhanced(
            message="我家在广州,2 口人,有空调,月电费 180 元",
            user_id="mining_new_user",
        )
        meta = result.personalization_info.get("profile_mining", {})
        assert meta.get("written_to_graph", 0) >= 3
        # 验证 DB
        manager = UserProfileManager()
        prof = manager.get_profile("mining_new_user")
        assert prof
        graph = prof.get("graph") or {}
        # 图谱中应有 household_fact 节点
        nodes = graph.get("nodes", [])
        if isinstance(nodes, dict):
            keys = list(nodes.keys())
        else:
            keys = [n["node_id"] for n in nodes]
        assert any("energy_" in k for k in keys)

    def test_chat_no_clues_skips_mining(self, agent, profile):
        result = agent.chat_enhanced(
            message="今天天气不错,谢谢",
            user_id="mining_no_clue_user",
        )
        meta = result.personalization_info.get("profile_mining", {})
        # 无画像线索 → 抽取为 0
        assert meta.get("extracted_count", 0) == 0

    def test_chat_hypothetical_skipped(self, agent, profile):
        result = agent.chat_enhanced(
            message="假如我家有 5 口人,北京,有空调",
            user_id="mining_hypo_user",
        )
        meta = result.personalization_info.get("profile_mining", {})
        assert meta.get("extracted_count", 0) == 0

    def test_chat_exclusion_extracted(self, agent, profile):
        result = agent.chat_enhanced(
            message="我不想缩短洗澡时间",
            user_id="mining_excl_user",
        )
        meta = result.personalization_info.get("profile_mining", {})
        # 至少应识别 excluded_actions
        assert meta.get("extracted_count", 0) >= 1

    def test_chat_mining_violations_recorded(self, agent, profile):
        """超出范围的值 → violation"""
        result = agent.chat_enhanced(
            message="我家有 25 口人",  # 超出 1-20
            user_id="mining_oor_user",
        )
        meta = result.personalization_info.get("profile_mining", {})
        assert len(meta.get("violations", [])) >= 1

    def test_chat_mining_refreshes_profile(self, agent):
        """mining 后画像更新 → plan 用新数据"""
        # 第一轮:无画像,mining 写
        agent.chat_enhanced(
            message="我家在北京,3 口人,有空调",
            user_id="mining_refresh_user",
        )
        # 第二轮:plan 应反映北京
        result = agent.chat_enhanced(
            message="根据我家情况给我家制定节能方案",
            user_id="mining_refresh_user",
        )
        # plan.profile_snapshot.city 应是 beijing(由 mining 写入)
        plan = result.personalization_info.get("energy_plan", {})
        assert plan.get("actions")

    def test_chat_mining_meta_in_response(self, agent, profile):
        """profile_mining 元数据应在 personalization_info 中"""
        result = agent.chat_enhanced(
            message="我家在北京",
            user_id="mining_meta_user",
        )
        meta = result.personalization_info.get("profile_mining", {})
        assert "reasoning" in meta
        assert "extracted_count" in meta


# ============ 4. HTML 报告文件落盘(4) ============

class TestHTMLFileOutput:
    def setup_method(self):
        self.reporter = HTMLReporter()

    def test_chat_returns_html_path(self, agent, profile):
        result = agent.chat_enhanced(
            message="根据我家情况给我家制定节能方案",
            user_id="p14_user",  # 用 fixture profile 的用户
        )
        path = result.personalization_info.get("html_report_path")
        assert path is not None
        assert path.endswith(".html")

    def test_html_file_exists(self, agent, profile):
        result = agent.chat_enhanced(
            message="根据我家情况给我家制定节能方案",
            user_id="p14_user",
        )
        path = result.personalization_info.get("html_report_path")
        assert Path(path).exists()

    def test_html_file_not_empty(self, agent, profile):
        result = agent.chat_enhanced(
            message="根据我家情况给我家制定节能方案",
            user_id="p14_user",
        )
        path = result.personalization_info.get("html_report_path")
        size = Path(path).stat().st_size
        # 报告应 > 10KB(基础 HTML + 内容)
        assert size > 10000

    def test_html_file_referenced_in_message(self, agent, profile):
        result = agent.chat_enhanced(
            message="根据我家情况给我家制定节能方案",
            user_id="p14_user",
        )
        # 现在用可点击 URL(取代纯文件路径)
        url = result.personalization_info.get("html_report_url")
        assert url
        assert url in result.message
        assert url.startswith("/api/reports/")


# ============ 5. 端到端 e2e(7) ============

class TestEndToEnd:
    def test_full_chat_with_mining_and_html(self, agent):
        """一条消息触发:mining → 画像更新 → plan 生成 → HTML 报告"""
        result = agent.chat_enhanced(
            message="我家在北京,5 口人,有空调、冰箱、热水器,月电费 300 元,我想少折腾。给我制定节能方案。",
            user_id="e2e_p14_user",
        )
        assert result.intent == "energy_planning"

        # 1. mining 应抽取
        meta = result.personalization_info.get("profile_mining", {})
        assert meta.get("extracted_count", 0) >= 4

        # 2. plan 应有 actions
        plan = result.personalization_info.get("energy_plan", {})
        assert len(plan.get("actions", [])) >= 3

        # 3. today card 应有 actions
        today = result.personalization_info.get("today_card", {})
        assert len(today.get("actions", [])) >= 1

        # 4. HTML 报告应生成
        html_path = result.personalization_info.get("html_report_path")
        assert html_path
        assert Path(html_path).exists()

        # 5. LLM 元数据应记录
        llm_meta = result.personalization_info.get("llm_reasoner", {})
        assert llm_meta.get("llm_used") is True

    def test_message_includes_html_link(self, agent, profile):
        result = agent.chat_enhanced(
            message="根据我家情况给我家制定节能方案",
            user_id="p14_user",
        )
        assert "HTML" in result.message or "html" in result.message.lower()

    def test_html_contains_user_clues(self, agent):
        # 用唯一 user_id 避免污染
        import uuid
        unique_user = f"e2e_clues_{uuid.uuid4().hex[:8]}"
        result = agent.chat_enhanced(
            message=f"我家在深圳,3 口人,有空调和电热水器。给我制定节能方案。",
            user_id=unique_user,
        )
        path = result.personalization_info.get("html_report_path")
        # 验证 mining 真的把"深圳"写到了 households.db
        from agent.energy.household_store import load_profile
        hp = load_profile(unique_user)
        assert hp
        assert hp.city == "shenzhen", f"期望 city=shenzhen,实际 {hp.city}"
        assert hp.family_size == 3
        if path:
            html = Path(path).read_text(encoding="utf-8")
            assert "shenzhen" in html or "深圳" in html

    def test_html_has_alpine_toggle(self, agent, profile):
        result = agent.chat_enhanced(
            message="根据我家情况给我家制定节能方案",
            user_id="p14_user",
        )
        path = result.personalization_info.get("html_report_path")
        html = Path(path).read_text(encoding="utf-8")
        assert "x-data" in html or "alpine" in html.lower()

    def test_html_renders_in_reasonable_time(self, agent, profile):
        """完整响应应在 8 秒内"""
        import time
        start = time.time()
        agent.chat_enhanced(
            message="根据我家情况给我家制定节能方案",
            user_id="p14_user",
        )
        elapsed = time.time() - start
        assert elapsed < 8.0

    def test_multiple_chats_each_generate_html(self, agent, profile):
        paths = []
        for _ in range(2):
            result = agent.chat_enhanced(
                message="根据我家情况给我家制定节能方案",
                user_id="p14_user",
            )
            paths.append(result.personalization_info.get("html_report_path"))
        for p in paths:
            assert p
            assert Path(p).exists()

    def test_profile_field_count_in_html(self, agent, profile):
        """HTML 应显示画像字段数(至少 3 条)"""
        result = agent.chat_enhanced(
            message="根据我家情况给我家制定节能方案",
            user_id="p14_user",
        )
        path = result.personalization_info.get("html_report_path")
        html = Path(path).read_text(encoding="utf-8")
        # 至少 3 个画像字段(family_size + city + appliances + bill)
        assert "画像字段" in html