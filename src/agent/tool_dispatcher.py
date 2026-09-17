"""
P6.S.17: Tool Dispatcher + ReAct 循环

让 LLM 真正能用 OpenAI function calling 协议自主选 tool。

核心:
1. 构造 OpenAI 格式的 tools list
2. 调 LLM(传 tools=)
3. 若 LLM 返 tool_calls:dispatch 到 ToolRegistry
4. 把 tool 结果加到 messages,再调 LLM
5. 重复 2-4 直到 LLM 返 stop 或达 max_steps

这是真正"agent"的核心循环,替代 core.py 里 200+ 行硬编码 if-else。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from llm.client import registry_tools_to_openai_format

_logger = logging.getLogger(__name__)


def dispatch_tool_call(
    name: str, arguments_json: str, ctx: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    P6.S.17: 执行一个 tool_call,返标准化结果

    Args:
        ctx: 调用上下文(如 {"user_id":..., "city":...}),注入到工具 kwargs。
             LLM 显式传的参数优先,ctx 只填充缺失项(如出行工具的城市)。

    Returns:
        {"success": bool, "output": Any, "error": str?}
    """
    # P6.S.20: 记录 tool 调用到 metrics
    try:
        from observability.metrics import get_metrics_collector

        get_metrics_collector().record_tool_call(name)
    except Exception:
        pass
    try:
        from agent.tools import get_registry

        reg = get_registry()
    except Exception as e:
        return {"success": False, "error": f"registry unavailable: {e}"}

    inst = reg.get(name)
    if not inst:
        return {"success": False, "error": f"tool not found: {name}"}

    # P16: 工具级权限门(high 风险工具需用户确认;默认 low → 放行,不改变现状)
    try:
        from agent.tool_permission import check_tool_permission

        perm_err = check_tool_permission(inst, ctx)
        if perm_err:
            return {"success": False, "error": perm_err, "code": "NEEDS_CONFIRMATION"}
    except Exception:
        pass

    # 解析 arguments
    if arguments_json:
        try:
            kwargs = (
                json.loads(arguments_json) if isinstance(arguments_json, str) else arguments_json
            )
        except Exception as e:
            return {"success": False, "error": f"invalid arguments JSON: {e}"}
    else:
        kwargs = {}

    # 注入调用上下文(如 user_id/city):LLM 显式传的参数优先,ctx 只填充缺失项
    if ctx:
        for k, v in ctx.items():
            kwargs.setdefault(k, v)

    # 执行
    try:
        result = inst.execute(**kwargs)
        if result.success:
            # result.data 可能是 dict / str
            data = result.data
            if isinstance(data, dict):
                output = data.get("text") or data
            else:
                output = data
            return {"success": True, "output": output, "execution_time": result.execution_time}
        return {"success": False, "error": result.error or "tool returned failure"}
    except Exception as e:
        return {"success": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}


def _last_user_message(messages: List[Dict[str, Any]]) -> str:
    """提取最后一条 user 消息(当前问题),供反思用"""
    for m in reversed(messages):
        if isinstance(m, dict) and m.get("role") == "user":
            return str(m.get("content", "") or "")
    return ""


def run_react_loop(
    messages: List[Dict[str, Any]],
    llm_client,
    tool_names: Optional[List[str]] = None,
    max_steps: int = 3,
    tool_choice: str = "auto",
    trace_id: Optional[str] = None,
    ctx: Optional[Dict[str, Any]] = None,
    reflect: bool = False,
) -> Dict[str, Any]:
    """
    P6.S.17: 简单的 ReAct 循环
    - messages 初始含 system + user history
    - llm_client 必须有 .chat(messages, **kwargs) 接口
    - 每步: 调 LLM,若 finish_reason=="tool_calls" 则 dispatch,然后 messages+=tool_result 再调
    - reflect=True(P16): 出最终答案后做一次质量门控,失败/不完整则修订一次

    Returns:
        {
            "content": str,           # 最终 LLM 输出(可能经反思修订)
            "messages": List[dict],   # 完整对话历史(可调试)
            "steps": int,             # 实际循环步数
            "tool_calls": List[dict], # 调过哪些 tool
            "success": bool,
            "reflection": dict?,      # P16: {verdict, revised}
        }
    """
    tools = registry_tools_to_openai_format(tool_names)
    if not tools:
        # 没 tool 可用,直接单步 chat
        resp = llm_client.chat(messages, trace_id=trace_id)
        _raz = getattr(resp, "reasoning", "") or ""
        return {
            "content": resp.content or "",
            "messages": messages,
            "steps": 1,
            "tool_calls": [],
            "reasonings": [_raz] if _raz else [],
            "success": not bool(resp.error),
        }

    tool_calls_log: List[Dict[str, Any]] = []
    reasonings: List[str] = []  # DeepSeek R1 链式推理(供"思考过程"透明展示)
    for step in range(1, max_steps + 1):
        try:
            resp = llm_client.chat(
                messages,
                tools=tools,
                tool_choice=tool_choice,
                trace_id=trace_id,
            )
        except Exception as e:
            return {
                "content": f"[LLM 调用失败: {e}]",
                "messages": messages,
                "steps": step,
                "tool_calls": tool_calls_log,
                "reasonings": reasonings,
                "success": False,
            }

        # 收集推理内容
        _raz = getattr(resp, "reasoning", "") or ""
        if _raz:
            reasonings.append(_raz)

        if not resp.tool_calls:
            # LLM 觉得够用了,返 stop
            content = resp.content or ""
            reflection = None
            if reflect and tool_calls_log:
                try:
                    from agent.reflector import reflect_and_revise

                    question = _last_user_message(messages)
                    content, verdict, revised = reflect_and_revise(
                        llm_client, question, content, tool_calls_log, messages, trace_id
                    )
                    reflection = {"verdict": verdict, "revised": revised}
                except Exception as e:
                    _logger.warning("[P16] reflection 失败(非致命): %s", e)
            return {
                "content": content,
                "messages": messages,
                "steps": step,
                "tool_calls": tool_calls_log,
                "reasonings": reasonings,
                "success": True,
                "reflection": reflection,
            }

        # LLM 决定调 tool,执行每个 tool_call
        # OpenAI 要求把 assistant message(含 tool_calls)push 回 messages
        # 然后 tool 结果以 role="tool" push
        from llm.client import _parse_openai_tool_calls  # noqa

        # 构造 assistant message
        messages.append(
            {
                "role": "assistant",
                "content": resp.content or "",
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": tc["arguments"],
                        },
                    }
                    for tc in resp.tool_calls
                ],
            }
        )
        for tc in resp.tool_calls:
            t0 = time.time()
            result = dispatch_tool_call(tc["name"], tc["arguments"], ctx=ctx)
            elapsed_ms = round((time.time() - t0) * 1000, 2)
            tool_calls_log.append(
                {
                    "name": tc["name"],
                    "arguments": tc["arguments"],
                    "success": result["success"],
                    "elapsed_ms": elapsed_ms,
                    # 中间结果:工具输出(供实时 trace 展示"调了工具拿到什么")
                    "output": (
                        result.get("output")
                        if result["success"]
                        else {"error": result.get("error")}
                    ),
                }
            )
            # tool 结果以 role="tool" push,带 tool_call_id
            tool_result_text = json.dumps(
                result.get("output") if result["success"] else {"error": result.get("error")},
                ensure_ascii=False,
                default=str,
            )[:4000]  # 防超长
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": tool_result_text,
                }
            )
            _logger.info(
                "[P6.S.17.ReAct] step=%d tool=%s ok=%s ms=%.1f",
                step,
                tc["name"],
                result["success"],
                elapsed_ms,
            )

    # max_steps 用完,强制收尾
    _logger.warning("[P6.S.17.ReAct] 达 max_steps=%d, 强制收尾", max_steps)
    try:
        resp = llm_client.chat(messages, trace_id=trace_id)
        _raz = getattr(resp, "reasoning", "") or ""
        return {
            "content": resp.content or "",
            "messages": messages,
            "steps": max_steps,
            "tool_calls": tool_calls_log,
            "reasonings": reasonings + ([_raz] if _raz else []),
            "success": True,
        }
    except Exception as e:
        return {
            "content": f"[ReAct 循环结束但 LLM 失败: {e}]",
            "messages": messages,
            "steps": max_steps,
            "tool_calls": tool_calls_log,
            "reasonings": reasonings,
            "success": False,
        }
