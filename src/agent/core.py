"""
智能体核心引擎
整合意图识别、知识检索、RAG、记忆管理和响应生成
支持增强的用户画像和个性化推荐
"""

# P5-F: 模块级 logger
try:
    from observability import get_logger
    _logger = get_logger("agent.core")
except Exception:
    import logging
    _logger = logging.getLogger("agent.core")

# Windows UTF-8 encoding setup
import sys
# Windows UTF-8 encoding setup - Only if not already wrapped (avoid duplicate wrapping)
if sys.platform == 'win32':
    import io
    if not isinstance(sys.stdout, io.TextIOWrapper) or sys.stdout.encoding != 'utf-8':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import uuid
import sqlite3
import os
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path

script_path = Path(__file__).resolve()
src_path = script_path.parent.parent
project_root = script_path.parent.parent.parent

if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

_imported_modules = {}


def _get_module(name):
    if name not in _imported_modules:
        if name == 'intent':
            from agent.intent import IntentRecognizer, IntentType, IntentResult
            _imported_modules[name] = (IntentRecognizer, IntentType, IntentResult)
        elif name == 'response':
            from agent.response import ResponseGenerator, ResponseContext
            _imported_modules[name] = (ResponseGenerator, ResponseContext)
        elif name == 'knowledge':
            from knowledge.manager import KnowledgeManager
            _imported_modules[name] = KnowledgeManager
        elif name == 'memory':
            from memory.short_term import ShortTermMemory
            from memory.long_term import LongTermMemory
            _imported_modules[name] = (ShortTermMemory, LongTermMemory)
        elif name == 'profile':
            from user_profile.user_profile import UserProfileManager
            from user_profile.dynamic_updater import get_profile_updater
            from user_profile.personalized_recommender import PersonalizedRecommendationEngine
            _imported_modules[name] = (UserProfileManager, get_profile_updater, PersonalizedRecommendationEngine)
        elif name == 'helpers':
            from utils.helpers import create_response_structure, get_current_datetime
            _imported_modules[name] = (create_response_structure, get_current_datetime)
        elif name == 'tools':
            # P6.S.3: 工具集(TravelPlanningTool 等)懒加载
            from agent.tools.extended import TravelPlanningTool
            _imported_modules[name] = TravelPlanningTool
    return _imported_modules.get(name)


@dataclass
class AgentResponse:
    """智能体响应"""
    message: str
    conversation_id: str
    intent: str
    suggestions: List[str] = field(default_factory=list)
    knowledge_refs: List[str] = field(default_factory=list)
    memory_hints: List[str] = field(default_factory=list)
    profile_updates: Dict = field(default_factory=dict)
    timestamp: str = ""
    personalization_info: Dict = field(default_factory=dict)
    tool_result: Optional[Dict] = None  # P6.S.3: 工具调用结果(地图+天气+碳排)


@dataclass
class EnhancedAgentResponse(AgentResponse):
    """增强版智能体响应"""
    rag_context: str = ""
    personalization_info: Dict = field(default_factory=dict)
    recommendations: List[Dict] = field(default_factory=list)


class GreenAgent:
    """绿色低碳智能体核心引擎"""

    def __init__(
        self,
        knowledge_base_path: str = None,
        use_vector_db: bool = False,
        enable_rag: bool = True,
        use_llm: bool = True
    ):
        IntentRecognizer, IntentType, IntentResult = _get_module('intent')
        ResponseGenerator, ResponseContext = _get_module('response')
        KnowledgeManager = _get_module('knowledge')
        ShortTermMemory, LongTermMemory = _get_module('memory')
        UserProfileManager, get_profile_updater, PersonalizedRecommendationEngine = _get_module('profile')

        self.intent_recognizer = IntentRecognizer()
        self.response_generator = ResponseGenerator(use_llm=use_llm)
        self.use_llm = use_llm

        if knowledge_base_path is None:
            knowledge_base_path = str(project_root / "knowledge_base")
        self.knowledge_manager = KnowledgeManager(knowledge_base_path)

        self.rag_enabled = False
        self.rag_engine = None
        if enable_rag:
            self._init_rag_engine(knowledge_base_path)

        from memory.short_term import get_short_term_memory
        self.short_term_memory = get_short_term_memory()
        self.long_term_memory = LongTermMemory()
        self.profile_manager = UserProfileManager()
        self.dynamic_updater = get_profile_updater()
        self.recommendation_engine = PersonalizedRecommendationEngine()

        try:
            from utils.web_search import WebSearcher
            self.web_searcher = WebSearcher()
        except Exception as e:
            print(f"   - 网络搜索模块加载失败: {e}")
            self.web_searcher = None

        from agent.conversation_store import get_conversation_store
        self.conversation_store = get_conversation_store()
        self.active_conversations = self.conversation_store._conversations  # 兼容旧代码
        self.user_conversations = self.conversation_store._user_index      # 兼容旧代码
        self.use_vector_db = use_vector_db

        # LangGraph 支持
        self.use_langgraph = os.environ.get("USE_LANGGRAPH", "false").lower() == "true"
        self.langgraph_agent = None
        if self.use_langgraph:
            try:
                from agent.langgraph_agent import LangGraphAgent
                self.langgraph_agent = LangGraphAgent(
                    knowledge_base_path=knowledge_base_path,
                    use_vector_db=use_vector_db,
                    enable_rag=enable_rag,
                    use_llm=use_llm
                )
                print(f"   - LangGraph 模式: 已启用")
            except Exception as e:
                print(f"   - LangGraph 模式: 启用失败 ({e})")
                self.use_langgraph = False

        print(f"绿色低碳智能体初始化完成")
        print(f"   - 知识库: {len(self.knowledge_manager.get_all_documents())} 篇文档")
        print(f"   - RAG 引擎: {'已启用' if self.rag_enabled else '未启用'}")
        print(f"   - LLM 支持: {'已启用' if use_llm else '未启用'}")
        print(f"   - 个性化推荐: 已启用")
        print(f"   - LangGraph: {'已启用' if self.use_langgraph else '未启用'}")

    def _init_rag_engine(self, knowledge_base_path: str):
        """初始化 RAG 引擎"""
        try:
            from rag.rag_engine import RAGEngine, RAGConfig

            config = RAGConfig(
                enabled=True,
                provider="sentence-transformers",
                embedding_model="paraphrase-multilingual-MiniLM-L12-v2",
                vector_store_type="chroma",
                persist_directory=str(project_root / "data" / "vector_db"),
                collection_name="green_agent_knowledge",
                default_top_k=5,
                # P4-G: MiniLM 距离归一化后普遍 0.05-0.15,0.3 会漏检全部结果
                min_similarity=0.0,
                hybrid_search=True,
                semantic_weight=0.6
            )

            self.rag_engine = RAGEngine(config)
            if self.rag_engine.initialize(knowledge_base_path):
                self.rag_enabled = True
                print(f"[OK] RAG 引擎初始化成功")
        except Exception as e:
            _logger.warning(f"RAG 引擎初始化失败: {e}")
            self.rag_enabled = False
            self.rag_engine = None

    # ========== Onboarding 用户引导 ==========

    def get_onboarding_status(self, user_id: str) -> Dict[str, Any]:
        """获取用户引导状态"""
        profile = self.profile_manager.get_profile(user_id)

        onboarding_completed = profile.get("onboarding_completed", False)
        current_step = profile.get("onboarding_step", 0)

        questions = self.profile_manager.get_onboarding_questions()

        return {
            "completed": onboarding_completed,
            "current_step": current_step,
            "total_steps": len(questions),
            "questions": questions if not onboarding_completed else [],
            "progress_percentage": int((current_step / len(questions)) * 100) if questions else 100
        }

    def process_onboarding_answer(
        self,
        user_id: str,
        step: int,
        answer: Any
    ) -> Dict[str, Any]:
        """处理引导问题的回答"""
        questions = self.profile_manager.get_onboarding_questions()

        current_question = None
        for q in questions:
            if q["step"] == step:
                current_question = q
                break

        if not current_question:
            return {"success": False, "error": "无效的步骤"}

        field = current_question["field"]
        profile = self.profile_manager.get_profile(user_id)

        if field == "primary_interests" and isinstance(answer, list):
            current_interests = profile.get("eco_profile", {}).get("primary_interests", [])
            new_interests = list(set(current_interests + answer))
            self.profile_manager.update_eco_profile(user_id, {"primary_interests": new_interests})
        elif field == "region":
            self.profile_manager.update_basic_info(user_id, {"region": answer})
        elif field == "eco_knowledge":
            level_map = {"low": "beginner", "medium": "intermediate", "high": "advanced"}
            self.profile_manager.update_eco_profile(user_id, {"knowledge_level": level_map.get(answer, "intermediate")})
        else:
            self.profile_manager.update_basic_info(user_id, {field: answer})

        self.profile_manager.update_profile(user_id, {"onboarding_step": step})

        next_step = step + 1
        next_question = None
        for q in questions:
            if q["step"] == next_step:
                next_question = q
                break

        # 已完成所有问题
        if next_step >= len(questions):
            self.profile_manager.complete_onboarding(user_id, profile.get("basic_info", {}))
            return {
                "success": True,
                "completed": True,
                "message": "太好了！你已经完成了初始设置。现在让我们开始吧！"
            }

        return {
            "success": True,
            "completed": False,
            "next_step": next_step,
            "next_question": next_question
        }

    def start_onboarding(self, user_id: str) -> Dict[str, Any]:
        """开始引导流程"""
        profile = self.profile_manager.get_profile(user_id)
        self.profile_manager.update_profile(user_id, {"onboarding_step": 0})

        questions = self.profile_manager.get_onboarding_questions()

        return {
            "started": True,
            "total_steps": len(questions),
            "first_question": questions[0] if questions else None,
            "welcome_message": self._generate_onboarding_welcome()
        }

    def _generate_onboarding_welcome(self) -> str:
        """生成欢迎消息"""
        return """欢迎来到绿色低碳智能体！

在开始之前，我想先了解一下你的情况，这样可以为你提供更个性化的建议。

这个过程大约需要1-2分钟，回答没有对错之分。

准备好了吗？让我们开始吧！"""

    # ========== 用户注册 ==========

    def register_user(self, user_info: Dict[str, Any] = None, account_id: str = None) -> str:
        """
        注册新用户

        Args:
            user_info: 用户信息字典（可选）
            account_id: 账号ID（可选，用于关联已有账号）

        Returns:
            user_id
        """
        user_id = str(uuid.uuid4())[:12]

        profile = {
            "user_id": user_id,
            "account_id": account_id,  # 关联的账号ID
            "registration_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "basic_info": {
                "age_group": user_info.get("age_group") if user_info else None,
                "gender": user_info.get("gender") if user_info else None,
                "region": user_info.get("region") if user_info else None,
                "income_level": user_info.get("income_level") if user_info else None,
                "family_type": user_info.get("family_type") if user_info else None,
            },
            "eco_profile": {
                "knowledge_level": self._estimate_knowledge_level(user_info) if user_info else "intermediate",
                "behavior_stage": "意向",
                "awareness_level": user_info.get("eco_awareness", "medium") if user_info else "medium",
                "primary_interests": user_info.get("interests", []) if user_info else [],
                "action_history": [],
                "completed_actions": [],
            },
            "communication_style": self._detect_communication_style(user_info) if user_info else "balanced",
            "preferences": {
                "content_depth": "balanced",
                "response_length": "medium",
                "tone": "encouraging",
            },
            "statistics": {
                "total_conversations": 0,
                "total_messages": 0,
                "questions_asked": 0,
                "actions_reported": 0,
                "feedback_given": 0,
                "suggestions_accepted": 0,
                "suggestions_rejected": 0,
            },
            "last_interaction": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        self.profile_manager.create_profile(user_id, profile)

        # 如果有关联账号，也关联到账号系统
        if account_id:
            try:
                from auth.account_manager import AccountManager
                account_mgr = AccountManager()
                account_mgr.link_user_profile(account_id, user_id)
            except Exception as e:
                print(f"[GreenAgent] 关联账号失败: {e}")

        if user_info and user_info.get("interests"):
            self.long_term_memory.update_preference(
                user_id, "topics", user_info["interests"], confidence=0.9
            )

        return user_id

    def _estimate_knowledge_level(self, user_info: Dict) -> str:
        """根据用户信息估算环保知识水平"""
        awareness = user_info.get("eco_awareness", "medium")
        level_map = {"low": "beginner", "medium": "intermediate", "high": "advanced"}
        return level_map.get(awareness, "intermediate")

    def _detect_communication_style(self, user_info: Dict) -> str:
        """检测沟通风格偏好"""
        age_str = user_info.get("age_group", "26-35")
        try:
            if isinstance(age_str, str) and '-' in age_str:
                age = int(age_str.split('-')[0])
            else:
                age = int(age_str)
        except (ValueError, TypeError):
            age = 30

        if age < 25:
            return "通俗"
        elif age < 45:
            return "平衡"
        else:
            return "专业"

    # ========== 个性化聊天 (RAG + 推荐) ==========

    def chat_enhanced(
        self,
        user_id: str,
        message: str,
        conversation_id: str = None
    ) -> EnhancedAgentResponse:
        """增强版聊天 - 使用 RAG 和个性化推荐"""

        if self.use_langgraph and self.langgraph_agent:
            langgraph_response = self.langgraph_agent.chat(user_id, message, conversation_id)
            return EnhancedAgentResponse(
                message=langgraph_response.message,
                conversation_id=langgraph_response.conversation_id,
                intent=langgraph_response.intent,
                suggestions=langgraph_response.suggestions,
                knowledge_refs=langgraph_response.knowledge_refs,
                memory_hints=langgraph_response.memory_hints,
                profile_updates=langgraph_response.profile_updates,
                timestamp=langgraph_response.timestamp,
                personalization_info=langgraph_response.personalization_info,
                recommendations=langgraph_response.recommendations,
                rag_context=langgraph_response.metadata.get("rag_context", "")
            )

        IntentRecognizer, IntentType, IntentResult = _get_module('intent')
        ResponseGenerator, ResponseContext = _get_module('response')
        get_current_datetime = _get_module('helpers')[1]

        conversation_id = self._manage_conversation(user_id, conversation_id)
        conversation = self.active_conversations[conversation_id]
        conversation.turn_count += 1
        conversation.last_updated = get_current_datetime()

        user_profile = self.profile_manager.get_profile(user_id)

        # 检查是否配置了任何 API Key
        api_providers = [
            ("API_KEY", ""),
            ("OPENAI_API_KEY", "openai"),
            ("MINIMAX_API_KEY", "minimax"),
            ("ZHIPU_API_KEY", "zhipu"),
            ("BAIDU_API_KEY", "baidu"),
            ("ALI_API_KEY", "ali"),
            ("DEEPSEEK_API_KEY", "deepseek"),
        ]
        has_api_config = any(
            os.getenv(key) and os.getenv(key) not in ("", "your_api_key_here")
            for key, _ in api_providers
        )

        if not user_profile.get("onboarding_completed", False) and conversation.turn_count > 3 and not has_api_config:
            return EnhancedAgentResponse(
                message="我们还没完成初始设置，这样我无法为你提供最佳服务。让我们先完成设置吧！",
                conversation_id=conversation_id,
                intent="onboarding_reminder",
                timestamp=get_current_datetime()
            )

        rag_context = ""
        knowledge_refs = []
        rag_results = []
        if self.rag_enabled and self.rag_engine:
            rag_results = self.rag_engine.retrieve(message, top_k=5)
        if rag_results:
            context_parts = []
            for i, r in enumerate(rag_results, 1):
                context_parts.append(f"[来源 {i}]: {r.get_summary()}")
                knowledge_refs.append(f"{r.metadata.get('source', '')} (相似度: {r.score:.2f})")
            rag_context = "\n\n".join(context_parts)

        intent_result = self.intent_recognizer.recognize(message)

        message_analysis = self.dynamic_updater.analyze_message(
            user_id, message,
            intent_result.intent.value,
            intent_result.entities
        )

        profile_updates = self._apply_dynamic_updates(user_id, message_analysis)

        # P6.C: 画像有更新时清缓存(避免新画像用旧 LLM 响应)
        if profile_updates:
            try:
                from agent.cache import get_query_cache
                cleared = get_query_cache().invalidate(user_id)
                if cleared > 0:
                    import logging
                    logging.getLogger(__name__).info(
                        "[GreenAgent] QueryCache.invalidate user=%s cleared=%d (因画像更新)",
                        user_id, cleared,
                    )
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning("[GreenAgent] QueryCache.invalidate 异常(非致命): %s", e)

        self.profile_manager.record_interaction(user_id, self._map_intent_to_interaction(intent_result))

        recent_memories = self._get_recent_memories(user_id)
        # P4-B.4: 真正的语义+时间召回,覆盖默认的"最近 3 条"
        try:
            recalled = self._recall_memories(message, user_id, limit=5)
            if recalled:
                recent_memories = [
                    f"[{m.get('type', 'memory')}] {m.get('content', '')[:60]}"
                    for m in recalled
                ]
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("[GreenAgent] 记忆召回失败: %s", e)

        conversation_history = self.short_term_memory.get_conversation_history(conversation_id)

        personalization_ctx = self.profile_manager.get_personalization_context(user_id)
        strategy = self.profile_manager.get_suggestion_strategy(user_id)

        # P4-D: 合并 strategy 字段到 personalization_ctx,供 LLM prompt 注入
        personalization_ctx = {
            **personalization_ctx,
            "focus": strategy.get("focus"),
            "suggestion_intensity": strategy.get("suggestion_intensity"),
            "action_complexity": strategy.get("action_complexity"),
            "tone": strategy.get("tone"),
            "example_focus": strategy.get("example_focus"),
        }

        recommendations = []
        if intent_result.intent in [IntentType.ADVICE_REQUEST, IntentType.GREETING]:
            recs = self.recommendation_engine.generate_recommendations(user_profile, count=2)
            recommendations = [
                {
                    "action": r.action,
                    "category": r.category,
                    "reason": r.reason,
                    "carbon_saving": r.estimated_carbon_saving,
                    "examples": r.examples
                }
                for r in recs
            ]

        # 将 RAG 检索结果转换为 ResponseContext 格式
        retrieved_knowledge = []
        if rag_results:
            for r in rag_results:
                retrieved_knowledge.append({
                    "title": r.metadata.get("title", ""),
                    "content": r.content,
                    "source": r.metadata.get("source", ""),
                    "category": r.metadata.get("category", "")
                })

        context = ResponseContext(
            user_profile=user_profile,
            conversation_history=conversation_history,
            retrieved_knowledge=retrieved_knowledge,
            recent_memories=recent_memories,
            intent_type=intent_result.suggested_response_type
        )

        # P6.C: Query Cache — 命中时复用 message + suggestions,跳过 LLM 调用
        cached_response = None
        try:
            from agent.cache import get_query_cache
            cached_response = get_query_cache().get(message, user_id, user_profile)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("[GreenAgent] QueryCache.get 异常(非致命): %s", e)

        if cached_response:
            # 命中:复用 LLM 输出,其余字段(RAG/recs/profile/memory)仍跑
            response_data = {
                "message": cached_response["message"],
                "suggestions": cached_response.get("suggestions", []),
            }
        else:
            response_data = self._generate_personalized_response(
                message, context, intent_result, rag_context, personalization_ctx, strategy
            )
            # 写缓存(失败不致命)
            try:
                from agent.cache import get_query_cache
                get_query_cache().set(
                    message, user_id, user_profile,
                    response_data["message"],
                    response_data.get("suggestions", []),
                )
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning("[GreenAgent] QueryCache.set 异常(非致命): %s", e)

        self._save_conversation(conversation_id, user_id, message, response_data["message"])
        self.profile_manager.update_conversation_count(user_id)

        # P4-B.1: 接入记忆整合器(短→长)
        try:
            from memory.consolidation import get_consolidator
            consolidator = get_consolidator()
            consolidator.update_conversation_activity(conversation_id)
            consolidator.update_message_count(conversation_id, count=2)
            consolidated = consolidator.consolidate(user_id, conversation_id)
            if consolidated > 0:
                import logging
                logging.getLogger(__name__).info(
                    "[GreenAgent] 记忆整合: user=%s conv=%s saved=%d",
                    user_id, conversation_id, consolidated,
                )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("[GreenAgent] 记忆整合失败(非致命): %s", e)

        return EnhancedAgentResponse(
            message=response_data["message"],
            conversation_id=conversation_id,
            intent=intent_result.intent.value,
            suggestions=response_data.get("suggestions", []),
            knowledge_refs=knowledge_refs,
            memory_hints=recent_memories,
            profile_updates=profile_updates,
            timestamp=get_current_datetime(),
            rag_context=rag_context,
            personalization_info=personalization_ctx,
            recommendations=recommendations
        )

    def _map_intent_to_interaction(self, intent_result) -> str:
        """映射意图到交互类型"""
        IntentType = _get_module('intent')[1]
        mapping = {
            IntentType.KNOWLEDGE_QUERY: "question",
            IntentType.ADVICE_REQUEST: "question",
            IntentType.ACTION_REPORT: "action",
            IntentType.FEEDBACK: "feedback",
            IntentType.SUGGESTION_ACCEPT: "accept",
            IntentType.SUGGESTION_REJECT: "reject"
        }
        return mapping.get(intent_result.intent, "question")

    def _apply_dynamic_updates(self, user_id: str, analysis: Dict) -> Dict:
        """应用动态更新"""
        updates = {}

        if analysis.get("detected_interests"):
            top_interests = [i[0] for i in analysis["detected_interests"][:2]]
            current = self.profile_manager.get_profile(user_id)
            existing = current.get("eco_profile", {}).get("primary_interests", [])
            new_interests = list(set(existing + top_interests))[:8]
            self.profile_manager.update_eco_profile(user_id, {"primary_interests": new_interests})
            updates["new_interests"] = top_interests

        if analysis.get("knowledge_signals"):
            signal = analysis["knowledge_signals"][0]
            if signal.get("confidence", 0) > 0.5:
                self.profile_manager.update_eco_profile(
                    user_id,
                    {"knowledge_level": signal.get("level", "intermediate")}
                )
                updates["knowledge_updated"] = signal.get("level")

        if analysis.get("behavior_indicators"):
            indicator = analysis["behavior_indicators"][0]
            if indicator.get("confidence", 0) > 0.6:
                self.profile_manager.update_eco_profile(
                    user_id,
                    {"behavior_stage": indicator.get("stage", "意向")}
                )
                updates["stage_changed"] = indicator.get("stage")

        if analysis.get("action_reports"):
            for action in analysis["action_reports"]:
                if action.get("sentiment") == "positive":
                    self.profile_manager.update_preference_learning(
                        user_id,
                        action=action.get("type"),
                        accepted=True
                    )

        return updates

    def _generate_personalized_response(
        self,
        message: str,
        context,
        intent_result,
        rag_context: str,
        personalization: Dict,
        strategy: Dict
    ) -> Dict:
        """生成个性化响应"""
        IntentType = _get_module('intent')[1]

        knowledge_level = personalization.get("knowledge_level", "intermediate")
        knowledge_level_cn = personalization.get("knowledge_level_chinese", "了解")

        # 尝试使用LLM生成响应
        llm_response = None
        if self.use_llm and self.response_generator:
            try:
                # P4-H: 注入工作记忆(per-user 跨 session 的 workspace)
                working_memory_text = ""
                try:
                    from memory.working import get_working_memory
                    wm = get_working_memory()
                    working_memory_text = wm.snapshot_for_prompt(user_id)
                except Exception:
                    pass
                llm_response = self.response_generator.generate_with_llm(
                    message, context, rag_context, working_memory=working_memory_text,
                )
            except Exception as e:
                print(f"LLM生成失败，回退到模板: {e}")

        if llm_response:
            return {
                "message": llm_response,
                "suggestions": [],
                "response_type": "llm_generated"
            }

        # 回退到模板生成
        base_response = self.response_generator.generate_response(message, context)

        # P6.S.5: 不再 dump 整个 RAG 内容(可能超长且不相关),只取前 N 字精华
        RAG_PREVIEW_CHARS = 800  # 截断长度,避免模板返 5KB 文档原文

        if rag_context:
            if intent_result.intent == IntentType.KNOWLEDGE_QUERY:
                prefix = f"根据我的知识库，"
                if knowledge_level == "beginner":
                    prefix += f"让我用简单的话解释：\n\n"
                else:
                    prefix += "\n\n"
                # 只取首 N 字 + 略去的提示
                rag_preview = rag_context[:RAG_PREVIEW_CHARS]
                if len(rag_context) > RAG_PREVIEW_CHARS:
                    rag_preview += "\n...(更多内容见下方参考资料)"
                main_content = f"{rag_preview}\n\n{base_response['message']}"
            elif intent_result.intent == IntentType.ADVICE_REQUEST:
                prefix = f"结合你的情况（{knowledge_level_cn}水平，{strategy.get('behavior_stage', '意向')}阶段），"
                rag_preview = rag_context[:RAG_PREVIEW_CHARS]
                main_content = f"{base_response['message']}\n\n相关知识参考：\n{rag_preview}"
            else:
                prefix = ""
                main_content = base_response["message"]
        else:
            prefix = self._generate_prefix(intent_result, personalizacion)
            main_content = base_response["message"]

        suffix = self._generate_suffix(intent_result, personalization)

        response_parts = []
        if prefix:
            response_parts.append(prefix)
        response_parts.append(main_content)
        if suffix:
            response_parts.append(suffix)

        return {
            "message": "\n\n".join(response_parts),
            "suggestions": base_response.get("suggestions", []),
            "response_type": base_response.get("response_type", "general")
        }

    def _generate_prefix(self, intent_result, personalization: Dict) -> str:
        """生成响应前缀"""
        IntentType = _get_module('intent')[1]
        basic_summary = personalization.get("basic_info_summary", "")
        confirmed_interests = personalization.get("confirmed_interests", [])

        if intent_result.intent == IntentType.GREETING:
            if personalization.get("conversation_count", 0) == 0:
                return "你好！很高兴认识你！"
            else:
                return f"欢迎回来！{basic_summary}，我们继续聊吧！"

        if confirmed_interests and len(confirmed_interests) > 0:
            interest_str = "、".join(confirmed_interests[:2])
            return f"我记得你关注{interest_str}，"

        return ""

    def _generate_suffix(self, intent_result, personalization: Dict) -> str:
        """生成响应后缀"""
        IntentType = _get_module('intent')[1]
        behavior_stage = personalization.get("behavior_stage", "意向")

        if intent_result.intent in [IntentType.KNOWLEDGE_QUERY, IntentType.ADVICE_REQUEST]:
            stage_tips = {
                "无意向": "从小事开始，一起加油！",
                "意向": "有什么想法吗？我可以帮你分析！",
                "准备": "准备行动了吗？有什么问题随时问！",
                "行动": "继续坚持！你的努力很棒！",
                "维持": "你是低碳达人！有什么新想法吗？"
            }
            return stage_tips.get(behavior_stage, "")

        return ""

    # ========== 基础聊天 (保持向后兼容) ==========

    def _handle_travel_planning(self, user_id, message, conversation_id, intent_result):
        """P6.S.3: 出行规划专用流程 — 调高德地图 + 天气 + 碳排对比

        提取 origin/destination → 调 TravelPlanningTool → 返结构化结果
        若提取不到 origin/destination,降级为 advice(让用户补充)
        """
        import re
        from utils.helpers import get_current_datetime

        TravelPlanningTool = _get_module('tools')

        # 1) 提取 origin / destination(P6.S.3 + S.4 改进)
        import re as _re

        # P6.S.4: 时间/代词/动词白名单,避免被误判为 origin
        NON_LOC_WORDS = {
            "我", "你", "他", "她", "我们", "我明天", "你明天",
            "今天", "明天", "后天", "大后天", "今天要", "明天要", "我明天要", "你明天要",
            "现在", "之后", "再", "马上", "等下", "等一会儿",
            "请", "麻烦", "想", "要", "想从", "要去", "要带", "准备",
            "我等", "我马上", "我先", "我现", "我准", "下午", "上午", "晚上"
        }
        NON_LOC_SUBSTR = ["要", "想", "准备", "马上", "等", "坐", "去", "我", "你"]

        def _is_valid_origin(s: str) -> bool:
            """检查 s 是不是个有效的 location 词(过滤时间/代词/动词)"""
            if not s or len(s) < 2:
                return False
            if s in NON_LOC_WORDS:
                return False
            if any(s.startswith(w) for w in NON_LOC_WORDS if len(w) >= 2):
                return False
            if any(v in s for v in NON_LOC_SUBSTR):
                return False
            return True

        origin = None
        destination = None

        # 模式 1: "从A到B" 或 "从A去B" — 都有明确出发地
        m = _re.search(r'从\s*([^到去,,,?？\s]{2,15})\s*[到去]\s*([^,,,?？\s]{2,15})', message)
        if m:
            cand_o = m.group(1).strip()
            if _is_valid_origin(cand_o):
                origin = cand_o
                destination = m.group(2).strip()

        # 模式 2: "A到B" 或 "A去B" (无"从")
        if not origin:
            for m in _re.finditer(r'([^到去,,,?？\s]{3,15})\s*[到去]\s*([^,,,?？\s]{2,15})', message):
                if _is_valid_origin(m.group(1).strip()):
                    origin = m.group(1).strip()
                    destination = m.group(2).strip()
                    break

        # 模式 3: "去A" / "到A" — 只有目的地,出发地默认"当前位置"
        if not origin and not destination:
            m = _re.search(r'(?:去|到)\s*([^,,,?？\s]{2,15})', message)
            if m:
                origin = "当前位置"
                destination = m.group(1).strip()

        # 清理 destination 尾部的修饰词(长的先匹配,避免 "最环保" 被 "怎么走" 漏掉)
        if destination:
            for tail in [
                "怎么走最环保", "怎么坐最环保", "最环保的方式", "低碳出行", "环保出行", "绿色出行",
                "怎么走", "怎么坐", "怎么去", "怎么",
                "几点出发", "多久到", "多久", "多长",
                "最环保", "最绿色", "最省时", "最快",
                "出行", "规划", "路线", "坐公交", "坐地铁", "打车",
            ]:
                if destination.endswith(tail):
                    destination = destination[:-len(tail)].strip()
                    break  # 一次只剥一个,重新进入下一轮
            # 也清掉"去/到"尾巴
            for tail in ["去", "到"]:
                if destination.endswith(tail):
                    destination = destination[:-len(tail)].strip()

        # 清理 origin 同理
        if origin and origin != "当前位置":
            for tail in ["出发", "出发地"]:
                if origin.endswith(tail):
                    origin = origin[:-len(tail)].strip()

        # 2) 提取不到完整信息 — 返澄清问题
        if not origin or not destination:
            return AgentResponse(
                message="要帮你规划出行,需要知道 **出发地** 和 **目的地** 哦。\n\n试试这样说:\n• 从北京西单到国贸怎么走\n• 从家到公司坐公交多久\n• 明天去国贸",
                conversation_id=conversation_id,
                intent="travel_planning",
                suggestions=[
                    "从家到公司怎么走",
                    "从北京西单到国贸,坐地铁多久",
                    "从公司到机场,最环保的方式"
                ],
                timestamp=get_current_datetime()
            )

        # 2) 调工具
        try:
            tool = TravelPlanningTool()
            result = tool.execute(origin=origin, destination=destination, mode="all")
        except Exception as e:
            return AgentResponse(
                message=f"出行规划工具调用失败: {type(e).__name__}: {str(e)[:200]}",
                conversation_id=conversation_id,
                intent="travel_planning",
                suggestions=["试试其它交通方式", "查询附近公交站"],
                timestamp=get_current_datetime()
            )

        # 3) 格式化响应
        if not result.success:
            # 工具调用失败(可能没高德 API key) — 降级给 RAG 建议
            return AgentResponse(
                message=f"⚠️ {result.error or '路线查询失败'}\n\n"
                        f"💡 既然你要去 **{destination}**,以下是一些通用建议:\n"
                        f"• 优先选公交/地铁(碳排约为私家车的 1/5)\n"
                        f"• 短途(<5km) 骑行或步行最环保\n"
                        f"• 长途选高铁优于飞机(碳排约 1/4)",
                conversation_id=conversation_id,
                intent="travel_planning",
                suggestions=["查询附近公交站", "推荐低碳餐厅", "电动车充电桩位置"],
                tool_result={"origin": origin, "destination": destination, "error": result.error},
                timestamp=get_current_datetime()
            )

        # 4) 成功 — 格式化路线
        data = result.data
        routes = data.get("routes", [])
        weather = data.get("weather", {})
        recommended = data.get("recommended", {})

        # 格式化路线(注意:实际 key 是 'type' 不是 'mode')
        route_lines = []
        for i, r in enumerate(routes[:5], 1):
            route_lines.append(
                f"{i}. **{r.get('type', r.get('mode', '?'))}** — {r.get('distance_km', '?')}km, "
                f"约 {r.get('duration_min', '?')} 分钟, 碳排 {r.get('carbon_kg', '?')} kg, "
                f"¥{r.get('cost_yuan', '?')}"
            )
        route_text = "\n".join(route_lines) if route_lines else "(暂无路线数据)"

        # 推荐路线(注意:实际 key 是 'type' 不是 'mode')
        rec_text = ""
        if recommended:
            rec_text = (f"\n\n🌟 **推荐:{recommended.get('type', recommended.get('mode', '?'))}** "
                        f"(综合评分 {recommended.get('score', '?')}/10)\n"
                        f"理由: {recommended.get('reason', '碳排最优')}")

        # 天气(注意:实际 key 是 'temp_c' 不是 'temp')
        weather_text = ""
        if weather:
            w = weather
            weather_text = (f"\n\n🌤️ 天气:{w.get('description', '?')}, "
                            f"温度 {w.get('temp_c', w.get('temp', '?'))}°C, "
                            f"骑行适宜度 {'✅' if w.get('cycling_ok', True) else '⚠️ 不建议'}")

        message_text = (
            f"🚲 **{origin} → {destination}** 低碳出行方案:\n\n"
            f"{route_text}"
            f"{rec_text}"
            f"{weather_text}\n\n"
            f"💡 优先选 **碳排最低** 的方式,环保又健康!"
        )

        # 5) 持久化(记忆 + 对话)
        try:
            self._increment_conversation_count(user_id)
            self._save_conversation(conversation_id, user_id, message, message_text)
        except Exception:
            pass  # 不阻塞主流程

        return AgentResponse(
            message=message_text,
            conversation_id=conversation_id,
            intent="travel_planning",
            suggestions=[
                "查询附近公交站",
                f"推荐 {destination} 附近的低碳餐厅",
                "电动车充电桩位置"
            ],
            tool_result=data,  # 完整结构化数据给前端用
            timestamp=get_current_datetime()
        )

    def chat(self, user_id: str, message: str, conversation_id: str = None) -> 'AgentResponse':
        """处理用户对话（基础版）"""
        IntentRecognizer, IntentType, IntentResult = _get_module('intent')
        ResponseGenerator, ResponseContext = _get_module('response')
        get_current_datetime = _get_module('helpers')[1]

        conversation_id = self._manage_conversation(user_id, conversation_id)
        conversation = self.active_conversations[conversation_id]
        conversation.turn_count += 1
        conversation.last_updated = get_current_datetime()

        intent_result = self.intent_recognizer.recognize(message)

        # P6.S.3: 出行规划走工具调用(高德地图 + 天气 + 碳排对比)
        if intent_result.intent == IntentType.TRAVEL_PLANNING:
            return self._handle_travel_planning(
                user_id, message, conversation_id, intent_result
            )

        if self.web_searcher and self.web_searcher.is_realtime_query(message):
            realtime_response = self.web_searcher.get_realtime_response(message)

            self._update_memories(user_id, conversation_id, message, intent_result, realtime_response)
            self._increment_conversation_count(user_id)
            self._save_conversation(conversation_id, user_id, message, realtime_response)

            return AgentResponse(
                message=realtime_response,
                conversation_id=conversation_id,
                intent="realtime_query",
                suggestions=["给我更多低碳生活建议", "推荐一些环保行动"],
                timestamp=get_current_datetime()
            )

        retrieved_knowledge = self._retrieve_knowledge(message, intent_result)
        user_profile = self.profile_manager.get_profile(user_id)
        recent_memories = self._get_recent_memories(user_id)
        conversation_history = self.short_term_memory.get_conversation_history(conversation_id)

        context = ResponseContext(
            user_profile=user_profile,
            conversation_history=conversation_history,
            retrieved_knowledge=retrieved_knowledge,
            recent_memories=recent_memories,
            intent_type=intent_result.suggested_response_type
        )

        # P6.S.5: 优先用 LLM(若可用),失败回退到模板
        response_data = None
        if self.use_llm and self.response_generator:
            try:
                rag_context_str = "\n".join(
                    k.get("content", "")[:500] for k in retrieved_knowledge[:3]
                ) if retrieved_knowledge else ""
                # P6.S.5 final: 强制 MockLLMClient(若 .env 启 LLM_MOCK 或 server 启动时设过)
                # 直接构造 MockLLMClient 跳过工厂,避免 _build_prompt + llm.chat hang
                if os.getenv("LLM_MOCK", "auto").strip().lower() in ("true", "1", "yes", "on"):
                    from llm.client import MockLLMClient
                    mock = MockLLMClient()
                    # 用 RAG 摘要作为 system context
                    last_user_msg = message
                    augmented_msg = f"{last_user_msg}\n\n[知识库参考资料]:\n{rag_context_str[:1000]}"
                    mock_resp = mock.chat([{"role": "user", "content": augmented_msg}])
                    llm_text = mock_resp.content if hasattr(mock_resp, "content") else str(mock_resp)
                else:
                    llm_text = self.response_generator.generate_with_llm(
                        message, context, rag_context_str
                    )
                if llm_text and llm_text.strip():
                    response_data = {
                        "message": llm_text,
                        "suggestions": [],
                        "knowledge_refs": [k.get("title", "") for k in retrieved_knowledge[:3]],
                        "response_type": "llm_generated"
                    }
            except Exception as e:
                print(f"[P6.S.5] LLM 失败,回退模板: {e}", flush=True)

        if not response_data:
            response_data = self.response_generator.generate_response(message, context)

        profile_updates = self._update_memories(
            user_id, conversation_id, message, intent_result, response_data["message"]
        )
        self._update_user_profile(user_id, intent_result, profile_updates)
        self._save_conversation(conversation_id, user_id, message, response_data["message"])

        # P4-B.1: 接入记忆整合器(短→长)
        try:
            from memory.consolidation import get_consolidator
            consolidator = get_consolidator()
            consolidator.update_conversation_activity(conversation_id)
            consolidator.update_message_count(conversation_id, count=2)
            consolidator.consolidate(user_id, conversation_id)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("[GreenAgent] 记忆整合失败(非致命): %s", e)

        return AgentResponse(
            message=response_data["message"],
            conversation_id=conversation_id,
            intent=intent_result.intent.value,
            suggestions=response_data["suggestions"],
            knowledge_refs=response_data["knowledge_refs"],
            memory_hints=recent_memories,
            profile_updates=profile_updates,
            timestamp=get_current_datetime()
        )

    # ========== 辅助方法 ==========

    def _manage_conversation(self, user_id: str, conversation_id: str = None) -> str:
        """管理对话会话(委托给 ConversationStore 单例)"""
        ctx = self.conversation_store.get_or_create(user_id, conversation_id)
        return ctx.conversation_id

    def _retrieve_knowledge(self, query: str, intent_result) -> List[Dict]:
        """检索知识库"""
        results = self.knowledge_manager.search(query, top_k=3)
        return results

    def _get_recent_memories(self, user_id: str) -> List[str]:
        """获取用户最近的记忆(限到 50 字符,用于 prompt 注入)"""
        memories = []
        long_term_memories = self.long_term_memory.get_recent_memories(user_id, limit=3)
        memories.extend([m.get("content", "")[:50] for m in long_term_memories])
        return memories

    def _recall_memories(self, query: str, user_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """真正的"记忆召回"(P4-B.4)

        策略:
        1) 语义检索:用 query 调 search_memories(LIKE 关键词匹配)
        2) 时间回填:不足 limit 时补 get_recent_memories
        3) 去重(按 memory id),按 importance desc 排序

        Args:
            query: 当前用户消息
            user_id: 用户 ID
            limit: 返回上限

        Returns:
            记忆 dict 列表(含 id, type, content, importance, tags)
        """
        semantic: List[Dict[str, Any]] = []
        if query and query.strip():
            try:
                semantic = self.long_term_memory.search_memories(user_id, query, top_k=limit)
            except Exception:
                semantic = []
        if len(semantic) >= limit:
            return semantic[:limit]

        # 时间回填
        try:
            recent = self.long_term_memory.get_recent_memories(user_id, limit=limit * 2)
        except Exception:
            recent = []
        seen = {m.get("id") for m in semantic if m.get("id") is not None}
        for m in recent:
            if m.get("id") in seen:
                continue
            semantic.append(m)
            seen.add(m.get("id"))
            if len(semantic) >= limit:
                break
        return semantic[:limit]

    def _update_memories(self, user_id, conversation_id, user_message, intent_result, response_message):
        """更新记忆系统"""
        updates = {}

        self.short_term_memory.add_message(
            conversation_id=conversation_id,
            role="user",
            content=user_message,
            metadata={"intent": intent_result.intent.value}
        )
        self.short_term_memory.add_message(
            conversation_id=conversation_id,
            role="assistant",
            content=response_message,
            metadata={"intent": intent_result.intent.value}
        )

        key_info = self._extract_key_info(user_message, intent_result)

        if key_info:
            self.long_term_memory.add_memory(
                user_id=user_id,
                content=key_info["content"],
                memory_type=key_info["type"],
                importance=key_info.get("importance", 0.5)
            )
            updates["new_memory"] = key_info["type"]

        return updates

    def _extract_key_info(self, message: str, intent_result) -> Optional[Dict]:
        """提取关键信息用于记忆"""
        IntentType = _get_module('intent')[1]

        if intent_result.intent == IntentType.ACTION_REPORT:
            return {
                "content": f"用户报告: {message[:100]}",
                "type": "action_report",
                "importance": 0.7
            }
        elif intent_result.intent == IntentType.ADVICE_REQUEST:
            return {
                "content": f"用户感兴趣: {message[:100]}",
                "type": "interest",
                "importance": 0.6
            }
        elif intent_result.intent == IntentType.FEEDBACK:
            return {
                "content": f"用户反馈: {message[:100]}",
                "type": "feedback",
                "importance": 0.8
            }
        return None

    def _update_user_profile(self, user_id: str, intent_result, updates: Dict):
        """更新用户画像"""
        IntentType = _get_module('intent')[1]

        if intent_result.intent == IntentType.KNOWLEDGE_QUERY:
            self.profile_manager.record_interaction(user_id, "question")
        elif intent_result.intent == IntentType.ACTION_REPORT:
            self.profile_manager.record_interaction(user_id, "action")
        elif intent_result.intent == IntentType.FEEDBACK:
            self.profile_manager.record_interaction(user_id, "feedback")

        self.profile_manager.update_conversation_count(user_id)

    def _increment_conversation_count(self, user_id: str):
        """增加对话轮次"""
        self.profile_manager.update_conversation_count(user_id)

    def _save_conversation(self, conversation_id, user_id, user_message, assistant_message):
        """保存对话历史"""
        self.short_term_memory.add_message(conversation_id, "user", user_message)
        self.short_term_memory.add_message(conversation_id, "assistant", assistant_message)

    def get_conversation_history(self, conversation_id: str) -> List[Dict]:
        """获取对话历史"""
        return self.short_term_memory.get_conversation_history(conversation_id)

    def get_user_profile(self, user_id: str) -> Dict[str, Any]:
        """获取用户画像"""
        return self.profile_manager.get_profile(user_id)

    def get_personalization_context(self, user_id: str) -> Dict[str, Any]:
        """获取个性化上下文"""
        return self.profile_manager.get_personalization_context(user_id)

    def get_user_stats(self, user_id: str) -> Dict:
        """获取用户统计信息"""
        profile = self.profile_manager.get_profile(user_id)
        memories = self.long_term_memory.get_preferences(user_id)
        learned = self.dynamic_updater.get_learned_interests(user_id)

        return {
            "user_id": user_id,
            "conversation_count": profile.get("statistics", {}).get("total_conversations", 0),
            "message_count": profile.get("statistics", {}).get("total_messages", 0),
            "questions_asked": profile.get("statistics", {}).get("questions_asked", 0),
            "actions_completed": len(profile.get("eco_profile", {}).get("completed_actions", [])),
            "learned_interests": learned,
            "preferences": memories,
            "engagement_level": self._calculate_engagement(profile),
        }

    def _calculate_engagement(self, profile: Dict) -> str:
        """计算用户参与度"""
        stats = profile.get("statistics", {})
        # 只对数值字段求和，排除字典类型的 topic_interactions
        numeric_fields = [
            "total_conversations", "total_messages", "questions_asked",
            "actions_reported", "feedback_given", "suggestions_accepted", "suggestions_rejected"
        ]
        total = sum(stats.get(field, 0) for field in numeric_fields)

        if total < 5:
            return "low"
        elif total < 20:
            return "medium"
        else:
            return "high"

    def get_knowledge_stats(self) -> Dict[str, Any]:
        """获取知识库统计"""
        stats = self.knowledge_manager.get_stats()
        if self.rag_enabled and self.rag_engine:
            stats["rag_enabled"] = True
            stats["rag_stats"] = self.rag_engine.get_stats()
        else:
            stats["rag_enabled"] = False
        return stats

    def get_rag_stats(self) -> Dict:
        """获取 RAG 统计信息"""
        if not self.rag_enabled or not self.rag_engine:
            return {"enabled": False, "message": "RAG 功能未启用"}
        return self.rag_engine.get_stats()

    def reset_conversation(self, conversation_id: str):
        """重置对话(委托给 ConversationStore)"""
        self.conversation_store.remove(conversation_id)

    def export_user_data(self, user_id: str) -> Dict[str, Any]:
        """导出用户数据"""
        profile = self.profile_manager.get_profile(user_id)
        memories = self.long_term_memory.get_all_memories(user_id)
        preferences = self.long_term_memory.get_preferences(user_id)
        learned_interests = self.dynamic_updater.get_learned_interests(user_id)
        return {
            "profile": profile,
            "memories": memories,
            "preferences": preferences,
            "learned_interests": learned_interests,
            "export_time": datetime.now().isoformat()
        }


if __name__ == "__main__":
    from pathlib import Path
    project_root = Path(__file__).parent.parent.parent

    agent = GreenAgent(
        knowledge_base_path=str(project_root / "knowledge_base"),
        enable_rag=True
    )

    user_id = agent.register_user({
        "age_group": "26-35",
        "region": "北京",
        "interests": ["低碳出行", "节能减排"]
    })
    print(f"\n注册成功，用户ID: {user_id}")

    onboarding = agent.start_onboarding(user_id)
    print(f"\n引导流程: {onboarding}")

    response = agent.chat_enhanced(user_id, "什么是碳中和？")
    print(f"\n助手: {response.message}")
    print(f"\n个性化信息: {response.personalization_info}")
    print(f"\n推荐: {response.recommendations}")
