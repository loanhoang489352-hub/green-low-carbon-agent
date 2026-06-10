"""
LLM 响应生成器
使用大语言模型生成智能响应
"""

import sys
from pathlib import Path
from typing import Dict, Any, List, Optional

# P5-F: 模块级 logger
try:
    from observability import get_logger
    _logger = get_logger("llm.response_generator")
except Exception:
    import logging
    _logger = logging.getLogger("llm.response_generator")

script_path = Path(__file__).resolve()
project_root = script_path.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from . import (
    LLMClient,
    OpenAIClient,
    MockLLMClient,
    create_llm_client,
    build_system_prompt,
    build_conversation_prompt,
    get_llm_client,
    set_llm_client,
    SYSTEM_PROMPT_TEMPLATE
)


class LLMResponseGenerator:
    """基于 LLM 的响应生成器"""
    
    def __init__(
        self,
        client: LLMClient = None,
        enable_rag: bool = True,
        enable_personalization: bool = True
    ):
        """
        初始化 LLM 响应生成器
        
        Args:
            client: LLM 客户端，不提供则使用全局客户端
            enable_rag: 是否启用 RAG
            enable_personalization: 是否启用个性化
        """
        if client is None:
            client = get_llm_client()
        self.client = client
        self.enable_rag = enable_rag
        self.enable_personalization = enable_personalization
    
    def generate(
        self,
        user_message: str,
        rag_context: str = "",
        conversation_history: List[Dict] = None,
        personalization_ctx: Dict[str, Any] = None,
        intent_type: str = None
    ) -> str:
        """
        生成响应
        
        Args:
            user_message: 用户消息
            rag_context: RAG 检索到的上下文
            conversation_history: 对话历史
            personalization_ctx: 个性化上下文
            intent_type: 意图类型
        
        Returns:
            生成的响应文本
        """
        # 构建消息列表
        messages = build_conversation_prompt(
            user_message=user_message,
            rag_context=rag_context if self.enable_rag else "",
            conversation_history=conversation_history,
            personalization_ctx=personalization_ctx if self.enable_personalization else None
        )
        
        # 发送请求
        response = self.client.chat(messages)
        
        return response.content
    
    def generate_with_fallback(
        self,
        user_message: str,
        fallback_response: str,
        rag_context: str = "",
        conversation_history: List[Dict] = None,
        personalization_ctx: Dict[str, Any] = None
    ) -> str:
        """
        生成响应，如果 LLM 不可用则使用降级响应
        
        Args:
            user_message: 用户消息
            fallback_response: 降级响应
            rag_context: RAG 上下文
            conversation_history: 对话历史
            personalization_ctx: 个性化上下文
        
        Returns:
            生成的响应文本
        """
        try:
            return self.generate(
                user_message=user_message,
                rag_context=rag_context,
                conversation_history=conversation_history,
                personalization_ctx=personalization_ctx
            )
        except Exception as e:
            _logger.warning(f"LLM 生成失败,使用降级响应: {e}")
            return fallback_response


class HybridResponseGenerator:
    """混合响应生成器 - 结合规则和 LLM"""
    
    def __init__(
        self,
        rule_based_generator=None,
        llm_generator: LLMResponseGenerator = None
    ):
        """
        初始化混合响应生成器
        
        Args:
            rule_based_generator: 规则基础的生成器
            llm_generator: LLM 生成器
        """
        self.rule_generator = rule_based_generator
        self.llm_generator = llm_generator or LLMResponseGenerator()
    
    def generate(
        self,
        user_message: str,
        context: Any = None,
        rag_context: str = "",
        personalization_ctx: Dict[str, Any] = None,
        use_llm: bool = False
    ) -> Dict[str, Any]:
        """
        生成响应
        
        Args:
            user_message: 用户消息
            context: 上下文
            rag_context: RAG 上下文
            personalization_ctx: 个性化上下文
            use_llm: 是否强制使用 LLM
        
        Returns:
            包含 message, suggestions, knowledge_refs 等字段的字典
        """
        if use_llm and self.llm_generator:
            # 使用 LLM 生成
            message = self.llm_generator.generate(
                user_message=user_message,
                rag_context=rag_context,
                conversation_history=context.conversation_history if context else None,
                personalization_ctx=personalization_ctx
            )
            
            return {
                "message": message,
                "suggestions": self._get_suggestions(personalization_ctx),
                "knowledge_refs": [],
                "response_type": "llm"
            }
        elif self.rule_generator:
            # 使用规则生成
            rule_response = self.rule_generator.generate_response(user_message, context)
            
            if use_llm:
                # 尝试增强
                try:
                    llm_message = self.llm_generator.generate(
                        user_message=user_message,
                        rag_context=rag_context,
                        personalization_ctx=personalization_ctx
                    )
                    # 合并响应
                    message = self._merge_responses(rule_response["message"], llm_message)
                except Exception:
                    message = rule_response["message"]
            else:
                message = rule_response["message"]
            
            return {
                "message": message,
                "suggestions": rule_response.get("suggestions", []),
                "knowledge_refs": rule_response.get("knowledge_refs", []),
                "response_type": "hybrid" if use_llm else "rule"
            }
        else:
            # 仅使用 LLM
            message = self.llm_generator.generate(
                user_message=user_message,
                rag_context=rag_context,
                personalization_ctx=personalization_ctx
            )
            
            return {
                "message": message,
                "suggestions": self._get_suggestions(personalization_ctx),
                "knowledge_refs": [],
                "response_type": "llm"
            }
    
    def _get_suggestions(self, personalization_ctx: Dict[str, Any] = None) -> List[str]:
        """获取建议(P4-D:基于 stage strategy 推荐下一步)"""
        suggestions = [
            "给我更多低碳生活建议",
            "推荐一些环保行动",
            "有什么节能产品推荐？",
        ]

        if personalization_ctx:
            behavior_stage = personalization_ctx.get("behavior_stage", "意向")
            intensity = personalization_ctx.get("suggestion_intensity", "low")
            focus = personalization_ctx.get("focus", "意识唤醒")

            # 5 阶段差异化建议(P4-D)
            stage_specific = {
                "无意向": [
                    "低碳生活真的有用吗?",
                    "先了解下环保的真正意义",
                ],
                "意向": [
                    "推荐一些简单的起步行动",
                    "看看和我类似的人是怎么开始的",
                ],
                "准备": [
                    "我准备好了,告诉我具体怎么做",
                    "给我一个一周行动计划",
                ],
                "行动": [
                    "分享你的减碳成果",
                    "帮我看看现在做的怎么样",
                ],
                "维持": [
                    "还有什么进阶的低碳玩法?",
                    "如何影响身边更多人加入",
                ],
            }
            stage_picks = stage_specific.get(behavior_stage, [])
            suggestions.extend(stage_picks)

            # intensity 决定返回数量(very_low=3, low=3, medium=4, high=5)
            n = {
                "very_low": 3,
                "low": 3,
                "medium": 4,
                "high": 5,
            }.get(intensity, 3)
            suggestions = suggestions[:n]
        else:
            suggestions = suggestions[:3]

        return suggestions
    
    def _merge_responses(self, rule_response: str, llm_response: str) -> str:
        """合并规则响应和 LLM 响应"""
        # 如果 LLM 响应有明显改进，优先使用 LLM
        if "Mock" not in llm_response and len(llm_response) > len(rule_response):
            return llm_response
        
        # 否则结合两者
        return f"{rule_response}\n\n---\n💬 AI 补充：\n{llm_response}"


def create_hybrid_generator(rule_generator=None) -> HybridResponseGenerator:
    """创建混合生成器"""
    return HybridResponseGenerator(rule_based_generator=rule_generator)


# 测试代码
if __name__ == "__main__":
    print("=" * 50)
    print("测试 LLM 响应生成器")
    print("=" * 50)
    
    # 测试 LLM 客户端
    client = create_llm_client("openai")
    
    # 测试生成
    generator = LLMResponseGenerator(client=client)
    
    test_message = "什么是碳中和？"
    personalization = {
        "knowledge_level_chinese": "了解",
        "behavior_stage": "意向",
        "primary_interests": ["低碳出行"],
        "communication_style": "平衡"
    }
    
    print(f"\n用户消息: {test_message}")
    print(f"个性化信息: {personalization}")
    print("\n生成响应...")
    
    response = generator.generate(
        user_message=test_message,
        personalization_ctx=personalization
    )
    
    print(f"\nAI 响应:\n{response}")
    print("\n" + "=" * 50)
