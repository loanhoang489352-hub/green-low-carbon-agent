"""
Step 6 Part 1 验收测试:LLM Reasoner + 反幻觉护栏(35 个测试)

覆盖:
  · JSON 解析(含 markdown 容错)(5)
  · explain 基础(5)
  · explain 反幻觉护栏(5)
  · negotiate 替换(5)
  · negotiate 拒绝伪造 action_id(3)
  · ask_missing_info(4)
  · AntiHallucinationGuard.verify(8)
"""
from __future__ import annotations

import json
import pytest

from agent.llm_reasoner import (
    LLMReasoner,
    LLMReasonerResult,
    LLMClient,
    MockLLMClient,
    AntiHallucinationGuard,
    make_reasoner,
    PROMPT_EXPLAIN,
    PROMPT_NEGOTIATE,
    PROMPT_ASK_INFO,
    SYSTEM_PROMPT,
)


# ============ 1. JSON 解析(5) ============

class TestJsonParsing:
    def setup_method(self):
        self.r = LLMReasoner()

    def test_parse_clean_json(self):
        d = self.r._parse_json_response('{"a": 1, "b": "x"}')
        assert d == {"a": 1, "b": "x"}

    def test_parse_markdown_json(self):
        raw = "```json\n{\"a\": 1}\n```"
        d = self.r._parse_json_response(raw)
        assert d == {"a": 1}

    def test_parse_markdown_no_lang(self):
        raw = "```\n{\"a\": 1}\n```"
        d = self.r._parse_json_response(raw)
        assert d == {"a": 1}

    def test_parse_extract_from_text(self):
        raw = "思考一下... \n{\"a\": 1, \"b\": [2,3]}\n 解释完毕"
        d = self.r._parse_json_response(raw)
        assert d == {"a": 1, "b": [2, 3]}

    def test_parse_invalid_returns_empty(self):
        assert self.r._parse_json_response("not json at all") == {}


# ============ 2. explain 基础(5) ============

class TestExplainBasic:
    def setup_method(self):
        self.llm = MockLLMClient()
        self.r = LLMReasoner(self.llm)

    def _plan(self):
        return {
            "actions": [
                {
                    "id": "ac_temp_up_1c",
                    "title": "空调温度调高 1 度",
                    "estimated_saving_cny": 26.0,
                    "estimated_saving_co2_kg": 13.0,
                    "source_ref": "standard:GB 12021",
                },
            ]
        }

    def test_explain_returns_result(self):
        result = self.r.explain("", "", "", self._plan(), "test message")
        assert isinstance(result, LLMReasonerResult)
        assert result.explanation
        assert not result.used_template_fallback

    def test_explain_calls_llm(self):
        self.r.explain("prof", "know", "schema", self._plan(), "msg")
        assert len(self.llm.calls) == 1
        # prompt 含 system + user
        assert self.llm.calls[0]["system"] == SYSTEM_PROMPT
        assert "ac_temp_up_1c" in self.llm.calls[0]["user"]

    def test_explan_confidence_parsed(self):
        self.llm.response = json.dumps({
            "explanation": "ok", "follow_up_questions": [],
            "confidence": 0.92,
        })
        result = self.r.explain("", "", "", self._plan())
        assert result.confidence == 0.92

    def test_explan_follow_up_questions_parsed(self):
        self.llm.response = json.dumps({
            "explanation": "ok",
            "follow_up_questions": ["q1", "q2"],
            "confidence": 0.5,
        })
        result = self.r.explain("", "", "", self._plan())
        assert result.follow_up_questions == ["q1", "q2"]

    def test_explain_failure_falls_back(self):
        class FailingLLM(LLMClient):
            def chat(self, system, user):
                raise RuntimeError("LLM down")

        r = LLMReasoner(FailingLLM())
        result = r.explain("", "", "", self._plan())
        assert result.used_template_fallback is True


# ============ 3. explain 反幻觉护栏(5) ============

class TestExplainAntiHallucination:
    def setup_method(self):
        self.llm = MockLLMClient()
        self.r = LLMReasoner(self.llm)

    def _plan(self):
        return {
            "actions": [
                {"id": "x", "estimated_saving_cny": 26.0, "estimated_saving_co2_kg": 13.0},
            ]
        }

    def test_explanation_with_real_amount_passes(self):
        self.llm.response = json.dumps({
            "explanation": "约 ¥26/年的参考值适用你",
            "confidence": 0.8,
        })
        result = self.r.explain("", "", "", self._plan())
        assert not result.used_template_fallback

    def test_explanation_with_fake_amount_falls_back(self):
        self.llm.response = json.dumps({
            "explanation": "约 ¥999 的参考值适用你",  # 999 不在 plan 中
            "confidence": 0.8,
        })
        result = self.r.explain("", "", "", self._plan())
        assert result.used_template_fallback is True

    def test_explanation_no_amount_passes(self):
        self.llm.response = json.dumps({
            "explanation": "没有具体金额,只解释逻辑",
            "confidence": 0.7,
        })
        result = self.r.explain("", "", "", self._plan())
        assert not result.used_template_fallback

    def test_explanation_zero_amount_safe(self):
        self.llm.response = json.dumps({
            "explanation": "约 ¥0 不适用",  # 0 不是伪造
            "confidence": 0.7,
        })
        result = self.r.explain("", "", "", self._plan())
        assert not result.used_template_fallback

    def test_explanation_handles_decimal(self):
        self.llm.response = json.dumps({
            "explanation": "约 ¥26.5 是模板",  # 26.5 不在 plan(只有 26.0)
            "confidence": 0.7,
        })
        result = self.r.explain("", "", "", self._plan())
        assert result.used_template_fallback is True


# ============ 4. negotiate 替换(5) ============

class TestNegotiate:
    def setup_method(self):
        self.llm = MockLLMClient()
        self.r = LLMReasoner(self.llm)

    def _plan(self):
        return {
            "actions": [
                {"id": "ac_temp_up_1c", "title": "空调"},
                {"id": "ac_clean_filter", "title": "清洗滤网"},
                {"id": "water_bathing_shorter", "title": "缩短淋浴"},
            ]
        }

    def test_negotiate_replacement_in_plan(self):
        self.llm.response = json.dumps({
            "replacement_action_id": "ac_clean_filter",
            "replacement_rationale": "因为你说不想动温度",
            "negotiation_note": "可以先试清洗滤网",
            "confidence": 0.8,
        })
        result = self.r.negotiate("", "", self._plan(), "不想动空调温度")
        assert result.replacement_action_id == "ac_clean_filter"
        assert "清洗滤网" in result.negotiation_note

    def test_negotiate_replacement_not_in_plan_blocked(self):
        self.llm.response = json.dumps({
            "replacement_action_id": "fake_action_id",  # 不存在
            "replacement_rationale": "x",
            "negotiation_note": "y",
            "confidence": 0.8,
        })
        result = self.r.negotiate("", "", self._plan(), "不想动")
        assert result.replacement_action_id is None
        # rationale 和 note 保留(不强制校验)

    def test_negotiate_null_replacement(self):
        self.llm.response = json.dumps({
            "replacement_action_id": None,
            "replacement_rationale": "无合适替换",
            "negotiation_note": "保留原方案",
            "confidence": 0.5,
        })
        result = self.r.negotiate("", "", self._plan(), "x")
        assert result.replacement_action_id is None

    def test_negotiate_no_replacement_field(self):
        self.llm.response = json.dumps({
            "replacement_rationale": "r", "negotiation_note": "n",
        })
        result = self.r.negotiate("", "", self._plan(), "x")
        assert result.replacement_action_id is None

    def test_negotiate_calls_llm_with_rejection(self):
        self.r.negotiate("", "", self._plan(), "我不想缩短洗澡时间")
        assert "不想缩短洗澡时间" in self.llm.calls[0]["user"]


# ============ 5. AntiHallucinationGuard.verify(8) ============

class TestAntiHallucinationGuard:
    def _plan(self, **overrides):
        base = {
            "actions": [
                {"id": "a1", "estimated_saving_cny": 26.0, "estimated_saving_co2_kg": 13.0,
                 "source_ref": "GB 12021", "estimate_kind": "reference",
                 "difficulty": 1, "estimate_period": "year", "estimated_saving_kwh": 50.0},
                {"id": "a2", "estimated_saving_cny": 0.0, "estimated_saving_co2_kg": 0.0,
                 "source_ref": "vendor建议", "estimate_kind": "qualitative",
                 "difficulty": 1, "estimate_period": "unknown", "estimated_saving_kwh": 0.0},
            ]
        }
        for k, v in overrides.items():
            base[k] = v
        return base

    def test_identical_plan_passes(self):
        p = self._plan()
        assert AntiHallucinationGuard.verify(p, p) is True

    def test_new_action_introduced_blocked(self):
        before = self._plan()
        after = self._plan()
        after["actions"].append({"id": "a3_NEW", "estimated_saving_cny": 10.0})
        assert AntiHallucinationGuard.verify(before, after) is False

    def test_action_deleted_blocked(self):
        before = self._plan()
        after = self._plan()
        after["actions"] = after["actions"][:1]  # 删一个
        assert AntiHallucinationGuard.verify(before, after) is False

    def test_cny_modified_blocked(self):
        before = self._plan()
        after = self._plan()
        after["actions"][0]["estimated_saving_cny"] = 99.0
        assert AntiHallucinationGuard.verify(before, after) is False

    def test_co2_modified_blocked(self):
        before = self._plan()
        after = self._plan()
        after["actions"][0]["estimated_saving_co2_kg"] = 99.0
        assert AntiHallucinationGuard.verify(before, after) is False

    def test_id_changed_blocked(self):
        before = self._plan()
        after = self._plan()
        after["actions"][0]["id"] = "different_id"
        assert AntiHallucinationGuard.verify(before, after) is False

    def test_source_ref_changed_blocked(self):
        before = self._plan()
        after = self._plan()
        after["actions"][0]["source_ref"] = "FAKE_REF"
        assert AntiHallucinationGuard.verify(before, after) is False

    def test_extra_field_in_action_allowed(self):
        """非关键字段(如 title 改变)不影响护栏"""
        before = self._plan()
        after = self._plan()
        after["actions"][0]["title"] = "新标题"
        # title 不在护栏字段列表 → 通过
        assert AntiHallucinationGuard.verify(before, after) is True


# ============ 6. ask_missing_info(4) ============

class TestAskMissingInfo:
    def setup_method(self):
        self.llm = MockLLMClient()
        self.r = LLMReasoner(self.llm)

    def test_returns_questions(self):
        self.llm.response = json.dumps({
            "questions": ["你家几口人?", "用什么热水器?"],
            "confidence": 0.7,
        })
        result = self.r.ask_missing_info("profile", "schema")
        assert result.follow_up_questions == ["你家几口人?", "用什么热水器?"]

    def test_limits_to_5(self):
        self.llm.response = json.dumps({
            "questions": ["q1", "q2", "q3", "q4", "q5", "q6", "q7"],
        })
        result = self.r.ask_missing_info("", "")
        assert len(result.follow_up_questions) == 5

    def test_empty_questions_safe(self):
        self.llm.response = json.dumps({"questions": []})
        result = self.r.ask_missing_info("", "")
        assert result.follow_up_questions == []

    def test_failure_fallback(self):
        class FailingLLM(LLMClient):
            def chat(self, system, user):
                raise RuntimeError("nope")
        r = LLMReasoner(FailingLLM())
        result = r.ask_missing_info("", "")
        assert result.used_template_fallback is True


# ============ 7. 工厂 + dataclass(2) ============

class TestFactory:
    def test_make_reasoner_default(self):
        r = make_reasoner()
        assert isinstance(r, LLMReasoner)
        assert isinstance(r.llm, MockLLMClient)

    def test_make_reasoner_custom(self):
        custom = MockLLMClient()
        r = make_reasoner(custom)
        assert r.llm is custom


# ============ 8. LLMReasonerResult.to_dict(1) ============

class TestResultSerialization:
    def test_to_dict(self):
        r = LLMReasonerResult(
            explanation="x",
            follow_up_questions=["q1"],
            confidence=0.8,
            replacement_action_id="a1",
        )
        d = r.to_dict()
        assert d["explanation"] == "x"
        assert d["follow_up_questions"] == ["q1"]
        assert d["confidence"] == 0.8
        assert d["replacement_action_id"] == "a1"
        assert d["used_template_fallback"] is False