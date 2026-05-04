"""
LangGraph 节点定义
定义智能体工作流中的各个处理节点
"""

import sys
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime

script_path = Path(__file__).resolve()
project_root = script_path.parent.parent.parent
sys.path.insert(0, str(project_root / 'src'))

from .state import AgentState, IntentType


class AgentNodes:
    """节点工具类，包含所有节点函数"""

    def __init__(self):
        self._intent_recognizer = None
        self._rag_engine = None
        self._profile_manager = None
        self._response_generator = None
        self._recommendation_engine = None
        self._dynamic_updater = None
        self._initialized = False

    def initialize(self):
        """延迟初始化依赖模块"""
        if self._initialized:
            return

        from agent.intent import IntentRecognizer, IntentType as OldIntentType
        from rag.rag_engine import RAGEngine, RAGConfig
        from user_profile.user_profile import UserProfileManager
        from user_profile.dynamic_updater import get_profile_updater
        from user_profile.personalized_recommender import PersonalizedRecommendationEngine
        from agent.response import ResponseGenerator

        self._intent_recognizer = IntentRecognizer()
        self._profile_manager = UserProfileManager()
        self._dynamic_updater = get_profile_updater()
        self._recommendation_engine = PersonalizedRecommendationEngine()
        self._response_generator = ResponseGenerator(use_llm=False)

        try:
            rag_config = RAGConfig(
                enabled=True,
                provider="sentence-transformers",
                persist_directory=str(project_root / "data" / "vector_db")
            )
            self._rag_engine = RAGEngine(rag_config)
            self._rag_engine.initialize(str(project_root / "knowledge_base"))
        except Exception as e:
            print(f"RAG 引擎初始化失败: {e}")
            self._rag_engine = None

        self._initialized = True

    def recognize_intent(self, state: AgentState) -> AgentState:
        """节点1: 意图识别"""
        self.initialize()

        message = state["message"]
        intent_result = self._intent_recognizer.recognize(message)

        return {
            "intent": intent_result.intent.value,
            "intent_type": intent_result.intent.value,
            "intent_confidence": intent_result.confidence,
            "metadata": {
                "entities": intent_result.entities,
                "context": intent_result.context,
                "suggested_response_type": intent_result.suggested_response_type
            }
        }

    def retrieve_knowledge(self, state: AgentState) -> AgentState:
        """节点2: RAG 知识检索"""
        self.initialize()

        if not self._rag_engine or not self._rag_engine.is_enabled:
            return {
                "rag_context": "",
                "rag_results": [],
                "knowledge_refs": []
            }

        message = state["message"]
        intent_type = state.get("intent_type", "")

        try:
            rag_result = self._rag_engine.query(message, top_k=3)

            if rag_result and rag_result.get("results"):
                context_parts = []
                refs = []
                for item in rag_result["results"][:3]:
                    content = item.get("content", "")[:200]
                    source = item.get("source", "未知来源")
                    context_parts.append(f"[{source}]\n{content}")
                    refs.append(source)

                rag_context = "\n\n---\n\n".join(context_parts)
            else:
                rag_context = ""
                refs = []

            return {
                "rag_context": rag_context,
                "rag_results": rag_result.get("results", []) if rag_result else [],
                "knowledge_refs": refs
            }
        except Exception as e:
            return {
                "rag_context": "",
                "rag_results": [],
                "knowledge_refs": [],
                "error": f"知识检索失败: {str(e)}"
            }

    def get_user_profile(self, state: AgentState) -> AgentState:
        """节点3: 获取用户画像"""
        self.initialize()

        user_id = state["user_id"]
        profile = {}

        try:
            profile = self._profile_manager.get_profile(user_id)
            if not profile:
                profile = {
                    "user_id": user_id,
                    "knowledge_level": "beginner",
                    "behavior_stage": "precontemplation",
                    "communication_style": "friendly"
                }
        except Exception as e:
            profile = {
                "user_id": user_id,
                "knowledge_level": "beginner",
                "behavior_stage": "precontemplation"
            }

        return {"profile": profile}

    def update_profile(self, state: AgentState) -> AgentState:
        """节点4: 更新用户画像"""
        self.initialize()

        user_id = state["user_id"]
        message = state["message"]
        intent_type = state.get("intent_type", "")
        profile = state.get("profile", {})

        try:
            updates = self._dynamic_updater.analyze_message(
                user_id=user_id,
                message=message,
                intent_type=intent_type,
                current_profile=profile
            )
            return {"profile_updates": updates}
        except Exception as e:
            return {"profile_updates": {}, "error": f"画像更新失败: {str(e)}"}

    def generate_recommendations(self, state: AgentState) -> AgentState:
        """节点5: 生成个性化推荐"""
        self.initialize()

        user_id = state["user_id"]
        profile = state.get("profile", {})
        intent_type = state.get("intent_type", "")

        try:
            recommendations = self._recommendation_engine.generate_recommendations(
                user_id=user_id,
                user_profile=profile,
                context={"intent_type": intent_type}
            )

            suggestions = [r.get("action", "") for r in recommendations[:3] if r.get("action")]

            return {
                "recommendations": recommendations[:5],
                "suggestions": suggestions
            }
        except Exception as e:
            return {"recommendations": [], "suggestions": [], "error": f"推荐生成失败: {str(e)}"}

    def generate_response(self, state: AgentState) -> AgentState:
        """节点6: 响应生成"""
        self.initialize()

        message = state["message"]
        intent_type = state.get("intent_type", "")
        rag_context = state.get("rag_context", "")
        profile = state.get("profile", {})
        recommendations = state.get("recommendations", [])
        suggestions = state.get("suggestions", [])

        try:
            from agent.response import ResponseContext
            context = ResponseContext(
                user_profile=profile,
                conversation_history=state.get("messages", []),
                retrieved_knowledge=state.get("rag_results", []),
                recent_memories=state.get("memory_hints", []),
                intent_type=intent_type
            )

            response = self._response_generator.generate_response(
                user_input=message,
                context=context
            )

            response_text = response.get("message", "")
            if rag_context and intent_type == "knowledge_query":
                response_text += f"\n\n[KB] 参考资料：\n{rag_context[:300]}..."

            return {
                "response_message": response_text,
                "suggestions": suggestions or response.get("suggestions", []),
                "messages": [{
                    "role": "assistant",
                    "content": response_text,
                    "timestamp": datetime.now().isoformat()
                }]
            }
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {
                "response_message": f"抱歉，生成响应时出现错误: {str(e)}",
                "error": f"响应生成失败: {str(e)}"
            }

    def handle_error(self, state: AgentState) -> AgentState:
        """错误处理节点"""
        error = state.get("error", "未知错误")
        return {
            "response_message": f"处理过程中遇到问题: {error}",
            "turn_count": state.get("turn_count", 0) + 1
        }

    def should_use_rag(self, state: AgentState) -> str:
        """条件边: 是否使用 RAG"""
        intent_type = state.get("intent_type", "")
        if intent_type in [IntentType.KNOWLEDGE_QUERY.value, IntentType.ADVICE_REQUEST.value]:
            return "use_rag"
        return "skip_rag"

    def should_update_profile(self, state: AgentState) -> str:
        """条件边: 是否更新画像"""
        intent_type = state.get("intent_type", "")
        if intent_type in [IntentType.ACTION_REPORT.value, IntentType.FEEDBACK.value]:
            return "update_profile"
        return "skip_update"

    def should_recommend(self, state: AgentState) -> str:
        """条件边: 是否生成推荐"""
        intent_type = state.get("intent_type", "")
        if intent_type in [IntentType.ADVICE_REQUEST.value, IntentType.GREETING.value]:
            return "generate_recommendation"
        return "skip_recommendation"


_nodes_instance = None

def get_nodes() -> AgentNodes:
    """获取节点实例（单例）"""
    global _nodes_instance
    if _nodes_instance is None:
        _nodes_instance = AgentNodes()
    return _nodes_instance


def recognize_intent(state: AgentState) -> AgentState:
    """意图识别节点"""
    return get_nodes().recognize_intent(state)

def retrieve_knowledge(state: AgentState) -> AgentState:
    """RAG 知识检索节点"""
    return get_nodes().retrieve_knowledge(state)

def get_user_profile(state: AgentState) -> AgentState:
    """获取用户画像节点"""
    return get_nodes().get_user_profile(state)

def update_profile(state: AgentState) -> AgentState:
    """更新用户画像节点"""
    return get_nodes().update_profile(state)

def generate_recommendations(state: AgentState) -> AgentState:
    """生成推荐节点"""
    return get_nodes().generate_recommendations(state)

def generate_response(state: AgentState) -> AgentState:
    """响应生成节点"""
    return get_nodes().generate_response(state)

def handle_error(state: AgentState) -> AgentState:
    """错误处理节点"""
    return get_nodes().handle_error(state)
