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

        # P4-B.2: 短期记忆写入(用户消息)
        try:
            from memory.short_term import get_short_term_memory
            stm = get_short_term_memory()
            stm.add_message(
                conversation_id=state.get("conversation_id", ""),
                role="user",
                content=message,
                metadata={"intent": intent_result.intent.value},
            )
        except Exception:
            pass  # 短期记忆失败不应阻塞主流程

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
        """节点2: RAG 知识检索(P4-F.1:基于用户画像软过滤)"""
        self.initialize()

        if not self._rag_engine or not self._rag_engine.is_enabled:
            return {
                "rag_context": "",
                "rag_results": [],
                "knowledge_refs": []
            }

        message = state["message"]
        intent_type = state.get("intent_type", "")

        # P4-F.1: 基于用户画像构造软过滤信号(region + interests)
        personalization = self._build_personalization_hints(state)

        try:
            raw_results = self._rag_engine.retrieve(
                message, top_k=max(8, 3 * 2),  # 多取一些用于软过滤
            )

            # 软重排:region/interests 命中的文档分数加成
            ranked = self._rerank_by_personalization(
                raw_results, personalization,
            )

            # 标准化成 dict 格式,方便后续处理
            rag_items = [
                {
                    "id": r.id,
                    "content": r.content,
                    "source": (r.metadata or {}).get("source", "未知来源"),
                    "metadata": r.metadata,
                    "score": r.score,
                }
                for r in ranked[:3]
            ]

            if rag_items:
                context_parts = []
                refs = []
                for item in rag_items:
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
                "rag_results": rag_items,
                "knowledge_refs": refs
            }
        except Exception as e:
            return {
                "rag_context": "",
                "rag_results": [],
                "knowledge_refs": [],
                "error": f"知识检索失败: {str(e)}"
            }

    def _build_personalization_hints(self, state: AgentState) -> Dict[str, Any]:
        """根据用户画像构造个性化信号(P4-F.1)

        返回:
        - region: 用户地区
        - interests: 用户兴趣列表
        - 其它可用于软过滤的信号
        """
        try:
            user_id = state.get("user_id", "")
            if not user_id or not self._profile_manager:
                return {}
            profile = self._profile_manager.get_profile(user_id)
            if not profile:
                return {}

            basic = profile.get("basic_info", {}) or {}
            eco = profile.get("eco_profile", {}) or {}
            return {
                "region": basic.get("region") or "全国",
                "interests": list(eco.get("primary_interests") or []),
            }
        except Exception:
            return {}

    def _rerank_by_personalization(
        self,
        results: List[Any],
        hints: Dict[str, Any],
    ) -> List[Any]:
        """基于个性化信号对检索结果软重排(P4-F.1)

        策略:
        - 文档的 category 或 source 路径包含 region → 分数 * 1.3
        - 文档的 category 或 source 包含任一 interest → 分数 * 1.15
        - 累乘后排序,取 top_k
        """
        if not results or not hints:
            return results

        region = (hints.get("region") or "").strip()
        interests = hints.get("interests") or []

        # 地区关键词映射(中→英/拼音),用于软匹配
        region_aliases = self._region_aliases(region)
        # 兴趣关键词映射(代码 ID → 文件名常用关键词)
        interest_keywords: List[str] = []
        for interest in interests:
            interest_keywords.extend(self._interest_keywords(interest))

        def boost(result) -> float:
            meta = getattr(result, "metadata", None) or {}
            category = str(meta.get("category", ""))
            source = str(meta.get("source", ""))
            haystack = f"{category} {source}".lower()
            score = result.score
            if region and region != "全国":
                # 命中任一别名
                if any(alias.lower() in haystack for alias in region_aliases):
                    score *= 1.3
            if interest_keywords:
                if any(kw.lower() in haystack for kw in interest_keywords):
                    score *= 1.15
            return score

        # 直接修改 score 字段,避免新建对象
        for r in results:
            r.score = boost(r)
        return sorted(results, key=lambda r: r.score, reverse=True)

    @staticmethod
    def _region_aliases(region: str) -> List[str]:
        """地区名 → 关键词列表(P4-F.1:软匹配中文/英文文件名)"""
        aliases = [region] if region else []
        mapping = {
            "北京": ["北京", "beijing"],
            "上海": ["上海", "shanghai"],
            "广州": ["广州", "guangzhou"],
            "深圳": ["深圳", "shenzhen"],
            "杭州": ["杭州", "hangzhou"],
            "成都": ["成都", "chengdu"],
            "全国": ["全国", "national", "china"],
        }
        if region in mapping:
            aliases.extend(mapping[region])
        return list({a for a in aliases if a})

    @staticmethod
    def _interest_keywords(interest: str) -> List[str]:
        """兴趣 ID → 关键词列表(用于匹配文档 source/category)"""
        if not interest:
            return []
        mapping = {
            "low_carbon_travel": ["low_carbon_travel", "travel", "出行", "交通", "green_travel"],
            "energy_saving": ["energy_saving", "energy", "用电", "节能", "home_energy"],
            "green_consumption": ["green_consumption", "consumption", "消费"],
            "diet_eco": ["diet_eco", "diet", "饮食", "food"],
            "waste_classification": ["waste_classification", "waste", "垃圾", "分类"],
        }
        if interest in mapping:
            return mapping[interest]
        return [interest]

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
        """节点5: 生成个性化推荐(P4-F.3:静态 + RAG 混合)"""
        self.initialize()

        user_id = state["user_id"]
        profile = state.get("profile", {})
        intent_type = state.get("intent_type", "")
        rag_results = state.get("rag_results", []) or []

        try:
            static_recs = self._recommendation_engine.generate_recommendations(
                user_id=user_id,
                user_profile=profile,
                context={"intent_type": intent_type},
            )
            # P4-F.3: 用 RAG 检索到的本地政策补充推荐
            recommendations = self._recommendation_engine.augment_with_rag(
                static_recommendations=static_recs,
                user_profile=profile,
                rag_results=rag_results,
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

            # P4-B.2: 短期记忆写入(助手回复)
            try:
                from memory.short_term import get_short_term_memory
                stm = get_short_term_memory()
                stm.add_message(
                    conversation_id=state.get("conversation_id", ""),
                    role="assistant",
                    content=response_text,
                    metadata={"intent": intent_type},
                )
            except Exception:
                pass

            # P4-B.1: 触发短→长整合(节点出口)
            try:
                from memory.consolidation import get_consolidator
                consolidator = get_consolidator()
                conv_id = state.get("conversation_id", "")
                user_id = state.get("user_id", "")
                consolidator.update_conversation_activity(conv_id)
                consolidator.update_message_count(conv_id, count=2)
                consolidator.consolidate(user_id, conv_id)
            except Exception:
                pass

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
