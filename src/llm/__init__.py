"""
LLM 模块 - 提供大语言模型调用能力
支持 OpenAI API 和本地模型
"""

from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

# P5-F: 模块级 logger
try:
    from observability import get_logger

    _logger = get_logger("llm")
except Exception:
    import logging

    _logger = logging.getLogger("llm")


@dataclass
class LLMResponse:
    """LLM响应 (P5-A 统一契约)
    - content: 文本内容
    - model: 实际使用的模型
    - usage: token 用量 {prompt_tokens, completion_tokens, total_tokens}
    - finish_reason: 完成原因 (stop/length/error/tool_calls)
    - latency_ms: 调用耗时(P5-A 新增,P5-B trace_id 联动)
    - request_id: 链路追踪 ID(P5-A 新增,P5-B 自动注入)
    - error: 错误信息(成功时为空,P5-C 错误处理使用)
    - tool_calls: P6.S.17 tool-use 字段,LLM 返的工具调用列表
      每个元素: {"id": str, "name": str, "arguments": str (JSON)}
    """

    content: str
    model: str
    usage: Dict[str, int]
    finish_reason: str
    latency_ms: Optional[float] = None
    request_id: Optional[str] = None
    error: Optional[str] = None
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    reasoning: Optional[str] = None  # DeepSeek R1/reasoner 的链式推理内容(reasoning_content)


# LLMResponse 定义在本文件顶部(先于 import client):client.py 顶部
# `from llm import LLMResponse` 依赖它;其余符号统一 re-export 自 llm.client
# (唯一实现),保证 `from llm import X` 与 `from llm.client import X` 一致。
# 循环导入安全:Python 先执行本文件 → 定义 LLMResponse → import client →
# client import llm 时 LLMResponse 已存在。
from llm.client import (  # noqa: E402
    LLMClient,
    OpenAIClient,
    MockLLMClient,
    ZhipuClient,
    BaiduClient,
    AliClient,
    MiniMaxClient,
    DeepSeekClient,
    BayesianLLMClient,
    BayesianModelRouter,
    ModelStats,
    BetaDistribution,
    create_llm_client,
    get_llm_client,
    reset_llm_client,
    build_chat_prompt,
    SYSTEM_PROMPT,
    # mock 开关:client.py 中为私有名(_is_mock_mode_env 等),此处重导出为公开名
    _is_mock_mode_env as is_mock_mode,
    _should_use_mock as should_use_mock,
    _log_mock_decision as log_mock_decision,
)

# 兼容层:遗留模块(llm/response_generator.py 及部分测试)仍 import 以下旧符号。
# 生产主链路(client.py 的 build_chat_prompt)不使用它们;保留旧签名避免破坏消费者。
SYSTEM_PROMPT_TEMPLATE = """你是一个专业的绿色低碳智能助手，名为"绿宝"。

你的职责：
1. 帮助用户了解碳中和、节能减排等环保知识
2. 根据用户情况提供个性化的低碳生活建议
3. 引导用户采取实际行动，减少碳排放
4. 回答关于环保政策、绿色产品等问题

用户信息：
- 环保认知水平：{knowledge_level}
- 行为阶段：{behavior_stage}
- 关注领域：{interests}
- 沟通风格：{communication_style}

本轮建议策略（P4-D 行为阶段驱动）：
- 焦点：{focus}
- 建议强度：{suggestion_intensity}
- 行动复杂度：{action_complexity}
- 语气：{tone}
- 示例侧重：{example_focus}

回复要求：
1. 使用友好、鼓励的语气
2. 根据用户认知水平调整解释深度
3. 每条建议尽量具体可执行
4. 可以适当引用数据和事实"""


def build_system_prompt(personalization_ctx: Dict[str, Any]) -> str:
    """构建系统提示词(P4-D 扩展:把行为阶段策略注入 prompt)"""
    knowledge_level = personalization_ctx.get("knowledge_level_chinese", "了解")
    behavior_stage = personalization_ctx.get("behavior_stage", "意向")
    interests = personalization_ctx.get(
        "confirmed_interests", personalization_ctx.get("primary_interests", [])
    )
    if isinstance(interests, list):
        interests = "、".join(interests[:3]) if interests else "绿色生活"
    communication_style = personalization_ctx.get("communication_style", "平衡")

    # P4-D: 行为阶段驱动的策略变量
    focus = personalization_ctx.get("focus", "意识唤醒")
    suggestion_intensity = personalization_ctx.get("suggestion_intensity", "low")
    action_complexity = personalization_ctx.get("action_complexity", "simple")
    tone = personalization_ctx.get("tone", "positive")
    example_focus = personalization_ctx.get("example_focus", "similar_people")

    return SYSTEM_PROMPT_TEMPLATE.format(
        knowledge_level=knowledge_level,
        behavior_stage=behavior_stage,
        interests=interests,
        communication_style=communication_style,
        focus=focus,
        suggestion_intensity=suggestion_intensity,
        action_complexity=action_complexity,
        tone=tone,
        example_focus=example_focus,
    )


def build_conversation_prompt(
    user_message: str,
    rag_context: str = "",
    conversation_history: List[Dict] = None,
    personalization_ctx: Dict[str, Any] = None,
) -> List[Dict[str, str]]:
    """构建对话消息列表(遗留模块兼容实现)"""
    messages = []

    # 系统提示词
    if personalization_ctx:
        system_prompt = build_system_prompt(personalization_ctx)
    else:
        system_prompt = (
            "你是一个专业的绿色低碳智能助手，帮助用户了解环保知识、提供低碳生活建议。"
        )

    messages.append({"role": "system", "content": system_prompt})

    # 对话历史
    if conversation_history:
        for msg in conversation_history[-6:]:  # 最近3轮对话
            role = "assistant" if msg.get("role") == "assistant" else "user"
            messages.append({"role": role, "content": msg.get("content", "")})

    # RAG 上下文
    if rag_context:
        context_msg = f"""[参考知识]
{rag_context}

[问题]
{user_message}"""
        messages.append({"role": "user", "content": context_msg})
    else:
        messages.append({"role": "user", "content": user_message})

    return messages


__all__ = [
    "LLMResponse",
    "LLMClient",
    "OpenAIClient",
    "MockLLMClient",
    "ZhipuClient",
    "BaiduClient",
    "AliClient",
    "MiniMaxClient",
    "DeepSeekClient",
    "BayesianLLMClient",
    "BayesianModelRouter",
    "ModelStats",
    "BetaDistribution",
    "create_llm_client",
    "get_llm_client",
    "reset_llm_client",
    "build_chat_prompt",
    "SYSTEM_PROMPT",
    "is_mock_mode",
    "should_use_mock",
    "log_mock_decision",
    "SYSTEM_PROMPT_TEMPLATE",
    "build_system_prompt",
    "build_conversation_prompt",
]
