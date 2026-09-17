"""
Reflection 闭环(P16)

执行后用 LLM 对最终答案做质量门控(自评),失败/不完整时给修订方向并触发一次修订。

与 ReAct 浅层反思(下一步调什么工具)的区别:这里是对"最终答案"做质量门控——
尤其抓"工具失败却仍给出具体数字"的幻觉。三个 verdict:
  - complete   : 完整、有据、未虚构,可直接返回
  - incomplete : 缺关键信息(如工具失败/返回空/缺对比项)
  - wrong      : 有错误或编造(如工具失败却给了确定数值)

纯逻辑 + 依赖 LLM 客户端抽象 chat(system, user) -> str,可 mock 单测。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

_log = logging.getLogger(__name__)

_REFLECT_SYSTEM = "你是质量审查员。"
_REFLECT_PROMPT = """给定「用户问题」「工具调用结果」「草稿回答」,判断草稿是否可直接返回给用户。

判据:
- complete  : 完整回答了问题,数字/事实有工具结果支撑,未编造。
- incomplete: 缺少关键信息(例如工具失败、返回空、缺了用户要的对比项)。
- wrong     : 存在编造或与工具结果矛盾(例如工具失败却仍给出具体数字)。

只输出 JSON(不要 Markdown 代码块):
{{
  "verdict": "complete | incomplete | wrong",
  "critique": "一句话自评(中文)",
  "revision_hint": "若需修订,给出具体方向;否则空字符串"
}}

[用户问题]
{question}

[工具调用结果]
{tool_summary}

[草稿回答]
{draft}
"""


def _parse_json(raw: str) -> Dict[str, Any]:
    raw = (raw or "").strip()
    raw = re.sub(r"^```(?:json)?", "", raw, flags=re.MULTILINE).strip()
    raw = re.sub(r"```$", "", raw, flags=re.MULTILINE).strip()
    try:
        return json.loads(raw)
    except Exception:
        pass
    m = re.search(r"\{[\s\S]*\}", raw)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return {}


@dataclass
class ReflectionResult:
    verdict: str = "complete"  # complete | incomplete | wrong
    critique: str = ""
    revision_hint: str = ""
    raw: str = ""

    @property
    def needs_revision(self) -> bool:
        return self.verdict in ("incomplete", "wrong")


class Reflector:
    """最终答案质量门控器"""

    def __init__(self, llm_client=None):
        self.llm = llm_client

    def reflect(
        self,
        question: str,
        draft: str,
        tool_calls: List[Dict[str, Any]],
    ) -> ReflectionResult:
        if not self.llm:
            return ReflectionResult()
        # 无工具调用 → 纯知识/闲聊,无需反思
        if not tool_calls:
            return ReflectionResult()
        tool_summary = self._summarize_tools(tool_calls)
        prompt = _REFLECT_PROMPT.format(
            question=question,
            tool_summary=tool_summary,
            draft=(draft or "")[:2000],
        )
        # 统一用 chat(messages) 接口(与真实 llm.client / run_react_loop 一致)
        msgs = [
            {"role": "system", "content": _REFLECT_SYSTEM},
            {"role": "user", "content": prompt},
        ]
        try:
            raw = self.llm.chat(msgs)
        except Exception as e:
            _log.warning("[reflector] 反思调用失败: %s", e)
            return ReflectionResult()
        # 兼容两种返回:纯字符串或带 .content 的对象(LLMResponse)
        if not isinstance(raw, str):
            raw = getattr(raw, "content", "") or ""
        parsed = _parse_json(raw)
        verdict = parsed.get("verdict", "complete")
        if verdict not in ("complete", "incomplete", "wrong"):
            verdict = "complete"
        return ReflectionResult(
            verdict=verdict,
            critique=parsed.get("critique", ""),
            revision_hint=parsed.get("revision_hint", ""),
            raw=raw,
        )

    @staticmethod
    def _summarize_tools(tool_calls: List[Dict[str, Any]]) -> str:
        lines: List[str] = []
        for tc in tool_calls:
            name = tc.get("name", "?")
            ok = tc.get("success", False)
            output = tc.get("output")
            out_str = ""
            if output is not None:
                out_str = json.dumps(output, ensure_ascii=False, default=str)[:500]
            lines.append(f"- {name} (success={ok}): {out_str}")
        return "\n".join(lines) if lines else "(无工具调用)"


def reflect_and_revise(
    llm_client,
    question: str,
    draft: str,
    tool_calls: List[Dict[str, Any]],
    messages: Optional[List[Dict[str, Any]]] = None,
    trace_id: Optional[str] = None,
) -> tuple:
    """反思 + 一次修订。返回 (final_draft, verdict, revised: bool)。

    verdict 为 incomplete/wrong 且能修订时,把 critique 注入 messages 再调一次 LLM;
    修订失败则回退原草稿(不阻塞主路径)。
    """
    reflector = Reflector(llm_client)
    result = reflector.reflect(question, draft, tool_calls)
    if not result.needs_revision:
        return draft, result.verdict, False

    # 触发一次修订
    if messages is None:
        return draft, result.verdict, False
    try:
        revise_msg = {
            "role": "user",
            "content": (
                f"[自评] 你上一轮的答案存在不足:{result.critique} "
                f"修订方向:{result.revision_hint or '请补充缺失信息或纠正错误'}。"
                "请直接给出修订后的答案。"
            ),
        }
        messages.append(revise_msg)
        resp = llm_client.chat(messages, trace_id=trace_id)
        if resp and getattr(resp, "content", ""):
            return resp.content, result.verdict, True
    except Exception as e:
        _log.warning("[reflector] 修订调用失败: %s", e)
    return draft, result.verdict, False


__all__ = ["Reflector", "ReflectionResult", "reflect_and_revise"]
