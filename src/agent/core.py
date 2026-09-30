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

# 别名(兼容历史代码使用 _log)
_log = _logger

# Windows UTF-8 encoding setup
import sys

# Windows UTF-8 encoding setup - Only if not already wrapped (avoid duplicate wrapping)
if sys.platform == "win32":
    import io

    if not isinstance(sys.stdout, io.TextIOWrapper) or sys.stdout.encoding != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import uuid
import os
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

script_path = Path(__file__).resolve()
src_path = script_path.parent.parent
project_root = script_path.parent.parent.parent

if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

_imported_modules = {}


def _get_module(name):
    if name not in _imported_modules:
        if name == "intent":
            from agent.intent import IntentRecognizer, IntentType, IntentResult

            _imported_modules[name] = (IntentRecognizer, IntentType, IntentResult)
        elif name == "response":
            from agent.response import ResponseGenerator, ResponseContext

            _imported_modules[name] = (ResponseGenerator, ResponseContext)
        elif name == "knowledge":
            from knowledge.manager import KnowledgeManager

            _imported_modules[name] = KnowledgeManager
        elif name == "memory":
            from memory.short_term import ShortTermMemory
            from memory.long_term import LongTermMemory

            _imported_modules[name] = (ShortTermMemory, LongTermMemory)
        elif name == "profile":
            from user_profile.user_profile import UserProfileManager
            from user_profile.dynamic_updater import get_profile_updater
            from user_profile.personalized_recommender import PersonalizedRecommendationEngine

            _imported_modules[name] = (
                UserProfileManager,
                get_profile_updater,
                PersonalizedRecommendationEngine,
            )
        elif name == "helpers":
            from utils.helpers import create_response_structure, get_current_datetime

            _imported_modules[name] = (create_response_structure, get_current_datetime)
        elif name == "tools":
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
    trace: List[Dict] = field(default_factory=list)  # 节点透明度:执行轨迹(意图/RAG/记忆/LLM/工具/skill)


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
        use_llm: bool = True,
    ):
        IntentRecognizer, IntentType, IntentResult = _get_module("intent")
        ResponseGenerator, ResponseContext = _get_module("response")
        KnowledgeManager = _get_module("knowledge")
        ShortTermMemory, LongTermMemory = _get_module("memory")
        UserProfileManager, get_profile_updater, PersonalizedRecommendationEngine = _get_module(
            "profile"
        )

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
        self.user_conversations = self.conversation_store._user_index  # 兼容旧代码
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
                    use_llm=use_llm,
                )
                print("   - LangGraph 模式: 已启用 (实验特性)")
                print(
                    "     ⚠ 注意: LangGraph 分支尚未与 chat_enhanced 功能对等"
                    "(无 LLM 响应、无多轮上下文、缺早返)。生产建议保持 USE_LANGGRAPH=false。"
                )
            except Exception as e:
                print(f"   - LangGraph 模式: 启用失败 ({e})")
                self.use_langgraph = False

        print("绿色低碳智能体初始化完成")
        print(f"   - 知识库: {len(self.knowledge_manager.get_all_documents())} 篇文档")
        print(f"   - RAG 引擎: {'已启用' if self.rag_enabled else '未启用'}")
        print(f"   - LLM 支持: {'已启用' if use_llm else '未启用'}")
        print("   - 个性化推荐: 已启用")
        print(f"   - LangGraph: {'已启用' if self.use_langgraph else '未启用'}")

    def _init_rag_engine(self, knowledge_base_path: str):
        """初始化 RAG 引擎(统一使用 get_rag_engine 单例,不再自建实例)

        修复:聊天与调度/订阅者共用同一个引擎实例 + 同一 collection,
        否则政策更新重建的是单例,聊天用的实例永不重建。
        调参(collection=green_agent_knowledge、min_similarity=0.05、
        hybrid_search、semantic_weight=0.6、post_filter_threshold=0.005、
        initial_fetch_multiplier=4)统一在 rag_engine.get_rag_engine 工厂默认值里。
        """
        try:
            from rag.rag_engine import get_rag_engine

            self.rag_engine = get_rag_engine()
            if self.rag_engine.is_enabled:
                # 调度器/订阅者可能已初始化同一单例,直接复用,避免重复初始化
                self.rag_enabled = True
                print("[OK] RAG 引擎已就绪(单例)")
                return
            if self.rag_engine.initialize(knowledge_base_path):
                self.rag_enabled = True
                print("[OK] RAG 引擎初始化成功(单例)")
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
            "progress_percentage": int((current_step / len(questions)) * 100) if questions else 100,
        }

    def process_onboarding_answer(self, user_id: str, step: int, answer: Any) -> Dict[str, Any]:
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
            self.profile_manager.update_eco_profile(
                user_id, {"knowledge_level": level_map.get(answer, "intermediate")}
            )
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
                "message": "太好了！你已经完成了初始设置。现在让我们开始吧！",
            }

        return {
            "success": True,
            "completed": False,
            "next_step": next_step,
            "next_question": next_question,
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
            "welcome_message": self._generate_onboarding_welcome(),
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
                "knowledge_level": self._estimate_knowledge_level(user_info)
                if user_info
                else "intermediate",
                "behavior_stage": "意向",
                "awareness_level": user_info.get("eco_awareness", "medium")
                if user_info
                else "medium",
                "primary_interests": user_info.get("interests", []) if user_info else [],
                "action_history": [],
                "completed_actions": [],
            },
            "communication_style": self._detect_communication_style(user_info)
            if user_info
            else "balanced",
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
            if isinstance(age_str, str) and "-" in age_str:
                age = int(age_str.split("-")[0])
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

    def apply_onboarding_to_profile(self, user_id: str, user_info: Dict = None) -> str:
        """已登录用户完成引导:把 user_info 合并进其账号关联画像,而非新建游离的独立 user_id。

        解决"引导创建的 user_id_U 与登录账号的 user_id_L 不一致 → 画像页空白"的问题。
        返回实际写入的 user_id(即账号关联 id)。
        """
        user_info = user_info or {}
        # 1) 基础信息
        self.profile_manager.update_basic_info(
            user_id,
            {
                "age_group": user_info.get("age_group"),
                "gender": user_info.get("gender"),
                "region": user_info.get("region"),
                "income_level": user_info.get("income_level"),
                "family_type": user_info.get("family_type"),
            },
        )
        # 2) 环保画像
        eco_updates = {}
        if user_info.get("eco_awareness") or user_info.get("eco_knowledge"):
            eco_updates["knowledge_level"] = self._estimate_knowledge_level(user_info)
            eco_updates["awareness_level"] = user_info.get("eco_awareness", "medium")
        interests = list(user_info.get("interests", []) or [])
        if interests:
            existing = (
                self.profile_manager.get_profile(user_id)
                .get("eco_profile", {})
                .get("primary_interests", [])
                or []
            )
            eco_updates["primary_interests"] = list(set(existing) | set(interests))
        if eco_updates:
            self.profile_manager.update_eco_profile(user_id, eco_updates)
        # 3) 沟通风格 + 完成标记
        self.profile_manager.update_profile(
            user_id,
            {
                "communication_style": self._detect_communication_style(user_info),
                "onboarding_completed": True,
                "onboarding_step": 8,
            },
        )
        # 4) 长期偏好
        if interests:
            try:
                self.long_term_memory.update_preference(
                    user_id, "topics", interests, confidence=0.9
                )
            except Exception:
                pass
        return user_id

    # ========== 个性化聊天 (RAG + 推荐) ==========

    def chat_enhanced(
        self, user_id: str, message: str, conversation_id: str = None, trace=None, user_city=None,
        user_location=None,
    ) -> EnhancedAgentResponse:
        """增强版聊天 - 使用 RAG 和个性化推荐

        user_city: 调用方解析的用户城市(实时定位/画像),供出行规划 geocode 消歧。
        user_location: 用户真实定位 dict(含 city/lat/lng/source),供出行规划精确消歧/起点。
        """
        # 由 user_location 推导城市(若未显式给 user_city)
        if user_location and not user_city:
            user_city = (user_location or {}).get("city", "") or ""
        from agent.trace import Trace

        if trace is None:
            trace = Trace()

        # 快捷指令:以 / 开头的命令直接路由到对应 skill/工具/处理器(对标 Claude Code / DSH 的 /command)
        if message.strip().startswith("/"):
            command, _, arguments = message.strip().partition(" ")
            if command == "/energy":
                message = "家庭节能规划 " + arguments
            else:
                return self._handle_command(user_id, message, conversation_id, trace=trace)

        from agent.understanding import DialogueStateStore, DemandInterpreter, advance_state
        from agent.intent import IntentType
        from utils.helpers import get_current_datetime
        import logging as _logging_p14
        import os as _os_p14
        _log_p14 = _logging_p14.getLogger(__name__)

        # P14 修复: 检查是否有真实可用的 LLM(非 mock)
        # 没有 API key 时不应假装使用 LLM,直接告诉用户"AI 推理暂不可用"
        # 修正 env 名(与 llm/client.py 实际读取的 key 名一致)+ 用 config 的占位符判定(含 sk-xxx)
        from config import _is_placeholder as _is_ph
        _llm_truly_available = False
        _api_key_envs = [
            "OPENAI_API_KEY", "ZHIPU_API_KEY", "BAIDU_API_KEY",
            "ALI_API_KEY", "MINIMAX_API_KEY", "DEEPSEEK_API_KEY",
        ]
        for _ek in _api_key_envs:
            _v = _os_p14.environ.get(_ek, "")
            if _v and not _is_ph(_v):
                _llm_truly_available = True
                break

        conversation_id = self._manage_conversation(user_id, conversation_id)
        conversation = self.active_conversations[conversation_id]
        store = getattr(self, "_dialogue_store", None)
        if store is None:
            store = self._dialogue_store = DialogueStateStore()
        state = store.load(user_id, conversation_id)
        manager = getattr(self, "profile_manager", None)
        main_profile = manager.get_profile(user_id, refresh=True) if manager else {}
        # Pass only relevant non-identifying fields, not the entire profile/wiki.
        summary = {"family_type": (main_profile.get("basic_info") or {}).get("family_type"),
                   "priority": ((main_profile.get("behavior_profile") or {}).get("home_energy_usage") or {}).get("priority")}
        hints = self._parse_household_hints(message)

        # ====== P14: profile_mining 在意图分类前触发(任何含画像线索的消息都挖掘) ======
        # 这样用户分享"我家在北京,3 口人"时,即使被分类为 inform 也能被捕捉到
        global_profile_mining_meta: dict = {"skipped": True}
        try:
            from agent.skills.profile_mining_skill import ProfileMiningSkill
            from agent.skills.skill import SkillContext
            mining_skill = ProfileMiningSkill()
            mining_result = mining_skill.execute(SkillContext(
                user_id=user_id, message=message,
            ))
            if mining_result.success and mining_result.data:
                d = mining_result.data
                global_profile_mining_meta = {
                    "skipped": False,
                    "extracted_count": d.get("extracted_count", 0),
                    "written_to_graph": d.get("written_to_graph", 0),
                    "obsidian_paths": d.get("obsidian_paths", []),
                    "violations": d.get("violations", []),
                    "reasoning": d.get("reasoning", ""),
                }
                _log.info("[chat_enhanced] profile_mining extracted=%d, written=%d",
                          d.get("extracted_count", 0), d.get("written_to_graph", 0))
        except Exception as e:
            _log.warning("[chat_enhanced] profile_mining 集成失败(降级): %s", e)

        interpreter = DemandInterpreter(self.intent_recognizer, getattr(self, "_understanding_model", None))
        demand = interpreter.understand(message, state, summary, hints)
        intent_result = demand.intent_result()
        state = advance_state(state, demand, message)
        store.save(user_id, conversation_id, state)
        conversation.last_domain = intent_result.intent.value
        trace.add("intent", "理解本轮需求", {"domain": demand.domain, "act": demand.act,
                  "relation": demand.relation, "source": demand.source})
        if demand.act == "cancel" or demand.act == "clarify":
            # A domain label must never override cancellation or a clarification.
            reply = "已取消当前任务。你可以开始新的话题。" if demand.act == "cancel" else demand.question or "请补充一下你希望我做什么。"
            state["recent"] = (state.get("recent", []) + [{"role": "assistant", "content": reply}])[-6:]
            store.save(user_id, conversation_id, state)
            return EnhancedAgentResponse(message=reply,
                conversation_id=conversation_id, intent=intent_result.intent.value,
                timestamp=get_current_datetime(),
                personalization_info={"understanding": intent_result.context["understanding"],
                                     "profile_mining": global_profile_mining_meta},
                trace=trace.to_dict())
        if (intent_result.intent == IntentType.ENERGY_PLANNING
                or (demand.domain == "energy" and demand.act in ("plan", "update", "advise"))):
            effective_message = demand.message
            # 强制把 intent 设回 ENERGY_PLANNING(避免下游看到 UNKNOWN)
            if intent_result.intent != IntentType.ENERGY_PLANNING:
                try:
                    intent_result.intent = IntentType.ENERGY_PLANNING
                except Exception:
                    pass
            if state.get("expected_slot") == "family_size":
                import re
                if re.fullmatch(r"[一二三四五六七八九十两\d]+(?:个人|个|人|口)?[。\s]*", effective_message):
                    effective_message = re.sub(r"[个人口。\s]+$", "", effective_message) + "人"
            # P14: 把全局 profile_mining_meta + llm 状态传给 _handle_energy_planning(供 HTML 报告用)
            response = self._handle_energy_planning(
                user_id, effective_message, conversation_id, intent_result,
                profile_mining_meta=global_profile_mining_meta,
                llm_truly_available=_llm_truly_available,
            )
            from agent.energy.household_store import load_profile
            household = load_profile(user_id)
            state["expected_slot"] = "family_size" if not household or not household.family_size else "appliances" if not household.appliances else None
            state["recent"] = (state.get("recent", []) + [{"role": "assistant", "content": response.message[:1500]}])[-6:]
            if state.get("pending_tasks"):
                response.message += "\n你还有出行需求待处理，可以回复‘继续出行’。"
            store.save(user_id, conversation_id, state)
            response.trace = trace.to_dict()
            return response
        message = demand.message
        # Explanations and concrete planning share the same routing in all engines.
        # ReAct 模式: LLM 自主选工具(USE_REACT=true 时),每步调用全程写进 trace,透明
        if demand.act in ("advise", "greet") and os.environ.get("USE_REACT", "false").lower() in ("1", "true", "yes", "on"):
            react_response = self.chat_react(
                user_id, message, conversation_id, trace=trace, user_city=user_city,
                user_location=user_location,
            )
            state["recent"] = (state.get("recent", []) + [{"role": "assistant", "content": react_response.message[:1500]}])[-6:]
            store.save(user_id, conversation_id, state)
            return react_response

        if demand.act in ("advise", "greet") and self.use_langgraph and self.langgraph_agent:
            langgraph_response = self.langgraph_agent.chat(user_id, message, conversation_id)
            state["recent"] = (state.get("recent", []) + [{"role": "assistant", "content": langgraph_response.message[:1500]}])[-6:]
            store.save(user_id, conversation_id, state)
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
                rag_context=langgraph_response.metadata.get("rag_context", ""),
                tool_result=getattr(langgraph_response, "tool_result", None),  # P6.S.23
                trace=trace.to_dict(),
            )

        IntentRecognizer, IntentType, IntentResult = _get_module("intent")
        ResponseGenerator, ResponseContext = _get_module("response")
        get_current_datetime = _get_module("helpers")[1]

        conversation.last_updated = get_current_datetime()
        user_profile = main_profile

        # P6.S.20: 记录意图分布 + 活跃 user
        try:
            from observability.metrics import get_metrics_collector

            get_metrics_collector().record_intent(intent_result.intent.value)
            if user_id and user_id != "anonymous":
                get_metrics_collector().record_user_activity(user_id)
        except Exception:
            pass

        # P6.S.10: 出行规划早返 — 直接走工具路径(对齐 chat() line 992-996 行为)
        # 不进 RAG,避免 LLM 拿到无关"出行"知识文档后瞎答
        if intent_result.intent == IntentType.TRAVEL_PLANNING:
            travel_resp = self._handle_travel_planning(
                user_id,
                message,
                conversation_id,
                intent_result,
                user_city=user_city,
                user_location=user_location,
            )
            state["recent"] = (state.get("recent", []) + [{"role": "assistant", "content": travel_resp.message[:1500]}])[-6:]
            if state.get("pending_tasks"):
                travel_resp.message += "\n你还有家庭节能需求待处理，可以回复‘继续家庭节能’。"
            store.save(user_id, conversation_id, state)
            return EnhancedAgentResponse(
                message=travel_resp.message,
                conversation_id=travel_resp.conversation_id,
                intent="travel_planning",
                suggestions=travel_resp.suggestions or [],
                knowledge_refs=[],
                timestamp=travel_resp.timestamp,
                rag_context="",
                personalization_info={},
                recommendations=[],
                profile_updates={},
                tool_result=travel_resp.tool_result,  # P6.S.23: 透出 tool_result 给前端渲染地图
                trace=trace.to_dict(),
            )

        # P6.S.23: 位置查询早返 — 调 best_location() 直接答 city,不让 LLM 瞎说
        if intent_result.intent == IntentType.LOCATION_QUERY:
            return self._handle_location_query(
                user_id, message, conversation_id
            )

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

        if (
            not user_profile.get("onboarding_completed", False)
            and conversation.turn_count > 3
            and not has_api_config
        ):
            return EnhancedAgentResponse(
                message="我们还没完成初始设置，这样我无法为你提供最佳服务。让我们先完成设置吧！",
                conversation_id=conversation_id,
                intent="onboarding_reminder",
                timestamp=get_current_datetime(),
            )

        # P6.S.10: 意图门控 — 非知识/咨询类意图跳过 RAG
        NO_RAG_INTENTS = {
            IntentType.GREETING,
            IntentType.QUESTION,
            IntentType.UNKNOWN,
            IntentType.FEEDBACK,
            IntentType.ACTION_REPORT,
            IntentType.SUGGESTION_ACCEPT,
            IntentType.SUGGESTION_REJECT,
        }
        skip_rag = intent_result.intent in NO_RAG_INTENTS

        rag_context = ""
        knowledge_refs = []
        rag_results = []
        if not skip_rag and self.rag_enabled and self.rag_engine:
            try:
                rag_results = self.rag_engine.retrieve(message, top_k=5)
            except Exception as e:
                _logger.warning(f"[GreenAgent] RAG 检索失败(降级为空): {e}")
                rag_results = []
        if rag_results:
            context_parts = []
            for i, r in enumerate(rag_results, 1):
                grade = r.metadata.get("evidence_status", "unverified")
                evidence_rule = {
                    "verified_current": "可用于事实结论",
                    "verified_historical": "可用于对应历史年份，不代表当前年份",
                    "source_linked": "有来源但有效期未核验，具体数值需谨慎",
                    "unverified": "仅作背景线索，不可据此断言具体数值、政策或标准",
                }.get(grade, "仅作背景线索")
                context_parts.append(
                    f"[来源 {i} | 证据级别:{grade} | 使用限制:{evidence_rule}]: {r.get_summary()}"
                )
                ref_source = r.metadata.get("source_url") or r.metadata.get("source", "")
                knowledge_refs.append(
                    f"{ref_source} (证据:{grade}, 相似度:{r.score:.2f})"
                )
            rag_context = "\n\n".join(context_parts)

        trace.add(
            "rag", "检索知识库" if rag_results else "跳过知识库检索",
            {"top_k": 5, "hits": len(rag_results)},
            status="done" if rag_results else "skipped",
        )

        message_analysis = self.dynamic_updater.analyze_message(
            user_id, message, intent_result.intent.value, intent_result.entities
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
                        user_id,
                        cleared,
                    )
            except Exception as e:
                import logging

                logging.getLogger(__name__).warning(
                    "[GreenAgent] QueryCache.invalidate 异常(非致命): %s", e
                )

        self.profile_manager.record_interaction(
            user_id, self._map_intent_to_interaction(intent_result)
        )

        recent_memories = self._get_recent_memories(user_id)
        # P4-B.4: 真正的语义+时间召回,覆盖默认的"最近 3 条"
        try:
            recalled = self._recall_memories(message, user_id, limit=5)
            if recalled:
                # P6.S.18 fix: 之前只塞 60 字符标签,LLM 看不到内容
                # 改成 200 字符 + importance 标注(让 LLM 真正"记得"用户)
                recent_memories = [
                    f"[{m.get('type', 'memory')} | 重要度:{m.get('importance', 0.5):.2f}] {m.get('content', '')[:200]}"
                    for m in recalled
                ]
        except Exception as e:
            import logging

            logging.getLogger(__name__).warning("[GreenAgent] 记忆召回失败: %s", e)

        conversation_history = self._compact_history(
            self.short_term_memory.get_conversation_history(conversation_id)
        )
        trace.add("memory", "召回记忆", {"count": len(recent_memories)})

        personalization_ctx = self.profile_manager.get_personalization_context(user_id)
        strategy = dict(self.profile_manager.get_suggestion_strategy(user_id))
        if demand.act == "explain":
            strategy["focus"] = "解释本轮问题；不启动规划，不把假设或咨询记为用户事实。"

        # P4-D: 合并 strategy 字段到 personalization_ctx,供 LLM prompt 注入
        personalization_ctx = {
            **personalization_ctx,
            "focus": strategy.get("focus"),
            "suggestion_intensity": strategy.get("suggestion_intensity"),
            "action_complexity": strategy.get("action_complexity"),
            "tone": strategy.get("tone"),
            "example_focus": strategy.get("example_focus"),
            # P14: profile_mining 元数据(画像挖掘结果)
            "profile_mining": global_profile_mining_meta,
        }

        recommendations = []
        # 放宽:知识查询 / 一般问题 / 建议 / 问候 都附上推荐,避免新用户拿 0 条推荐(P4-G e2e 修复)
        if intent_result.intent in [
            IntentType.ADVICE_REQUEST,
            IntentType.GREETING,
            IntentType.KNOWLEDGE_QUERY,
            IntentType.QUESTION,
        ] and demand.act != "explain":
            recs = self.recommendation_engine.generate_recommendations(user_profile, count=2)
            recommendations = [
                {
                    "action": r.action,
                    "category": r.category,
                    "reason": r.reason,
                    "carbon_saving": r.estimated_carbon_saving,
                    "examples": r.examples,
                }
                for r in recs
            ]
        trace.add("recommendations", "生成个性化推荐", {"count": len(recommendations)})

        # 将 RAG 检索结果转换为 ResponseContext 格式
        retrieved_knowledge = []
        if rag_results:
            for r in rag_results:
                retrieved_knowledge.append(
                    {
                        "title": r.metadata.get("title", ""),
                        "content": r.content,
                        "source": r.metadata.get("source", ""),
                        "source_url": r.metadata.get("source_url", ""),
                        "category": r.metadata.get("category", ""),
                        "evidence_status": r.metadata.get("evidence_status", "unverified"),
                    }
                )

        context = ResponseContext(
            user_profile=user_profile,
            conversation_history=conversation_history,
            retrieved_knowledge=retrieved_knowledge,
            recent_memories=recent_memories,
            intent_type=intent_result.suggested_response_type,
        )

        # P6.S.11: LLM_MOCK 状态变化时清缓存,避免 mock 响应被锁住
        try:
            import logging

            prev = getattr(self, "_last_llm_mock_state", None)
            cur = os.getenv("LLM_MOCK", "auto").strip().lower() in ("true", "1", "yes", "on")
            if prev is not None and prev != cur:
                from agent.cache import get_query_cache

                cleared = get_query_cache().invalidate(user_id)
                if cleared > 0:
                    logging.getLogger(__name__).info(
                        "[GreenAgent] LLM_MOCK 状态变更 (%s→%s),清 user=%s 缓存 cleared=%d",
                        prev,
                        cur,
                        user_id,
                        cleared,
                    )
            self._last_llm_mock_state = cur
        except Exception as e:
            import logging

            logging.getLogger(__name__).debug("[GreenAgent] LLM_MOCK 状态检测异常(非致命): %s", e)

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
                message, context, intent_result, rag_context, personalization_ctx, strategy,
                trace=trace,
            )
            # 写缓存(失败不致命)
            try:
                from agent.cache import get_query_cache

                get_query_cache().set(
                    message,
                    user_id,
                    user_profile,
                    response_data["message"],
                    response_data.get("suggestions", []),
                )
            except Exception as e:
                import logging

                logging.getLogger(__name__).warning(
                    "[GreenAgent] QueryCache.set 异常(非致命): %s", e
                )

        state["recent"] = (state.get("recent", []) + [{"role": "assistant", "content": response_data["message"][:1500]}])[-6:]
        store.save(user_id, conversation_id, state)
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
                    user_id,
                    conversation_id,
                    consolidated,
                )
        except Exception as e:
            import logging

            logging.getLogger(__name__).warning("[GreenAgent] 记忆整合失败(非致命): %s", e)

        trace.add(
            "done", "生成回答",
            {"cached": bool(cached_response), "chars": len(response_data["message"])},
        )

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
            recommendations=recommendations,
            trace=trace.to_dict(),
        )

    def _handle_command(
        self, user_id: str, message: str, conversation_id: str, trace=None
    ) -> "EnhancedAgentResponse":
        """快捷指令解析 — 对标 Claude Code / DSH 的 /command。

        支持:
          /help          列出命令
          /energy        家庭节能规划(复用 _handle_energy_planning)
          /profile       查看当前用户画像摘要
          /skills        列出已注册技能
          /tools         列出已注册工具
          /tool <name> [ JSON]  直接调用某个工具(走 ToolRegistry / dispatch)
          /skill <name>  直接调用某个技能(走 SkillExecutor)
        调用全程记录进 trace,前端"🔍 思考过程"可见。
        """
        from utils.helpers import get_current_datetime
        from agent.trace import Trace

        if trace is None:
            trace = Trace()
        parts = (message or "").strip().split()
        cmd = (parts[0].lstrip("/") or "help").lower() if parts else "help"
        args = parts[1:]
        trace.add("command", "识别快捷指令", {"cmd": "/" + cmd, "args": args}, status="done")

        def _resp(msg, suggestions=None, trace_extra=None):
            return EnhancedAgentResponse(
                message=msg,
                conversation_id=conversation_id,
                intent="command",
                suggestions=suggestions or [],
                timestamp=get_current_datetime(),
                trace=trace.to_dict(),
            )

        # /help
        if cmd == "help":
            trace.add("command", "返回命令帮助", status="done")
            return _resp(
                self._command_help(),
                ["/energy", "/skills", "/tools", "/tool daily_eco_tip", "/profile"],
            )

        # /energy → 家庭节能规划
        if cmd == "energy":
            trace.add("command", "调用节能规划(skill=energy_planning)", status="running")
            return self._handle_energy_planning(
                user_id, (" ".join(args) if args else "家庭节能规划"), conversation_id, None
            )

        # /profile → 画像摘要
        if cmd == "profile":
            try:
                profile = self.profile_manager.get_profile(user_id)
                basic = profile.get("basic_info", {})
                eco = profile.get("eco_profile", {})
                lines = [
                    "👤 你的画像摘要：",
                    f"- 地区: {basic.get('region') or '未填'}",
                    f"- 年龄段: {basic.get('age_group') or '未填'}",
                    f"- 收入: {basic.get('income_level') or '未填'}",
                    f"- 家庭: {basic.get('family_type') or '未填'}",
                    f"- 行为阶段: {eco.get('behavior_stage') or '意向'}",
                    f"- 关注领域: {', '.join(eco.get('primary_interests') or []) or '未填'}",
                    f"- 已完成引导: {'是' if profile.get('onboarding_completed') else '否'}",
                ]
                trace.add("command", "读取用户画像", status="done")
                return _resp("\n".join(lines), ["/energy", "帮我做家庭节能规划"])
            except Exception as e:
                import logging

                logging.getLogger(__name__).warning("[command] profile 失败: %s", e)
                return _resp(f"读取画像失败: {e}", ["/help"])

        # /skills → 列出已注册技能(含中文名 + 用途 + 类别)
        if cmd == "skills":
            try:
                from agent.skills import get_skill_executor

                exec_ = get_skill_executor()
                names = exec_.list_all()
                lines = ["🎯 已注册技能:"]
                for n in names:
                    sk = exec_.get(n)
                    name_cn = getattr(sk, "name_cn", "") or ""
                    desc = getattr(sk, "description", "") or ""
                    cat = getattr(sk, "category", "") or ""
                    lines.append(
                        f"· {n}{'（' + name_cn + '）' if name_cn else ''} — {desc}"
                        + (f"  [{cat}]" if cat else "")
                    )
                lines.append("\n（/skill <name> 查看详情并调用）")
                trace.add("command", "列出已注册技能", {"count": len(names)}, status="done")
                return _resp("\n".join(lines), ["/skill energy_planning", "/skills"])
            except Exception as e:
                return _resp(f"列技能失败: {e}", ["/help"])

        # /tools → 列出已注册工具
        if cmd == "tools":
            try:
                from agent.tools import get_registry

                names = get_registry().list_all()
                trace.add("command", "列出已注册工具", {"count": len(names)}, status="done")
                return _resp(
                    "🔧 已注册工具:\n" + "\n".join(f"· {n}" for n in names)
                    + "\n\n（可用 /tool <name> 调用）",
                    ["/tool daily_eco_tip"],
                )
            except Exception as e:
                return _resp(f"列工具失败: {e}", ["/help"])

        # /tool <name> → 直接调用某个工具
        if cmd == "tool":
            name = args[0] if args else ""
            tool_args = " ".join(args[1:]) if len(args) > 1 else "{}"
            if not name:
                return _resp("用法: /tool <工具名> [JSON参数]", ["/tools", "/help"])
            try:
                from agent.tool_dispatcher import dispatch_tool_call

                trace.add("command", "调用工具", {"tool": name}, status="running")
                result = dispatch_tool_call(name, tool_args)
                out = result.get("output") if result.get("success") else str(result.get("error"))
                trace.add("command", "工具执行结果", {"success": result.get("success")}, status="done")
                return _resp(f"🔧 /tool {name} 结果:\n\n{out}", ["/tools", "/energy"])
            except Exception as e:
                import logging

                logging.getLogger(__name__).warning("[command] tool 调用失败: %s", e)
                return _resp(f"工具调用失败: {e}", ["/help"])

        # /skill <name> → 直接调用某个技能
        if cmd == "skill":
            name = args[0] if args else ""
            if not name:
                return _resp("用法: /skill <技能名>", ["/skills", "/help"])
            try:
                from agent.skills import get_skill_executor

                exec_ = get_skill_executor()
                skill = exec_.get(name)
                if not skill:
                    return _resp(f"未找到技能: {name}。可用: {', '.join(exec_.list_all())}", ["/skills"])
                trace.add("command", "调用技能", {"skill": name}, status="running")
                from agent.skills.skill import SkillContext

                ctx = SkillContext(user_id=user_id, metadata={"operation": "plan"})
                result = skill.execute(ctx)
                out = result.data if result.success else str(result.error)
                trace.add("command", "技能执行结果", {"success": result.success}, status="done")
                return _resp(f"🎯 /skill {name} 结果:\n\n{out}", ["/energy", "/skills"])
            except Exception as e:
                import logging

                logging.getLogger(__name__).warning("[command] skill 调用失败: %s", e)
                return _resp(f"技能调用失败: {e}", ["/help"])

        # 未知命令
        return _resp(f"未知命令 /{cmd}。输入 /help 查看可用命令。", ["/help"])

    def _command_help(self) -> str:
        return (
            "📋 可用快捷指令:\n"
            "/help                    查看命令列表\n"
            "/energy                  家庭节能规划(节水/节电/节气)\n"
            "/profile                 查看我的画像摘要\n"
            "/skills                  列出已注册技能\n"
            "/tools                   列出已注册工具\n"
            "/tool <名字> [JSON]      直接调用某个工具\n"
            "/skill <名字>            直接调用某个技能\n\n"
            "也可以直接用自然语言聊天。"
        )

    def chat_react(
        self, user_id: str, message: str, conversation_id: str = None, trace=None, user_city=None,
        user_location=None,
    ) -> "EnhancedAgentResponse":
        """ReAct 主聊天:LLM 根据工具列表自主选择调用哪个工具,每步透明(写进 trace)。

        仅当 USE_REACT=true 时由 chat_enhanced 调用;否则仍走确定性管线。
        trace 由 SSE 实时流传入(携带 on_step),使每步都实时推给前端。
        user_city/user_location: 用户真实城市/定位(实时坐标),经 ctx 注入工具(如 travel_planning)。
        """
        from agent.trace import Trace
        from utils.helpers import get_current_datetime
        from llm import get_llm_client
        from agent.tool_dispatcher import run_react_loop
        from observability.trace import new_trace_id

        if trace is None:
            trace = Trace()
        trace.add("react", "进入 ReAct(LLM 自主选工具)模式", status="done")

        # 解析用户城市:优先调用方传入 user_city,其次 user_location.city,再画像/默认
        city = (user_city or "").strip()
        if not city and user_location:
            city = (user_location.get("city") or "").strip()
        if not city:
            try:
                from utils.geolocate import best_location
                geo = best_location(handler=None, user_id=user_id)
                if geo and geo.city:
                    city = geo.city
            except Exception:
                city = ""
        tool_ctx = {"user_id": user_id, "city": city, "location": user_location or {}}

        profile = self.profile_manager.get_profile(user_id)

        # 知识库上下文(尽力而为)
        rag_context = ""
        try:
            if self.rag_enabled and self.rag_engine:
                rags = self.rag_engine.retrieve(message, top_k=5)
                if rags:
                    rag_context = "\n\n".join(
                        f"[来源 {i}]: {r.get_summary()}" for i, r in enumerate(rags, 1)
                    )
                    trace.add("rag", "检索知识库", {"hits": len(rags)})
                else:
                    trace.add("rag", "知识库无命中", status="skipped")
            else:
                trace.add("rag", "跳过知识库检索", status="skipped")
        except Exception as e:
            import logging

            logging.getLogger(__name__).warning("[react] RAG 检索失败: %s", e)
            trace.add("rag", "知识库检索失败", status="skipped")

        react_instruction = self._react_system_prompt()
        messages = [
            {"role": "system", "content": react_instruction},
        ]
        # 用户画像上下文(让 LLM 知道"这是谁")
        try:
            basic = profile.get("basic_info", {})
            eco = profile.get("eco_profile", {})
            prof_lines = [
                f"用户地区: {basic.get('region') or '未知'}",
                f"年龄段: {basic.get('age_group') or '未知'}",
                f"行为阶段: {eco.get('behavior_stage') or '意向'}",
                f"关注领域: {', '.join(eco.get('primary_interests') or []) or '无'}",
            ]
            messages.append({"role": "system", "content": "[用户画像]\n" + "\n".join(prof_lines)})
        except Exception:
            pass
        # 身份上下文:让 LLM 知道当前 user_id,调用需要 user_id 的工具时直接填入,不要向用户索要
        messages.append(
            {
                "role": "system",
                "content": (
                    f"[身份上下文] 当前用户 user_id = {user_id}。"
                    "凡工具参数要求 user_id 的,直接填这个值,不要向用户询问。"
                ),
            }
        )
        # 位置上下文:让 LLM 知道用户当前定位(浏览器/IP/画像解析),回答"我当前位置/出发地"或出行时直接用
        try:
            loc = user_location or {}
            loc_parts = []
            if loc.get("detail"):
                loc_parts.append(f"具体位置={loc.get('detail')}")
            if loc.get("city"):
                loc_parts.append(f"城市={loc.get('city')}")
            if loc.get("lat") and loc.get("lng"):
                loc_parts.append(f"坐标=({float(loc['lng']):.4f},{float(loc['lat']):.4f})")
            if loc.get("source"):
                loc_parts.append(f"来源={loc.get('source')}")
            if loc_parts:
                messages.append({
                    "role": "system",
                    "content": ("[位置上下文] 当前用户定位: " + "、".join(loc_parts)
                                + "。若用户问「我当前位置/我在哪/出发地」,直接用这个城市回答;"
                                  "出行时 origin 可填'当前位置',系统用该坐标。"),
                })
        except Exception:
            pass
        if rag_context:
            messages.append({"role": "system", "content": f"[参考知识]\n{rag_context}"})
        messages.append({"role": "user", "content": message})

        llm = get_llm_client()
        from agent.tools import get_registry

        tool_names = get_registry().list_all()
        mcp_tool_count = sum(1 for n in tool_names if str(n).startswith("mcp_"))
        trace.add(
            "llm", "LLM 自主选择工具",
            {"tools": len(tool_names), "mcp_tools": mcp_tool_count},
            status="done",
        )

        result = run_react_loop(
            messages,
            llm,
            tool_names=tool_names,
            max_steps=4,
            trace_id=new_trace_id(),
            ctx=tool_ctx,
            reflect=True,
        )

        # 回填 travel_planning 工具输出为 tool_result(前端出行地图需要 origin/dest/routes/坐标)
        travel_tool_result = None

        # 展示模型链式推理(DeepSeek R1 reasoner 的 reasoning_content)
        for i, raz in enumerate(result.get("reasonings", []) or []):
            if isinstance(raz, str) and raz.strip():
                trace.add("llm", f"模型推理 #{i+1}", raz[:600], status="done")

        # 每步工具调用写进 trace(透明,含中间输出)
        for tc in result.get("tool_calls", []):
            out = tc.get("output")
            # 取最后一次成功的 travel_planning 结构化数据作为 tool_result,供前端渲染地图
            if tc.get("name") == "travel_planning" and tc.get("success") and isinstance(out, dict):
                travel_tool_result = out
            # 构造 trace 展示串:出行工具显示"数据来源 + 线路",而非 150 字截断原始 dict
            if tc.get("name") == "travel_planning" and tc.get("success") and isinstance(out, dict):
                out_str = self._summarize_travel_output(out)
            elif isinstance(out, str):
                out_str = out[:150]
            elif isinstance(out, dict):
                out_str = str(out)[:150]
            else:
                out_str = ""
            trace.add(
                "tool", f"调用工具 {tc.get('name', '?')}",
                {"success": tc.get("success"), "elapsed_ms": tc.get("elapsed_ms"),
                 "result": out_str},
                status="done" if tc.get("success") else "error",
            )
        trace.add(
            "react", "ReAct 循环结束",
            {
                "steps": result.get("steps", 0),
                "tool_calls": len(result.get("tool_calls", [])),
                "success": result.get("success"),
            },
            status="done" if result.get("success") else "error",
        )

        return EnhancedAgentResponse(
            message=result.get("content", "（ReAct 返回为空）"),
            conversation_id=conversation_id,
            intent="react",
            suggestions=[],
            timestamp=get_current_datetime(),
            tool_result=travel_tool_result,
            trace=trace.to_dict(),
        )

    @staticmethod
    def _summarize_travel_output(out: dict) -> str:
        """把 travel_planning 工具输出浓缩成 trace 可读串:数据来源 + 各线路摘要。"""
        src = out.get("source", "高德地图API")
        routes = out.get("routes", []) or []
        lines = []
        for r in routes[:4]:
            t = r.get("type", "?")
            ln = r.get("line", "")
            km = r.get("distance_km", "?")
            lines.append(f"{t}:{ln}({km}km)")
        if lines:
            return f"来源[{src}] " + " | ".join(lines)
        return f"来源[{src}]"

    def _react_system_prompt(self) -> str:
        """ReAct 的 system prompt —— 委托统一人格+护栏底座(system_prompt.py),
        再拼接动态工具列表,提高 LLM 调对工具的概率。"""
        from agent.system_prompt import build_react_system_prompt

        tool_lines = []
        try:
            from agent.tools import get_registry

            reg = get_registry()
            for name in reg.list_all():
                inst = reg.get(name)
                desc = getattr(inst, "description", "") or ""
                params = getattr(inst, "parameters", None) or []
                if params:
                    param_str = ", ".join(
                        f"{p.get('name')}({p.get('type')}{'·必填' if p.get('required') else ''})"
                        for p in params
                    )
                else:
                    param_str = "无参数"
                tool_lines.append(f"- **{name}**: {desc}  参数: {param_str}")
        except Exception:
            tool_lines.append("(工具列表读取失败,按描述选择)")

        return build_react_system_prompt(tool_lines)

    def _map_intent_to_interaction(self, intent_result) -> str:
        """映射意图到交互类型"""
        IntentType = _get_module("intent")[1]
        mapping = {
            IntentType.KNOWLEDGE_QUERY: "question",
            IntentType.ADVICE_REQUEST: "question",
            IntentType.ACTION_REPORT: "action",
            IntentType.FEEDBACK: "feedback",
            IntentType.SUGGESTION_ACCEPT: "accept",
            IntentType.SUGGESTION_REJECT: "reject",
        }
        return mapping.get(intent_result.intent, "question")

    def _handle_location_query(
        self, user_id: str, message: str, conversation_id: str
    ) -> "EnhancedAgentResponse":
        """P6.S.23: 位置查询早返 — 调 best_location() 直接答 city,不让 LLM 瞎说

        三层 fallback: 浏览器定位 → IP 反查 → 画像默认 → 失败兜底
        """
        from utils.geolocate import best_location

        get_current_datetime = _get_module("helpers")[1]

        try:
            geo = best_location(handler=self, user_id=user_id)
        except Exception as e:
            import logging

            logging.getLogger(__name__).warning("[LocationQuery] best_location 失败: %s", e)
            geo = None

        if geo is None:
            msg = (
                "📍 我目前**没有拿到你的位置信息**。\n\n"
                "可以试试以下方式:\n"
                "1. 在浏览器顶部的位置权限弹窗里点「允许」,我就能拿到精确位置\n"
                "2. 在聊天里直接告诉我你的城市(如「我在上海」),我会记住\n"
                "3. 完成 onboarding 时填写所在城市,作为默认 fallback"
            )
            location_dict = {"source": "none", "city": "", "region": "", "country": "中国"}
        else:
            city = geo.city or "未知城市"
            region = geo.region or ""
            source = geo.source
            source_label = {
                "browser": "浏览器授权定位",
                "ip": "IP 反查",
                "profile": "画像默认",
                "none": "无定位数据",
            }.get(source, source)
            region_suffix = f"({region})" if region and region != city else ""
            msg = (
                f"📍 你现在在 **{city}**{region_suffix}\n\n"
                f"定位来源: {source_label}"
                + (f" · 精度: {geo.accuracy or '城市级'}" if getattr(geo, "accuracy", None) else "")
            )
            location_dict = geo.to_dict() if hasattr(geo, "to_dict") else {"city": city, "region": region, "source": source}

        # P6.S.23: 即便没拿到 location,也要把意图正确写回对话,避免循环
        try:
            self._save_conversation(conversation_id, user_id, message, msg)
        except Exception:
            pass

        return EnhancedAgentResponse(
            message=msg,
            conversation_id=conversation_id,
            intent="location_query",
            suggestions=[
                f"{location_dict.get('city') or '你所在城市'} 的低碳出行建议",
                "附近的新能源补贴",
                "本地的最新环保政策",
            ],
            knowledge_refs=[],
            memory_hints=[],
            profile_updates={},
            timestamp=get_current_datetime(),
            rag_context="",
            personalization_info={"location": location_dict},
            recommendations=[],
            tool_result={"location": location_dict},
        )

    def _handle_energy_planning(
        self, user_id: str, message: str, conversation_id: str, intent_result,
        profile_mining_meta: Optional[dict] = None,
        llm_truly_available: bool = False,
    ) -> "EnhancedAgentResponse":
        """P12: 家庭节能规划 — 在聊天里识别并生成节水/节电/节气方案。

        流程:
          1. 读取最新主画像，并合并已有家庭记录;
          2. 从本次消息抽取线索(city/人数/费用/电器)并合并;
          3. 关键信息缺失 → 反问收集(下轮继续补);
          4. 足够 → EnergyPlanner 生成方案 + 今日卡,以聊天回复 + 推荐卡片呈现。
        """
        from utils.helpers import get_current_datetime
        from agent.energy.models import HouseholdProfile
        from agent.energy.household_store import load_profile, save_profile
        from agent.energy.planner import EnergyPlanner
        from agent.trace import Trace

        trace = Trace()
        trace.add("energy_planning", "识别为家庭节能规划", status="running")

        from agent.energy.household_store import save_plan_variant
        from agent.energy.weekly import WeeklyEnergy
        from agent.energy.personalization import resolve_profile, remember_confirmed, describe_basis
        profile, profile_sources = resolve_profile(user_id, self.profile_manager.get_profile(user_id, refresh=True), load_profile(user_id))
        hints = self._parse_household_hints(message)
        profile = self._merge_household_hints(profile, hints)
        profile_sources.update({key: "本轮对话明确提供" for key in hints if key != "removed_appliances"})
        profile.intake_pending = not bool(profile.family_size and profile.appliances)
        profile.excluded_actions = list(set(profile.excluded_actions or []) | set(WeeklyEnergy().exclusions(user_id)))
        from agent.energy.delegation import get_delegation_level
        can_save = get_delegation_level(user_id) != 3
        planner = EnergyPlanner()
        plan = planner.generate_plan(profile)
        profile_saved = False

        # ====== P14: profile_mining 在 chat_enhanced 顶层已跑过;此处复用结果 ======
        # 由 caller 通过 profile_mining_meta 注入;若没注入(直接调本函数)则为空
        if profile_mining_meta is None:
            profile_mining_meta = {"skipped": True}

        # 如果 mining 刚写了图谱,刷新 profile 让 plan 用新数据
        if profile_mining_meta.get("written_to_graph", 0) > 0 and not profile_mining_meta.get("skipped", False):
            try:
                profile, profile_sources = resolve_profile(
                    user_id,
                    self.profile_manager.get_profile(user_id, refresh=True),
                    load_profile(user_id),
                )
                # 重 resolve 会丢本轮的 hints,需重新合并(否则 family_size 等又回到旧值)
                profile = self._merge_household_hints(profile, hints)
                profile_sources.update({key: "本轮对话明确提供" for key in hints if key != "removed_appliances"})
                profile.intake_pending = not bool(profile.family_size and profile.appliances)
                profile.excluded_actions = list(set(profile.excluded_actions or []) | set(WeeklyEnergy().exclusions(user_id)))
                plan = planner.generate_plan(profile)
                _log.info("[_handle_energy_planning] 用了 mining 刷新的 profile,重生成 plan")
            except Exception as e:
                _log.warning("[_handle_energy_planning] 刷新 profile 失败: %s", e)

        if can_save and "GUARD_EXTREME_VALUES" not in (plan.warning or ""):
            # 保留用户的委托级别,避免 save_profile 用默认值 1 覆盖 DB 里的 level(0/2)
            profile.delegation_level = get_delegation_level(user_id)
            profile_saved = remember_confirmed(self.profile_manager, user_id, profile, hints)
            save_profile(user_id, profile)
        if plan.blocked:
            missing = []
            if not profile.family_size: missing.append("家里几个人？")
            if not profile.appliances: missing.append("有哪些主要设备？例如冰箱、电热水器或燃气灶。")
            msg = "先了解一点你家的情况：" + " ".join(missing) if missing else "请检查提供的信息：" + str(plan.warning)
            return EnhancedAgentResponse(message=msg, conversation_id=conversation_id,
                intent="energy_planning", timestamp=get_current_datetime(),
                suggestions=["家里3人，有冰箱和电热水器，不用燃气"], recommendations=[],
                rag_context="", personalization_info={"missing_fields": missing}, knowledge_refs=[], profile_updates={})
        plan.status = "draft"
        saved = save_plan_variant(user_id, plan, status="draft") if can_save else False
        card = planner.generate_today_card(plan)

        # ====== P13 Step 6: 集成 LLM 推理层(解释 + 反问,数字仍走模板) ======
        llm_explanation = ""
        llm_follow_up: list = []
        llm_reasoner_meta: dict = {}

        # P14 修复: 若无真实 LLM,直接告诉用户"AI 推理暂不可用",不假装
        if not llm_truly_available:
            llm_reasoner_meta = {
                "llm_used": False,
                "llm_real": False,
                "reason": "未配置任何 LLM API Key(请在 .env 设置 OPENAI_API_KEY / DEEPSEEK_API_KEY / MINIMAX_API_KEY 等)",
                "action_required": "set_api_key",
            }
            _log.info("[handle_energy_planning] 无真实 LLM,跳过推理层")
        else:
            try:
                from agent.context_builder import ContextBuilder, ContextOptions
                from agent.llm_reasoner import make_reasoner, LLMReasonerResult

                # 1) 组装 LLM context
                action_ids = [a.id for a in plan.actions]
                ctx_builder = ContextBuilder()
                built_ctx = ctx_builder.build(user_id, action_ids=action_ids, options=ContextOptions(
                    include_profile=True, include_knowledge=True, include_schema=True,
                    profile_hop=2, knowledge_hop=1, max_chars=8000,
                ))
                ctx_text = built_ctx.render()

                # 2) 初始化真实 LLM 客户端(尊重 API_PROVIDER,默认 deepseek)
                #    不再用 BayesianLLMClient:其 select_model 首次会命中 openai(__SET_ME__ 占位符),
                #    导致真正可用的 DeepSeek 永远轮不到。
                llm_client = None
                try:
                    from llm import get_llm_client
                    llm_client = get_llm_client()
                except Exception as e:
                    _log.warning("[handle_energy_planning] get_llm_client 初始化失败: %s", e)
                    llm_client = None

                if llm_client is None:
                    llm_reasoner_meta = {"llm_used": False, "reason": "客户端初始化失败"}
                else:
                    # 3) 适配器:把 src/llm/client.py 的 chat(messages, **kwargs) → LLMReasoner.chat(system, user)
                    #    超时/重试由 provider 客户端内部的 _call_openai_sdk 统一管(30s + 3 次退避),
                    #    不再额外套 8s 线程壳(会误杀 deepseek-reasoner 等慢推理模型)。
                    from agent.llm_reasoner import LLMClient as _ReasonerLLMClient
                    class _Adapter(_ReasonerLLMClient):
                        def __init__(self, real):
                            self._real = real
                        def chat(self, system: str, user: str) -> str:
                            resp = self._real.chat([
                                {"role": "system", "content": system},
                                {"role": "user", "content": user},
                            ])
                            # 配置/鉴权/网络错误 → 返回空串,让 reasoner 走 template fallback,
                            # 而不是把 "[错误] 调用失败..." 当作个性化解释展示给用户。
                            if getattr(resp, "error", None):
                                _log.warning("[handle_energy_planning] LLM 返回错误: %s", resp.error)
                                return ""
                            if hasattr(resp, "content"):
                                return resp.content or ""
                            return str(resp) if resp else ""

                    reasoner = make_reasoner(llm_client=_Adapter(llm_client))
                    plan_dict = plan.to_dict()
                    reason_result = reasoner.explain(
                        profile_section=built_ctx.profile_section,
                        knowledge_section=built_ctx.knowledge_section,
                        schema_section=built_ctx.schema_section,
                        plan_dict=plan_dict,
                        user_message=message,
                    )

                    # 检测响应是否真的是 LLM 生成(而非 mock 兜底字符串)
                    is_mock_response = (
                        not reason_result.raw_llm_response
                        or "作为绿色低碳助手" in reason_result.raw_llm_response
                        or "我很乐意帮助你" in reason_result.raw_llm_response
                        or len(reason_result.raw_llm_response) < 20
                    )

                    if not reason_result.used_template_fallback and reason_result.explanation and not is_mock_response:
                        llm_explanation = reason_result.explanation
                        llm_follow_up = reason_result.follow_up_questions
                        llm_reasoner_meta = {
                            "llm_used": True,
                            "llm_real": True,
                            "llm_class": llm_client.__class__.__name__,
                            "confidence": reason_result.confidence,
                            "context_chars": built_ctx.char_count(),
                            "context_truncated": built_ctx.meta.get("truncated", False),
                        }
                    else:
                        # LLM 真调用了但响应是 mock 兜底 → 不算真用
                        llm_reasoner_meta = {
                            "llm_used": False,
                            "llm_real": False,
                            "reason": "客户端已连接,但 provider 返回 mock 兜底(可能 API key 无效或网络受限)",
                            "llm_class": llm_client.__class__.__name__,
                        }
            except Exception as e:
                _log.exception("[_handle_energy_planning] LLM 推理失败: %s", e)
                llm_reasoner_meta = {"llm_used": False, "error": str(e)}

        # ====== 组装聊天回复 ======
        lines = [describe_basis(profile)]

        # P13 Step 6: LLM 个性化解释(在方案明细之前)
        if llm_explanation:
            lines.append(f"\n💡 个性化分析(LLM 推理):\n{llm_explanation}")
        elif not llm_truly_available:
            # 没 API key — 显式告知,不假装使用
            lines.append(
                "\n⚠️ **AI 推理功能暂未启用**\n\n"
                "  当前未在 .env 配置任何 LLM API Key(OPENAI_API_KEY / DEEPSEEK_API_KEY / MINIMAX_API_KEY 等)。\n"
                "  本回复由模板生成,不含 LLM 个性化推理。\n"
                "  配置 API Key 重启服务后即可启用 AI 个性化分析。"
            )
        else:
            lines.append("先从一件容易执行的事开始。下面的数字是年度参考或按你提供的参数计算的估算，不是已经省下的费用。")

        lines.append(f"📋 方案 ID: `{plan.id}`（后续标记完成 / 调优都引用这个 ID）")

        # 字段级来源溯源(让用户看到"我从哪儿读到这些信息")
        if profile_sources:
            source_items = list(profile_sources.items())[:6]
            source_lines = [f"  · {k} ← {v}" for k, v in source_items]
            lines.append("📌 画像字段来源:")
            lines.extend(source_lines)

        # 全部 actions(不再只展示前 3 个)
        lines.append(f"\n🎯 完整方案（{len(plan.actions)} 项):")
        for action in plan.actions:
            estimate = (f"约 ¥{action.estimated_saving_cny}/年" if action.estimate_kind != "qualitative" else "暂不估算金额")
            lines.append(f"· [{action.id}] {action.title}：{action.description}（{estimate}）")
            lines.append(f"  依据与假设：{action.estimate_note}")
            lines.append(f"  数据源: {action.source_ref[:120]}{'...' if len(action.source_ref) > 120 else ''}")

        # 今日行动卡(从全部 actions 里挑 3 个最容易执行的)
        if card and card.actions:
            lines.append(f"\n🔥 今日行动卡(从方案挑 {len(card.actions)} 个最容易执行):")
            for a in card.actions:
                lines.append(f"  · [{a.id}] {a.title}（难度 {a.difficulty}/3）")

        # P13 Step 6: LLM 反问(基于 ontology 不变量 + 画像缺失)
        # 仅在 LLM 真用时才显示 LLM 生成的反问;否则从 ontology 自动推
        if llm_follow_up and llm_reasoner_meta.get("llm_used"):
            lines.append(f"\n❓ 我还想了解:")
            for q in llm_follow_up[:3]:
                lines.append(f"  · {q}")
        elif not llm_truly_available:
            # 从 ontology 不变量推必填字段,自动生成反问
            missing_questions = []
            if not profile.city or profile.city == "beijing":
                missing_questions.append("你家在哪个城市?不同城市阶梯电价不同")
            if not profile.appliances:
                missing_questions.append("家里有哪些主要设备?如空调、热水器、冰箱等")
            if not profile.monthly_electricity_bill:
                missing_questions.append("月电费大概多少?可以更精确推荐")
            if missing_questions:
                lines.append(f"\n❓ 补充信息可让方案更精准:")
                for q in missing_questions[:3]:
                    lines.append(f"  · {q}")

        # 本周已排除项(用户说过不想做的)
        if profile.excluded_actions:
            lines.append(f"\n🚫 本周已排除: {', '.join(profile.excluded_actions[:5])}")

        recs = []
        for action in plan.actions[:3]:
            estimate = (f"约 ¥{action.estimated_saving_cny}/年" if action.estimate_kind != "qualitative" else "暂不估算金额")
            recs.append({"action": action.title, "category": action.category,
                         "action_id": action.id,
                         "reason": action.description, "carbon_saving": "未实测",
                         "difficulty": action.difficulty, "source_ref": action.source_ref,
                         "estimate": estimate})
        lines.append("\n你可以直接回复‘保持舒适优先’‘我已经一直满桶洗衣’或‘不想缩短洗澡时间’，我会记住并调整之后的建议。")
        if hints and not profile_saved: lines.append("这次信息尚未写入长期画像；本次建议仍会使用你提供的信息。")
        if not saved: lines.append("当前方案仅供预览，尚未保存。")

        # ====== P14: 渲染 HTML 报告(独立分支,不影响默认文本回复) ======
        html_report_path: Optional[str] = None
        html_report_url: Optional[str] = None
        try:
            from agent.html_reporter import HTMLReporter
            html_reporter = HTMLReporter()
            html_content = html_reporter.render_energy_plan(
                user_id=user_id,
                profile=profile.to_dict(),
                profile_sources=profile_sources,
                plan=plan.to_dict(),
                today_card=card.to_dict(),
                llm_explanation=llm_explanation,
                llm_follow_up=llm_follow_up,
                llm_meta=llm_reasoner_meta,
                obsidian_writes=profile_mining_meta.get("obsidian_paths", []),
                anti_hallu_passed=llm_reasoner_meta.get("llm_used", False),
                profile_field_count=len(profile_sources),
            )
            # 结构化目录: data/reports/by-user/<uid>/YYYY/MM/energy_plan_<plan_id>_<secret>.html
            # 文件名含随机 secret → capability URL(不可枚举,拿到链接才能看,浏览器可直接点开)
            from datetime import datetime as _dt
            from pathlib import Path
            from paths import REPORTS_DIR
            now = _dt.now()
            _secret = uuid.uuid4().hex[:16]
            reports_dir = REPORTS_DIR / "by-user" / user_id / f"{now.year:04d}" / f"{now.month:02d}"
            reports_dir.mkdir(parents=True, exist_ok=True)
            report_filename = f"energy_plan_{plan.id}_{_secret}.html"
            report_path = reports_dir / report_filename
            report_path.write_text(html_content, encoding="utf-8")
            html_report_path = str(report_path)
            # 同时按日期存一份(便于按时间清理过期报告)
            by_date_dir = REPORTS_DIR / "by-date" / f"{now.year:04d}-{now.month:02d}-{now.day:02d}"
            by_date_dir.mkdir(parents=True, exist_ok=True)
            (by_date_dir / f"{user_id[:8]}_{report_filename}").write_text(html_content, encoding="utf-8")

            # 协议自动探测:与 main.py 的 HTTPS 逻辑一致(certs/ 有证书或设了 SSL_CERT → https)
            # 优先取 PUBLIC_BASE_URL(公网/隧道部署时设置),否则用 {scheme}://localhost:{port}
            html_report_url = f"/api/reports/by-user/{user_id}/{now.year:04d}/{now.month:02d}/{report_filename}"
            _scheme = "http"
            try:
                _certs_dir = Path(__file__).resolve().parent.parent.parent / "certs"
                if os.environ.get("SSL_CERT") or (
                    _certs_dir.exists() and any(p for p in _certs_dir.glob("*.pem") if "key" not in p.name)
                ):
                    _scheme = "https"
            except Exception:
                pass
            base_url = (os.environ.get("PUBLIC_BASE_URL") or f"{_scheme}://localhost:{os.environ.get('PORT', '8000')}").rstrip("/")
            html_report_full_url = f"{base_url}{html_report_url}"
            lines.append(
                f"\n📊 **HTML 可视化报告**: {html_report_full_url}\n\n"
                f"   [👉 点击此处直接打开报告]({html_report_full_url})\n\n"
                f"   — 交互式方案(可勾选 TODO / 切 3 个 variant / 看饼图 / 看反幻觉护栏)"
            )
        except Exception as e:
            _log.warning("[_handle_energy_planning] HTML 渲染失败(降级): %s", e)

        return EnhancedAgentResponse(message="\n".join(lines), conversation_id=conversation_id,
            intent="energy_planning", timestamp=get_current_datetime(),
            suggestions=["节能建议少折腾优先", "节能建议保持舒适优先"], recommendations=recs,
            rag_context="", personalization_info={
                "energy_plan": plan.to_dict(),
                "today_card": card.to_dict(),
                "profile_sources": profile_sources,
                "llm_reasoner": llm_reasoner_meta,
                "llm_follow_up": llm_follow_up,
                "profile_mining": profile_mining_meta,
                "html_report_path": html_report_path,
                "html_report_url": html_report_url,
            },
            knowledge_refs=[], profile_updates={})

    def _parse_household_hints(self, message: str) -> dict:
        """从用户消息里抽取家庭画像线索(city/人数/费用/电器) — 最佳努力"""
        import re

        hints = {}
        msg = message or ""
        if re.search(r"假如|假设|如果我家|如果有", msg):
            return hints

        # 城市
        try:
            from agent.energy.policies import CITY_TIER_PRICING

            for key, pricing in CITY_TIER_PRICING.items():
                if key == "default":
                    continue
                for alias in pricing.city_aliases:
                    if alias and alias.lower() in msg.lower():
                        hints["city"] = key
                        break
                if "city" in hints:
                    break
        except Exception:
            pass

        # 家庭人数(中文数字/阿拉伯数字 + 口/人)
        cn = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

        def _num(tok):
            if not tok:
                return None
            try:
                return int(tok)
            except (ValueError, TypeError):
                return cn.get(tok)

        m = re.search(r"([一二三四五六七八九十两]|[0-9]+)\s*口", msg)
        if m:
            n = _num(m.group(1))
            if n:
                hints["family_size"] = n
        else:
            m = re.search(r"([一二三四五六七八九十两]|[0-9]+)\s*(?:个)?人", msg)
            if m:
                n = _num(m.group(1))
                if n:
                    hints["family_size"] = n

        # 费用
        m = re.search(r"电费[^\d]{0,4}(\d+(?:\.\d+)?)\s*元?", msg)
        if m:
            hints["monthly_electricity_bill"] = float(m.group(1))
        m = re.search(r"水费[^\d]{0,4}(\d+(?:\.\d+)?)\s*元?", msg)
        if m:
            hints["monthly_water_bill"] = float(m.group(1))
        m = re.search(r"(?:燃气费|煤气费)[^\d]{0,4}(\d+(?:\.\d+)?)\s*元?", msg)
        if m:
            hints["monthly_gas_bill"] = float(m.group(1))

        appliances = ["燃气热水器", "电热水器", "热水器", "空调", "冰箱", "洗衣机", "洗碗机", "燃气灶", "电饭煲", "灯"]
        found, removed = [], []
        device_pattern = "(?:" + "|".join(appliances) + ")"
        negatives = re.findall(r"(?:没有|不用|不使用|无)\s*(" + device_pattern + r"(?:[和、与及\s]+" + device_pattern + r")*)", msg)
        for name in appliances:
            if name == "热水器" and ("电热水器" in msg or "燃气热水器" in msg):
                continue
            if any(name in group for group in negatives):
                removed.append(name)
            elif name in msg:
                # Questions and rejected suggestions are not evidence of ownership.
                clause = next((c for c in re.split(r"[，,。；;]", msg) if name in c), "")
                declarative = bool(re.search(r"(?:有|我家|家里|家中|使用)", clause)) and not re.search(r"(?:有没有|是否有|想买|打算买)", clause)
                device_list = re.sub("|".join(appliances), "", msg)
                list_only = not re.sub(r"[、和与及\s，,。]", "", device_list)
                if declarative or list_only or re.search(r"空调.*?\d{2}\s*度", clause):
                    found.append(name)
        if found: hints["appliances"] = found
        if removed: hints["removed_appliances"] = removed
        if re.search(r"(?:没有|不用|不使用|无)\s*燃气", msg):
            hints["uses_gas"] = False
        elif "燃气灶" in found or "燃气热水器" in found:
            hints["uses_gas"] = True
        if re.search(r"空调.*?(\d{2})\s*度", msg):
            hints["ac_temp_setting"] = int(re.search(r"空调.*?(\d{2})\s*度", msg).group(1))
        feedback_actions = {"washer_full_load": ("满桶洗衣", "满载洗衣"),
                            "water_bathing_shorter": ("缩短洗澡", "缩短淋浴"),
                            "ac_temp_up_1c": ("调高空调温度", "空调升温")}
        for action_id, aliases in feedback_actions.items():
            for alias in aliases:
                if re.search(r"(?:现在可以|愿意尝试|不再).{0,5}" + alias, msg):
                    hints.setdefault("restored_actions", []).append(action_id)
                elif re.search(r"(?:不想|不愿意|不要|不接受).{0,5}" + alias, msg):
                    hints.setdefault("excluded_actions", []).append(action_id)
                elif re.search(r"(?:已经|一直).{0,5}" + alias, msg):
                    hints.setdefault("already_doing", []).append(action_id)
        if "少折腾" in msg: hints["priority"] = "easy"
        elif "舒适" in msg: hints["priority"] = "comfort"
        elif "省钱优先" in msg: hints["priority"] = "money"
        return hints

    def _merge_household_hints(self, profile, hints: dict):
        for key in ("city", "family_size", "monthly_electricity_bill", "monthly_water_bill",
                    "monthly_gas_bill", "uses_gas", "priority", "ac_temp_setting"):
            if key in hints:
                setattr(profile, key, hints[key])
        for key in ("already_doing", "excluded_actions"):
            if key in hints:
                setattr(profile, key, list(dict.fromkeys((getattr(profile, key) or []) + hints[key])))
        for key in ("already_doing", "excluded_actions"):
            setattr(profile, key, [a for a in (getattr(profile, key) or []) if a not in hints.get("restored_actions", [])])
        removed = set(hints.get("removed_appliances", []))
        profile.appliances = [a for a in dict.fromkeys((profile.appliances or []) + hints.get("appliances", [])) if a not in removed]
        if profile.uses_gas is False:
            profile.appliances = [a for a in profile.appliances if "燃气" not in a]
        profile.confirmed_fields = sorted(set(profile.confirmed_fields or []) | (set(hints) - {"removed_appliances", "restored_actions"}))
        return profile

    def _energy_explain_block(self, warning: str) -> str:
        """把 GUARD 警告转成面向用户的『还缺什么』提示"""
        mapping = {
            "GUARD_NO_APPLIANCES": "我还不知道你家有哪些电器，",
            "GUARD_UNKNOWN_CITY": "我还不确定你在哪个城市（不同城市电价差别较大），",
            "GUARD_ZERO_USAGE": "我还不知道你家的大致水电燃气用量，",
            "GUARD_EXTREME_VALUES": "你给的信息有点超出常规范围，",
        }
        for k, v in mapping.items():
            if k in warning:
                return v
        return "还缺一些信息，"

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
                    user_id, {"knowledge_level": signal.get("level", "intermediate")}
                )
                updates["knowledge_updated"] = signal.get("level")

        if analysis.get("behavior_indicators"):
            indicator = analysis["behavior_indicators"][0]
            if indicator.get("confidence", 0) > 0.6:
                self.profile_manager.update_eco_profile(
                    user_id, {"behavior_stage": indicator.get("stage", "意向")}
                )
                updates["stage_changed"] = indicator.get("stage")

        if analysis.get("action_reports"):
            for action in analysis["action_reports"]:
                if action.get("sentiment") == "positive":
                    self.profile_manager.update_preference_learning(
                        user_id, action=action.get("type"), accepted=True
                    )
            # P4-G 修复:把具体行为(如"骑自行车")写入 action_history,
            # 经 _sync_profile_to_graph 落到画像图谱的 actions 节点(之前只写类型,图谱永远没有具体行为)
            try:
                action_history_updates = [
                    {
                        "action": act.get("action", act.get("type", "")),
                        "context": act.get("original_text", ""),
                        "sentiment": "positive",
                        "type": act.get("type", ""),
                        "source": act.get("source", "chat_inferred"),
                        "confidence": act.get("confidence", 0.5),
                        "observed_at": act.get("observed_at"),
                    }
                    for act in analysis["action_reports"]
                    if act.get("sentiment") == "positive" and act.get("action")
                ]
                if action_history_updates:
                    cur = (
                        self.profile_manager.get_profile(user_id)
                        .get("eco_profile", {})
                        .get("action_history", [])
                    )
                    current_actions = {a.get("action") for a in cur if isinstance(a, dict)}
                    merged = list(cur) + [
                        a for a in action_history_updates if a["action"] not in current_actions
                    ]
                    self.profile_manager.update_eco_profile(user_id, {"action_history": merged})
            except Exception as e:
                import logging

                logging.getLogger(__name__).warning(
                    "[GreenAgent] action_history 写回图谱失败(非致命): %s", e
                )

        return updates

    def _generate_personalized_response(
        self,
        message: str,
        context,
        intent_result,
        rag_context: str,
        personalization: Dict,
        strategy: Dict,
        trace=None,
    ) -> Dict:
        """生成个性化响应"""
        IntentType = _get_module("intent")[1]

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
                    message,
                    context,
                    rag_context,
                    working_memory=working_memory_text,
                )
            except Exception as e:
                print(f"LLM生成失败，回退到模板: {e}")

        if llm_response:
            if trace is not None:
                trace.add("llm", "调用大语言模型生成回答", status="done")
            return {"message": llm_response, "suggestions": [], "response_type": "llm_generated"}

        if trace is not None:
            trace.add("llm", "LLM 不可用,使用本地模板", status="skipped")
        # 回退到模板生成
        base_response = self.response_generator.generate_response(message, context)

        # P6.S.5: 不再 dump 整个 RAG 内容(可能超长且不相关),只取前 N 字精华
        RAG_PREVIEW_CHARS = 800  # 截断长度,避免模板返 5KB 文档原文

        if rag_context:
            if intent_result.intent == IntentType.KNOWLEDGE_QUERY:
                prefix = "根据我的知识库，"
                if knowledge_level == "beginner":
                    prefix += "让我用简单的话解释：\n\n"
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
            prefix = self._generate_prefix(intent_result, personalization)
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
            "response_type": base_response.get("response_type", "general"),
        }

    def _generate_prefix(self, intent_result, personalization: Dict) -> str:
        """生成响应前缀"""
        IntentType = _get_module("intent")[1]
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
        IntentType = _get_module("intent")[1]
        behavior_stage = personalization.get("behavior_stage", "意向")

        if intent_result.intent in [IntentType.KNOWLEDGE_QUERY, IntentType.ADVICE_REQUEST]:
            stage_tips = {
                "无意向": "从小事开始，一起加油！",
                "意向": "有什么想法吗？我可以帮你分析！",
                "准备": "准备行动了吗？有什么问题随时问！",
                "行动": "继续坚持！你的努力很棒！",
                "维持": "你是低碳达人！有什么新想法吗？",
            }
            return stage_tips.get(behavior_stage, "")

        return ""

    # ========== 基础聊天 (保持向后兼容) ==========

    def _handle_travel_planning(self, user_id, message, conversation_id, intent_result, user_city=None, user_location=None):
        """P6.S.3: 出行规划专用流程 — 调高德地图 + 天气 + 碳排对比

        提取 origin/destination → 调 TravelPlanningTool → 返结构化结果
        若提取不到 origin/destination,降级为 advice(让用户补充)
        P6.S.22: 用 3 层 fallback 解析用户真实位置(origin 不再是字面量" 当前位置")
        user_city: 用户真实城市(实时定位/画像),传给工具作 geocode 消歧。
        """
        from utils.helpers import get_current_datetime

        TravelPlanningTool = _get_module("tools")

        # 1) 提取 origin / destination(P6.S.3 + S.4 改进)
        import re as _re

        # P6.S.4: 时间/代词/动词白名单,避免被误判为 origin
        NON_LOC_WORDS = {
            "我",
            "你",
            "他",
            "她",
            "我们",
            "我明天",
            "你明天",
            "今天",
            "明天",
            "后天",
            "大后天",
            "今天要",
            "明天要",
            "我明天要",
            "你明天要",
            "现在",
            "之后",
            "再",
            "马上",
            "等下",
            "等一会儿",
            "请",
            "麻烦",
            "想",
            "要",
            "想从",
            "要去",
            "要带",
            "准备",
            "我等",
            "我马上",
            "我先",
            "我现",
            "我准",
            "下午",
            "上午",
            "晚上",
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
        m = _re.search(r"从\s*([^到去,,,?？\s]{2,15})\s*[到去]\s*([^,,,?？\s]{2,15})", message)
        if m:
            cand_o = m.group(1).strip()
            if _is_valid_origin(cand_o):
                origin = cand_o
                destination = m.group(2).strip()

        # 模式 2: "A到B" 或 "A去B" (无"从")
        if not origin:
            for m in _re.finditer(
                r"([^到去,,,?？\s]{3,15})\s*[到去]\s*([^,,,?？\s]{2,15})", message
            ):
                if _is_valid_origin(m.group(1).strip()):
                    origin = m.group(1).strip()
                    destination = m.group(2).strip()
                    break

        # 模式 3: "去A" / "到A" — 只有目的地,出发地默认"当前位置"
        if not origin and not destination:
            m = _re.search(r"(?:去|到)\s*([^,,,?？\s]{2,15})", message)
            if m:
                origin = "当前位置"
                destination = m.group(1).strip()

        # 清理 destination 尾部的修饰词(长的先匹配,避免 "最环保" 被 "怎么走" 漏掉)
        if destination:
            for tail in [
                "怎么走最环保",
                "怎么坐最环保",
                "最环保的方式",
                "低碳出行",
                "环保出行",
                "绿色出行",
                "怎么走",
                "怎么坐",
                "怎么去",
                "怎么",
                "几点出发",
                "多久到",
                "多久",
                "多长",
                "最环保",
                "最绿色",
                "最省时",
                "最快",
                "出行",
                "规划",
                "路线",
                "坐公交",
                "坐地铁",
                "打车",
            ]:
                if destination.endswith(tail):
                    destination = destination[: -len(tail)].strip()
                    break  # 一次只剥一个,重新进入下一轮
            # 也清掉"去/到"尾巴
            for tail in ["去", "到"]:
                if destination.endswith(tail):
                    destination = destination[: -len(tail)].strip()

        # 清理 origin 同理
        if origin and origin != "当前位置":
            for tail in ["出发", "出发地"]:
                if origin.endswith(tail):
                    origin = origin[: -len(tail)].strip()

        # 2) 提取不到完整信息 — 返澄清问题
        if not origin or not destination:
            return AgentResponse(
                message="要帮你规划出行,需要知道 **出发地** 和 **目的地** 哦。\n\n试试这样说:\n• 从北京西单到国贸怎么走\n• 从家到公司坐公交多久\n• 明天去国贸",
                conversation_id=conversation_id,
                intent="travel_planning",
                suggestions=[
                    "从家到公司怎么走",
                    "从北京西单到国贸,坐地铁多久",
                    "从公司到机场,最环保的方式",
                ],
                timestamp=get_current_datetime(),
            )

        # 2) 调工具
        try:
            tool = TravelPlanningTool()
            result = tool.execute(
                origin=origin, destination=destination, mode="all",
                user_id=user_id, city=user_city or "", location=user_location or {},
            )
        except Exception as e:
            return AgentResponse(
                message=f"出行规划工具调用失败: {type(e).__name__}: {str(e)[:200]}",
                conversation_id=conversation_id,
                intent="travel_planning",
                suggestions=["试试其它交通方式", "查询附近公交站"],
                timestamp=get_current_datetime(),
            )

        # 3) 格式化响应
        if not result.success:
            # 路线工具失败时只报告失败。知识库只能提供一般知识，不能替代
            # 路径服务生成具体路线、时长、票价或导航。
            error_text = result.error or "路线查询失败"
            provider_code = (result.data or {}).get("code", "")
            error_category = {
                "ROUTE_PROVIDER_NOT_CONFIGURED": "missing_api_key",
                "ROUTE_PROVIDER_RATE_LIMITED": "rate_limited",
                "MODE_ROUTE_UNAVAILABLE": "mode_unavailable",
            }.get(provider_code, "no_route")

            return AgentResponse(
                message=(f"⚠️ {error_text}\n\n"
                         "本次没有取得可核验的路线，因此不会展示路线、时间、费用或碳排。"),
                conversation_id=conversation_id,
                intent="travel_planning",
                suggestions=["重新输入更完整的起点和终点", "稍后重试路线查询"],
                tool_result={
                    "origin": origin,
                    "destination": destination,
                    "error": error_text,
                    "error_category": error_category,
                    "provider_code": provider_code,
                    "routes": [],
                },
                timestamp=get_current_datetime(),
            )

        # 4) 成功 — 格式化路线
        data = result.data
        routes = data.get("routes", [])
        weather = data.get("weather", {})
        recommended = data.get("recommended", {})
        weights = data.get("weights", {})

        # 格式化路线(注意:实际 key 是 'type' 不是 'mode')
        route_lines = []
        for i, r in enumerate(routes[:5], 1):
            # P6.S.15: 显示具体线路名(如"地铁1号线 → 公交52路")
            line_detail = r.get("line", "")
            if line_detail and line_detail != r.get("type", ""):
                line_str = f"({line_detail})"
            else:
                line_str = ""
            # P6.S.15: 显示评分明细(碳/费用/时长/天气)
            breakdown = r.get("score_breakdown", {})
            score_info = ""
            if breakdown:
                carbon_score_text = ("缺失" if breakdown.get("carbon") is None
                                     else breakdown.get("carbon"))
                score_info = (
                    f" [碳:{carbon_score_text} "
                    f"费:{breakdown.get('cost', '?')} "
                    f"时:{breakdown.get('duration', '?')} "
                    f"天:{breakdown.get('weather', '?')}]"
                )

            # P6.S.15: 显示碳减排对比(对比自驾)
            carbon_savings = ""
            if r.get("type") != "自驾" and r.get("carbon_kg") is not None:
                # 找到自驾那条
                driving = next((x for x in routes if x.get("type") == "自驾"), None)
                if driving and driving.get("carbon_kg") is not None:
                    saved = float(driving["carbon_kg"]) - float(r["carbon_kg"])
                    if saved > 0.01:
                        carbon_savings = f"  ⬇️ -碳{saved:.2f}kg"

            fare_text = (f"¥{float(r['cost_yuan']):.1f}"
                         if r.get("cost_yuan") is not None else "费用未知")
            carbon_text = (f"{float(r['carbon_kg']):.2f} kg"
                           if r.get("carbon_kg") is not None else "暂不可核验")
            carbon_note = r.get("carbon_note")
            route_lines.append(
                f"{i}. **{r.get('type', r.get('mode', '?'))}**{line_str} — "
                f"{r.get('distance_km', '?')}km, 约 {r.get('duration_min', '?')} 分钟, "
                f"碳排 {carbon_text}, {fare_text}"
                f"{carbon_savings}{score_info}"
                f"{('（' + carbon_note + '）') if carbon_note else ''}"
            )
        route_text = "\n".join(route_lines) if route_lines else "(暂无路线数据)"

        # P6.S.15: 评分修正(实际是 0-1,要显示成 0-10 直观)
        rec_text = ""
        if recommended:
            score_raw = recommended.get("score", 0)
            score_10 = round(float(score_raw) * 10, 1)  # 0.577 → 5.8
            # 构造详细理由
            bd = recommended.get("score_breakdown", {})
            reason_parts = []
            if bd.get("carbon") is not None and bd.get("carbon", 0) > 0.7:
                reason_parts.append("碳排最低")
            if bd.get("cost", 0) > 0.7:
                reason_parts.append("性价比高")
            if bd.get("duration", 0) > 0.7:
                reason_parts.append("用时最短")
            if bd.get("weather", 0) > 0.7:
                reason_parts.append("天气适宜")
            reason = "、".join(reason_parts) if reason_parts else "综合最优"
            if recommended.get("weather_note"):
                reason += f" ({recommended['weather_note']})"
            rec_text = (
                f"\n\n🌟 **推荐:{recommended.get('type', recommended.get('mode', '?'))}** "
                f"(综合评分 {score_10}/10)\n"
                f"理由: {reason}"
            )

        # 天气(注意:实际 key 是 'temp_c' 不是 'temp')
        weather_text = ""
        if weather:
            w = weather
            weather_text = (
                f"\n\n🌤️ 天气:{w.get('description', '?')}, "
                f"温度 {w.get('temp_c', w.get('temp', '?'))}°C, "
                f"骑行适宜度 {'✅' if w.get('cycling_ok', True) else '⚠️ 不建议'}"
                + (f" {w.get('note', '')}" if w.get("note") else "")
            )

        # P6.S.15: 多因素评分权重提示
        weight_text = ""
        if weights:
            weight_text = (
                f"\n\n📊 评分权重:碳排 {weights.get('carbon', '?')} · "
                f"费用 {weights.get('cost', '?')} · "
                f"时长 {weights.get('duration', '?')} · "
                f"天气 {weights.get('weather', '?')}"
            )

        message_text = (
            f"🚲 **{origin} → {destination}** 多因素低碳出行方案:\n\n"
            f"{route_text}"
            f"{rec_text}"
            f"{weather_text}"
            f"{weight_text}\n\n"
            f"💡 按当前可核验的碳排、费用、时长和天气数据进行综合推荐；缺失维度不会按 0 计算"
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
                "电动车充电桩位置",
            ],
            tool_result=data,  # 完整结构化数据给前端用
            timestamp=get_current_datetime(),
        )

    def chat(self, user_id: str, message: str, conversation_id: str = None) -> "AgentResponse":
        """处理用户对话（基础版）"""
        IntentRecognizer, IntentType, IntentResult = _get_module("intent")
        ResponseGenerator, ResponseContext = _get_module("response")
        get_current_datetime = _get_module("helpers")[1]

        conversation_id = self._manage_conversation(user_id, conversation_id)
        conversation = self.active_conversations[conversation_id]
        # turn_count 由 ConversationStore.get_or_create 在复用会话时递增(store 是唯一所有者),
        # 这里不再手动 +1,避免双倍计数。
        conversation.last_updated = get_current_datetime()

        intent_result = self.intent_recognizer.recognize(message)

        # P6.S.3: 出行规划走工具调用(高德地图 + 天气 + 碳排对比)
        if intent_result.intent == IntentType.TRAVEL_PLANNING:
            return self._handle_travel_planning(user_id, message, conversation_id, intent_result)

        if self.web_searcher and self.web_searcher.is_realtime_query(message):
            realtime_response = self.web_searcher.get_realtime_response(message)

            self._update_memories(
                user_id, conversation_id, message, intent_result, realtime_response
            )
            self._increment_conversation_count(user_id)

            return AgentResponse(
                message=realtime_response,
                conversation_id=conversation_id,
                intent="realtime_query",
                suggestions=["给我更多低碳生活建议", "推荐一些环保行动"],
                timestamp=get_current_datetime(),
            )

        retrieved_knowledge = self._retrieve_knowledge(message, intent_result)
        user_profile = self.profile_manager.get_profile(user_id)
        recent_memories = self._get_recent_memories(user_id)
        conversation_history = self._compact_history(
            self.short_term_memory.get_conversation_history(conversation_id)
        )

        context = ResponseContext(
            user_profile=user_profile,
            conversation_history=conversation_history,
            retrieved_knowledge=retrieved_knowledge,
            recent_memories=recent_memories,
            intent_type=intent_result.suggested_response_type,
        )

        # P6.S.5: 优先用 LLM(若可用),失败回退到模板
        response_data = None
        if self.use_llm and self.response_generator:
            try:
                rag_context_str = (
                    "\n".join(k.get("content", "")[:500] for k in retrieved_knowledge[:3])
                    if retrieved_knowledge
                    else ""
                )
                # P6.S.5 final: 强制 MockLLMClient(若 .env 启 LLM_MOCK 或 server 启动时设过)
                # 直接构造 MockLLMClient 跳过工厂,避免 _build_prompt + llm.chat hang
                if os.getenv("LLM_MOCK", "auto").strip().lower() in ("true", "1", "yes", "on"):
                    from llm.client import MockLLMClient

                    mock = MockLLMClient()
                    # 用 RAG 摘要作为 system context
                    last_user_msg = message
                    augmented_msg = (
                        f"{last_user_msg}\n\n[知识库参考资料]:\n{rag_context_str[:1000]}"
                    )
                    mock_resp = mock.chat([{"role": "user", "content": augmented_msg}])
                    llm_text = (
                        mock_resp.content if hasattr(mock_resp, "content") else str(mock_resp)
                    )
                else:
                    llm_text = self.response_generator.generate_with_llm(
                        message, context, rag_context_str
                    )
                if llm_text and llm_text.strip():
                    response_data = {
                        "message": llm_text,
                        "suggestions": [],
                        "knowledge_refs": [k.get("title", "") for k in retrieved_knowledge[:3]],
                        "response_type": "llm_generated",
                    }
            except Exception as e:
                print(f"[P6.S.5] LLM 失败,回退模板: {e}", flush=True)

        if not response_data:
            response_data = self.response_generator.generate_response(message, context)

        profile_updates = self._update_memories(
            user_id, conversation_id, message, intent_result, response_data["message"]
        )
        self._update_user_profile(user_id, intent_result, profile_updates)

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
            timestamp=get_current_datetime(),
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

    def _resolve_current_location(
        self, user_id: str, conversation_id: str = None, message: str = ""
    ) -> str:
        """P6.S.22: 3 层 fallback 解析用户当前位置

        优先级:
          1) 浏览器(前端 navigator.geolocation 上报)
          2) 用户画像 default city(basic_info.region)
          3) IP 反查(ip-api.com,带进程内缓存)
          失败兜底:北京

        Returns: 城市名字符串(高德地理编码能解析的形式)
        """
        try:
            from utils.geolocate import best_location

            geo = best_location(handler=self, user_id=user_id)
            if geo and geo.city:
                return geo.city
        except Exception as e:
            import logging

            logging.getLogger(__name__).debug("[P6.S.22] resolve location: %s", e)
        return "北京"

    def _get_recent_memories(self, user_id: str) -> List[str]:
        """获取用户最近的记忆(P6.S.18: 100 字符,含类型 + 重要度)"""
        memories = []
        long_term_memories = self.long_term_memory.get_recent_memories(user_id, limit=3)
        for m in long_term_memories:
            content = m.get("content", "")
            memories.append(
                f"[{m.get('type', 'memory')} | 重要度:{m.get('importance', 0.5):.2f}] {content[:100]}"
            )
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
                semantic = self.long_term_memory.search_memories(user_id, query, limit=limit)
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

    def _update_memories(
        self, user_id, conversation_id, user_message, intent_result, response_message
    ):
        """更新记忆系统"""
        updates = {}

        self.short_term_memory.add_message(
            conversation_id=conversation_id,
            role="user",
            content=user_message,
            metadata={"intent": intent_result.intent.value},
        )
        self.short_term_memory.add_message(
            conversation_id=conversation_id,
            role="assistant",
            content=response_message,
            metadata={"intent": intent_result.intent.value},
        )

        key_info = self._extract_key_info(user_message, intent_result)

        if key_info:
            self.long_term_memory.add_memory(
                user_id=user_id,
                content=key_info["content"],
                memory_type=key_info["type"],
                importance=key_info.get("importance", 0.5),
            )
            updates["new_memory"] = key_info["type"]

        return updates

    def _extract_key_info(self, message: str, intent_result) -> Optional[Dict]:
        """提取关键信息用于记忆"""
        IntentType = _get_module("intent")[1]

        if intent_result.intent == IntentType.ACTION_REPORT:
            return {
                "content": f"用户报告: {message[:100]}",
                "type": "action_report",
                "importance": 0.7,
            }
        elif intent_result.intent == IntentType.ADVICE_REQUEST:
            return {
                "content": f"用户感兴趣: {message[:100]}",
                "type": "interest",
                "importance": 0.6,
            }
        elif intent_result.intent == IntentType.FEEDBACK:
            return {"content": f"用户反馈: {message[:100]}", "type": "feedback", "importance": 0.8}
        return None

    def _update_user_profile(self, user_id: str, intent_result, updates: Dict):
        """更新用户画像"""
        IntentType = _get_module("intent")[1]

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

    def _compact_history(self, history: List[Dict]) -> List[Dict]:
        """P16: 按 token 预算压缩对话历史,防长对话爆窗。

        仅做"保留最近轮次、折叠更早轮次"的纯逻辑截断;滚动摘要(需 LLM)
        由调用方按 needs_summary 标志异步补做。失败回退为原历史(不阻塞主路径)。
        """
        if not history:
            return history
        try:
            from agent.context_compactor import compact_history, ContextBudget

            budget = ContextBudget()
            return compact_history(history, budget.history).kept
        except Exception:
            import logging

            logging.getLogger(__name__).warning("[P16] context 压缩失败,回退原历史")
            return history

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
            "total_conversations",
            "total_messages",
            "questions_asked",
            "actions_reported",
            "feedback_given",
            "suggestions_accepted",
            "suggestions_rejected",
        ]
        total = sum(stats.get(field, 0) for field in numeric_fields)

        if total < 5:
            return "low"
        elif total < 20:
            return "medium"
        else:
            return "high"

    def get_knowledge_stats(self) -> Dict[str, Any]:
        """获取知识库统计

        P6.S.23 修复: 此前 `total_documents` 来自 `KnowledgeManager.documents`
        (内存静态 KB,可能 0);前端用户看到"知识条目=0"以为是 RAG 数字。
        现在优先用 RAG 向量库的 vector_store_count,前端展示的"知识条目"
        才是用户实际能召回的语料数。
        """
        stats = self.knowledge_manager.get_stats()
        # 静态 markdown 文件数(用于 P1 的"知识库文件数"展示)
        stats["knowledge_base_files"] = stats.get("total_documents", 0)

        if self.rag_enabled and self.rag_engine:
            try:
                rag_stats = self.rag_engine.get_stats()
                stats["rag_enabled"] = True
                stats["rag_stats"] = rag_stats
                # P6.S.23: 主数字用 RAG 实际块数(150 doc),而不是 0 的内存 KB
                stats["total_documents"] = (
                    rag_stats.get("vector_store_count", 0)
                    + rag_stats.get("bm25_doc_count", 0)
                )
            except Exception as e:
                # Bug12: ChromaDB collection 丢失/异常时降级,不让 /api/knowledge/stats 500
                import logging
                logging.getLogger(__name__).warning(
                    "[GreenAgent] RAG stats 失败(降级返回静态 KB): %s", e
                )
                stats["rag_enabled"] = False
                stats["rag_error"] = str(e)[:200]
                # 保持 total_documents = 静态 KB 文档数(已从 knowledge_manager 拿)
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
            "export_time": datetime.now().isoformat(),
        }


if __name__ == "__main__":
    from pathlib import Path

    project_root = Path(__file__).parent.parent.parent

    agent = GreenAgent(knowledge_base_path=str(project_root / "knowledge_base"), enable_rag=True)

    user_id = agent.register_user(
        {"age_group": "26-35", "region": "北京", "interests": ["低碳出行", "节能减排"]}
    )
    print(f"\n注册成功，用户ID: {user_id}")

    onboarding = agent.start_onboarding(user_id)
    print(f"\n引导流程: {onboarding}")

    response = agent.chat_enhanced(user_id, "什么是碳中和？")
    print(f"\n助手: {response.message}")
    print(f"\n个性化信息: {response.personalization_info}")
    print(f"\n推荐: {response.recommendations}")
