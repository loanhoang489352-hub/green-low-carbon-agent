"""
P13 Step 6: LLM 推理层 — 反幻觉护栏 + 3 个 prompt

职责:
  · 只做"理解 + 解释 + 谈判 + 反问",不编数字
  · 输入:ontology context + 模板生成的 plan + user message
  · 输出:自然语言回复(分析 + 建议 + 反问)
  · 反幻觉护栏:
      - LLM 输出后,plan.estimated_saving_cny/co2 必须 == 模板值(否则丢弃 LLM 输出回退模板)
      - LLM 输出后,plan.actions[].id 不能变
      - LLM 不能引入新 action(只解释/排序/反问)

3 个 prompt:
  1. explain_priority — 解释为什么这4 个 action 最匹配你
  2. negotiate_tradeoff — 用户表达"不想做X" → 帮替换 + 解释替换逻辑
  3. ask_missing_info — 信息不足 → LLM 主动列出该问的 2-3 个问题

输出 dataclass:
  LLMReasonerResult {
    explanation: str,         # 自然语言分析
    follow_up_questions: list,# 待问用户的问题
    confidence: float,        # 推理置信度 0-1
    used_template_fallback: bool  # 是否回退到纯模板
  }
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from agent.ontology import validate_action

_log = logging.getLogger(__name__)


# ============ 默认 prompt 模板 ============

# 注意:prompt 中明确禁止 LLM 修改数字字段 / 引入新 action / 编 source_ref
SYSTEM_PROMPT = """你是绿色低碳智能体的个性化推理助手。你的职责:
1. 基于给定的"画像事实三元组 + 知识图谱三元组 + 模板生成的节能方案"做个性化解释。
2. **严禁**:修改 estimated_saving_cny / estimated_saving_co2_kg 数值;引入新 action;修改 source_ref。
3. **允许**:解释每个 action 为什么对当前用户最适合;列出 1-3 个追问;评估用户的硬约束是否与方案冲突。
4. **只输出 JSON**,不要 Markdown 代码块,不要自然语言前缀。"""


PROMPT_EXPLAIN = """[画像事实]
{profile_section}

[知识图谱]
{knowledge_section}

[ontology schema]
{schema_section}

[模板生成的方案]
{plan_json}

[用户最近消息]
{user_message}

任务:用 JSON 输出以下内容:
{{
  "explanation": "3-5 句自然语言分析,基于画像事实说明为什么这 4 个 action 对当前用户最匹配。可引用知识图谱的 source_ref。",
  "follow_up_questions": [
    "问题 1(基于 ontology 不变量或用户画像缺失字段)",
    "问题 2(可选)"
  ],
  "confidence": 0.0-1.0  # 你对解释质量的自信度
}}

约束:不要在 explanation 中给出具体节省金额数字(那是模板的事)。只解释'为什么'。
"""


PROMPT_NEGOTIATE = """[画像事实]
{profile_section}

[ontology schema]
{schema_section}

[当前方案]
{plan_json}

[用户表达的不接受项]
{user_rejection}

任务:基于画像 + 方案,推荐 1-2 个替换行动(只能从 plan.actions 里选,不能引入新 action)。
输出 JSON:
{{
  "replacement_action_id": "现有 plan 中某个 action 的 id,或 null 表示无合适替换",
  "replacement_rationale": "为什么这个替换对用户更合适",
  "negotiation_note": "对用户说的话,温和表达替换建议"
}}
"""


PROMPT_ASK_INFO = """[画像事实]
{profile_section}

[ontology schema]
{schema_section}

任务:基于 ontology 不变量和画像缺失字段,列出最该问用户的 2-3 个问题(避免一次问太多)。
输出 JSON:
{{
  "questions": [
    "问题 1",
    "问题 2",
    "问题 3"
  ]
}}
约束:只问 ontology 必填但缺失的字段,或对方案质量影响最大的字段。
"""


# ============ 数据结构 ============

@dataclass
class LLMReasonerResult:
    """LLM 推理结果(反幻觉护栏后)"""
    explanation: str = ""
    follow_up_questions: List[str] = field(default_factory=list)
    confidence: float = 0.0
    replacement_action_id: Optional[str] = None
    replacement_rationale: str = ""
    negotiation_note: str = ""
    used_template_fallback: bool = False
    raw_llm_response: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "explanation": self.explanation,
            "follow_up_questions": self.follow_up_questions,
            "confidence": self.confidence,
            "replacement_action_id": self.replacement_action_id,
            "replacement_rationale": self.replacement_rationale,
            "negotiation_note": self.negotiation_note,
            "used_template_fallback": self.used_template_fallback,
        }


# ============ 反幻觉护栏 ============

class AntiHallucinationGuard:
    """LLM 输出反幻觉护栏

    校验项:
      1. LLM 输出不能修改 plan.actions[].estimated_saving_cny / co2
      2. LLM 输出不能新增 action
      3. LLM 输出不能修改 action.id
      4. LLM 输出不能修改 action.source_ref
    """

    @staticmethod
    def verify(plan_before: Dict[str, Any],
               plan_after: Dict[str, Any]) -> bool:
        """返回 True 表示 LLM 未篡改 plan 关键字段;False 表示触发护栏

        Args:
            plan_before: 模板生成的原始 plan dict
            plan_after: LLM 处理后的 plan dict(可能只在 explanation 提到数字,不影响 plan 字段)
        """
        actions_before = {a["id"]: a for a in plan_before.get("actions", [])}
        actions_after = {a["id"]: a for a in plan_after.get("actions", [])}

        # 不能新增 action
        if set(actions_after.keys()) - set(actions_before.keys()):
            _log.warning("[anti_hallu] LLM 引入新 action: %s",
                         set(actions_after.keys()) - set(actions_before.keys()))
            return False

        # 不能删除 action
        if set(actions_before.keys()) - set(actions_after.keys()):
            _log.warning("[anti_hallu] LLM 删除 action: %s",
                         set(actions_before.keys()) - set(actions_after.keys()))
            return False

        # 关键数值字段不能改
        for aid, ab in actions_before.items():
            aa = actions_after.get(aid)
            if not aa:
                continue
            for key in ("estimated_saving_cny", "estimated_saving_co2_kg",
                        "estimated_saving_kwh", "source_ref", "id",
                        "estimate_period", "estimate_kind", "difficulty"):
                before_v = ab.get(key)
                after_v = aa.get(key)
                if before_v != after_v:
                    _log.warning("[anti_hallu] LLM 改了 %s[%s]: %s → %s",
                                 aid, key, before_v, after_v)
                    return False
        return True


# ============ LLM 客户端抽象 ============

class LLMClient:
    """LLM 客户端抽象(便于测试 mock)"""

    def chat(self, system: str, user: str) -> str:
        raise NotImplementedError


class MockLLMClient(LLMClient):
    """Mock 客户端 — 用于测试,返回固定 JSON"""

    def __init__(self, response: str = "") -> None:
        self.response = response
        self.calls: List[Dict[str, str]] = []

    def chat(self, system: str, user: str) -> str:
        self.calls.append({"system": system, "user": user})
        if self.response:
            return self.response
        # 默认返回合法 JSON
        return json.dumps({
            "explanation": "基于你的画像,我推荐这 4 个行动,因为它们与你家电和习惯最匹配。",
            "follow_up_questions": ["你家空调是定频还是变频?"],
            "confidence": 0.85,
        }, ensure_ascii=False)


# ============ Reasoner ============

class LLMReasoner:
    """LLM 推理层 — 调用 LLM + 反幻觉护栏"""

    def __init__(self, llm_client: Optional[LLMClient] = None) -> None:
        self.llm = llm_client or MockLLMClient()

    def _parse_json_response(self, raw: str) -> Dict[str, Any]:
        """从 LLM 输出提取 JSON(容错:可能带 Markdown 代码块)"""
        raw = raw.strip()
        # 去掉 markdown 代码块
        raw = re.sub(r"^```(?:json)?", "", raw, flags=re.MULTILINE).strip()
        raw = re.sub(r"```$", "", raw, flags=re.MULTILINE).strip()
        # 尝试直接解析
        try:
            return json.loads(raw)
        except Exception:
            pass
        # 尝试从文本中提取第一个 JSON 对象
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
        return {}

    def explain(self,
                profile_section: str,
                knowledge_section: str,
                schema_section: str,
                plan_dict: Dict[str, Any],
                user_message: str = "") -> LLMReasonerResult:
        """解释为什么方案匹配用户(防幻觉护栏)

        返回值:
            LLMReasonerResult
              - 如果 LLM 返回 JSON: explanation = parsed["explanation"]
              - 如果 LLM 返回纯文本: explanation = raw(整段话当 explanation)
              - 都不行: used_template_fallback = True
        """
        user_prompt = PROMPT_EXPLAIN.format(
            profile_section=profile_section,
            knowledge_section=knowledge_section,
            schema_section=schema_section,
            plan_json=json.dumps(plan_dict, ensure_ascii=False, indent=2),
            user_message=user_message or "(用户没说话)",
        )
        try:
            raw = self.llm.chat(SYSTEM_PROMPT, user_prompt)
            parsed = self._parse_json_response(raw)

            explanation_text = parsed.get("explanation", "").strip() if isinstance(parsed, dict) else ""

            # 真实 LLM 可能没严格返回 JSON,而是自然语言 — 兜底
            if not explanation_text and raw and raw.strip():
                explanation_text = raw.strip()

            # 反幻觉护栏(只对 explanation 文本做数字校验)
            ok = self._verify_explanation_text(explanation_text, plan_dict)
            if not ok:
                _log.warning("[llm_reasoner] explanation 含伪造数字,回退模板")
                return LLMReasonerResult(
                    explanation="(LLM 输出含伪造数字,已回退模板)",
                    used_template_fallback=True,
                    raw_llm_response=raw,
                )
            return LLMReasonerResult(
                explanation=explanation_text,
                follow_up_questions=list(parsed.get("follow_up_questions") or []) if isinstance(parsed, dict) else [],
                confidence=float(parsed.get("confidence", 0.0)) if isinstance(parsed, dict) else 0.0,
                raw_llm_response=raw,
            )
        except Exception as e:
            _log.exception("[llm_reasoner] explain 失败: %s", e)
            return LLMReasonerResult(used_template_fallback=True)

    def negotiate(self,
                  profile_section: str,
                  schema_section: str,
                  plan_dict: Dict[str, Any],
                  user_rejection: str) -> LLMReasonerResult:
        """用户拒绝某 action → 推荐替换"""
        user_prompt = PROMPT_NEGOTIATE.format(
            profile_section=profile_section,
            schema_section=schema_section,
            plan_json=json.dumps(plan_dict, ensure_ascii=False, indent=2),
            user_rejection=user_rejection,
        )
        try:
            raw = self.llm.chat(SYSTEM_PROMPT, user_prompt)
            parsed = self._parse_json_response(raw)
            result = LLMReasonerResult(raw_llm_response=raw)

            # 反幻觉:replacement_action_id 必须是 plan 中已存在的 id,不能是新编的
            replacement = parsed.get("replacement_action_id")
            existing_ids = {a["id"] for a in plan_dict.get("actions", [])}
            if replacement and replacement in existing_ids:
                result.replacement_action_id = replacement
            else:
                # replacement 是编造的 → 丢弃
                if replacement:
                    _log.warning("[llm_reasoner] replacement_action_id 不在 plan: %s", replacement)
                result.replacement_action_id = None
            result.replacement_rationale = parsed.get("replacement_rationale", "")
            result.negotiation_note = parsed.get("negotiation_note", "")
            result.confidence = float(parsed.get("confidence", 0.0))
            return result
        except Exception as e:
            _log.exception("[llm_reasoner] negotiate 失败: %s", e)
            return LLMReasonerResult(used_template_fallback=True)

    def ask_missing_info(self,
                         profile_section: str,
                         schema_section: str) -> LLMReasonerResult:
        """主动列出该问用户的 2-3 个问题"""
        user_prompt = PROMPT_ASK_INFO.format(
            profile_section=profile_section,
            schema_section=schema_section,
        )
        try:
            raw = self.llm.chat(SYSTEM_PROMPT, user_prompt)
            parsed = self._parse_json_response(raw)
            questions = list(parsed.get("questions") or [])
            # 限 1-5 个问题
            questions = questions[:5]
            return LLMReasonerResult(
                follow_up_questions=questions,
                confidence=float(parsed.get("confidence", 0.0)),
                raw_llm_response=raw,
            )
        except Exception as e:
            _log.exception("[llm_reasoner] ask_missing_info 失败: %s", e)
            return LLMReasonerResult(used_template_fallback=True)

    @staticmethod
    def _verify_explanation_text(text: str, plan_dict: Dict[str, Any]) -> bool:
        """检查 LLM 解释文本里是否编造了数字

        启发:plan 中的金额形式(如"约 ¥26/年")必须出现在 text 时才合法,
        或者 LLM 没说金额就通过。简单实现:任何包含"约 ¥X" 且 X 不在 plan 中 = 伪造。
        """
        # 提取 plan 中所有金额数字
        real_amounts = set()
        for a in plan_dict.get("actions", []):
            cny = a.get("estimated_saving_cny")
            if cny is not None and cny > 0:
                real_amounts.add(int(cny) if cny == int(cny) else cny)
        # 提取 text 中"约 ¥X"模式
        for m in re.finditer(r"约\s*[¥￥]?\s*(\d+(?:\.\d+)?)", text):
            n = float(m.group(1))
            if n not in real_amounts and n > 0:
                _log.warning("[llm_reasoner] explanation 含未在 plan 中的数字: %s", n)
                return False
        return True


# ============ 便捷函数 ============

def make_reasoner(llm_client: Optional[LLMClient] = None) -> LLMReasoner:
    """工厂函数"""
    return LLMReasoner(llm_client=llm_client)


__all__ = [
    "LLMReasoner",
    "LLMReasonerResult",
    "LLMClient",
    "MockLLMClient",
    "AntiHallucinationGuard",
    "make_reasoner",
    "PROMPT_EXPLAIN",
    "PROMPT_NEGOTIATE",
    "PROMPT_ASK_INFO",
    "SYSTEM_PROMPT",
]