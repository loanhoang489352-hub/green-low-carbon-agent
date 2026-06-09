"""
LangGraph 驱动的智能体
提供与原有 GreenAgent 接口兼容的 LangGraph 版本
"""

import uuid
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime

script_path = Path(__file__).resolve()
project_root = script_path.parent.parent.parent
sys.path.insert(0, str(project_root / 'src'))

from agent.graph import (
    AgentState,
    initial_state,
    get_agent_graph,
    get_react_graph
)
from agent.conversation_store import get_conversation_store, ConversationContext
from user_profile.user_profile import UserProfileManager
from user_profile.dynamic_updater import get_profile_updater
from memory.short_term import ShortTermMemory, get_short_term_memory
from memory.long_term import LongTermMemory


@dataclass
class LangGraphResponse:
    """LangGraph 智能体响应"""
    message: str
    conversation_id: str
    intent: str
    suggestions: List[str] = field(default_factory=list)
    knowledge_refs: List[str] = field(default_factory=list)
    memory_hints: List[str] = field(default_factory=list)
    profile_updates: Dict = field(default_factory=dict)
    timestamp: str = ""
    personalization_info: Dict = field(default_factory=dict)
    recommendations: List[Dict] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message": self.message,
            "conversation_id": self.conversation_id,
            "intent": self.intent,
            "suggestions": self.suggestions,
            "knowledge_refs": self.knowledge_refs,
            "memory_hints": self.memory_hints,
            "profile_updates": self.profile_updates,
            "timestamp": self.timestamp,
            "personalization_info": self.personalization_info,
            "recommendations": self.recommendations,
            "metadata": self.metadata
        }


class LangGraphAgent:
    """
    基于 LangGraph 的绿色低碳智能体

    提供与 GreenAgent 类似的接口，但内部使用 StateGraph 工作流
    """

    def __init__(
        self,
        knowledge_base_path: str = None,
        use_vector_db: bool = False,
        enable_rag: bool = True,
        use_llm: bool = False,
        use_react: bool = False
    ):
        self.use_llm = use_llm
        self.use_react = use_react

        if knowledge_base_path is None:
            knowledge_base_path = str(project_root / "knowledge_base")
        self.knowledge_base_path = knowledge_base_path

        self.short_term_memory = get_short_term_memory()
        self.long_term_memory = LongTermMemory()
        self.profile_manager = UserProfileManager()
        self.dynamic_updater = get_profile_updater()
        self.conversation_store = get_conversation_store()

        self._init_graph()

        print(f"LangGraph 智能体初始化完成")
        print(f"   - 工作流模式: {'ReAct' if use_react else 'StateGraph'}")
        print(f"   - 知识库: {knowledge_base_path}")
        print(f"   - RAG: {'已启用' if enable_rag else '未启用'}")

    def _init_graph(self):
        """初始化工作流图"""
        if self.use_react:
            self.graph = get_react_graph()
        else:
            self.graph = get_agent_graph()

    def chat(
        self,
        user_id: str,
        message: str,
        conversation_id: str = None
    ) -> LangGraphResponse:
        """
        处理用户对话

        Args:
            user_id: 用户ID
            message: 用户消息
            conversation_id: 对话ID

        Returns:
            LangGraphResponse: 智能体响应
        """
        if not conversation_id:
            conversation_id = self._get_or_create_conversation(user_id)

        state = initial_state(user_id, conversation_id, message)

        try:
            config = {"configurable": {"thread_id": conversation_id}}
            result = self.graph.invoke(state, config=config)

            return self._build_response(result, conversation_id)
        except Exception as e:
            print(f"LangGraph 执行错误: {e}")
            import traceback
            traceback.print_exc()
            return LangGraphResponse(
                message=f"抱歉，处理您的请求时出现错误: {str(e)}",
                conversation_id=conversation_id,
                intent="error",
                timestamp=datetime.now().isoformat(),
                metadata={"error": str(e)}
            )

    def chat_stream(
        self,
        user_id: str,
        message: str,
        conversation_id: str = None
    ):
        """
        流式处理用户对话

        Args:
            user_id: 用户ID
            message: 用户消息
            conversation_id: 对话ID

        Yields:
            dict: 逐步输出状态
        """
        if not conversation_id:
            conversation_id = self._get_or_create_conversation(user_id)

        state = initial_state(user_id, conversation_id, message)

        for event in self.graph.stream(state):
            yield event

    def _build_response(
        self,
        result: AgentState,
        conversation_id: str
    ) -> LangGraphResponse:
        """构建响应对象"""
        return LangGraphResponse(
            message=result.get("response_message", ""),
            conversation_id=conversation_id,
            intent=result.get("intent", ""),
            suggestions=result.get("suggestions", []),
            knowledge_refs=result.get("knowledge_refs", []),
            memory_hints=result.get("memory_hints", []),
            profile_updates=result.get("profile_updates", {}),
            timestamp=datetime.now().isoformat(),
            personalization_info=result.get("personalization_info", {}),
            recommendations=result.get("recommendations", []),
            metadata=result.get("metadata", {})
        )

    def _get_or_create_conversation(self, user_id: str) -> str:
        """获取或创建对话ID(委托给 ConversationStore 单例)"""
        ctx = self.conversation_store.get_or_create(user_id)
        return ctx.conversation_id

    def start_conversation(self, user_id: str) -> str:
        """开始新对话

        P4-B.5:显式分配新 conversation_id,与 get_or_create 的"复用最近"
        行为区分,用于 onboarding 后切分新会话等场景。
        """
        conv_id = str(uuid.uuid4())
        self.conversation_store._new_conversation(user_id)  # type: ignore[attr-defined]
        return conv_id

    def get_conversation_history(
        self,
        user_id: str,
        conversation_id: str = None,
        limit: int = 10
    ) -> List[Dict]:
        """获取对话历史"""
        if conversation_id:
            return self.short_term_memory.get_conversation_history(
                conversation_id, limit
            )

        contexts = self.conversation_store.list_user_conversations(user_id)
        if contexts:
            all_history = []
            for ctx in contexts:
                all_history.extend(
                    self.short_term_memory.get_conversation_history(
                        ctx.conversation_id, limit
                    )
                )
            return all_history[-limit:]
        return []

    def get_user_profile(self, user_id: str) -> Dict[str, Any]:
        """获取用户画像"""
        return self.profile_manager.get_profile(user_id) or {}

    def update_user_profile(self, user_id: str, updates: Dict) -> bool:
        """更新用户画像"""
        return self.profile_manager.update_profile(user_id, updates)

    def reset_conversation(self, user_id: str, conversation_id: str = None):
        """重置对话"""
        if conversation_id:
            self.conversation_store.remove(conversation_id)
            return
        for ctx in self.conversation_store.list_user_conversations(user_id):
            self.conversation_store.remove(ctx.conversation_id)

    def get_stats(self, user_id: str) -> Dict[str, Any]:
        """获取统计信息"""
        contexts = self.conversation_store.list_user_conversations(user_id)
        total_messages = 0
        for ctx in contexts:
            history = self.short_term_memory.get_conversation_history(
                ctx.conversation_id, 1000
            )
            total_messages += len(history)

        latest = self.conversation_store.get_latest(user_id)
        return {
            "total_conversations": len(contexts),
            "total_messages": total_messages,
            "active_conversation": latest.conversation_id if latest else None
        }
