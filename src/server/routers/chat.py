"""
聊天路由 (P5-E: 改用 APIError 异常体系,异常不再泄栈)
"""


def register_chat_routes(registry) -> None:
    """注册聊天相关路由"""

    from server.errors import APIError

    def chat(handler, data):
        user_id = data.get("user_id", "anonymous")
        message = data.get("message", "")
        conversation_id = data.get("conversation_id")

        if not message:
            raise APIError("BAD_REQUEST", "Message is required")

        response = handler.agent.chat(user_id, message, conversation_id)
        handler.send_json({
            "message": response.message,
            "conversation_id": response.conversation_id,
            "intent": response.intent if hasattr(response, "intent") else None,
        })

    def chat_enhanced(handler, data):
        user_id = data.get("user_id", "anonymous")
        message = data.get("message", "")
        conversation_id = data.get("conversation_id")

        if not message:
            raise APIError("BAD_REQUEST", "Message is required")

        response = handler.agent.chat_enhanced(user_id, message, conversation_id)
        handler.send_json({
            "message": response.message,
            "conversation_id": response.conversation_id,
            "intent": response.intent,
            "suggestions": response.suggestions,
            "knowledge_refs": response.knowledge_refs,
            "timestamp": response.timestamp,
            "personalization": response.personalization_info,
            "recommendations": response.recommendations,
            "profile_updates": response.profile_updates,
        })

    def conversation_reset(handler, data):
        conv_id = data.get("conversation_id")
        if conv_id:
            handler.agent.reset_conversation(conv_id)
        handler.send_json({"status": "success"})

    def conversation_history(handler, data):
        conv_id = data.get("conversation_id")
        if not conv_id:
            raise APIError("BAD_REQUEST", "conversation_id required")
        history = handler.agent.get_conversation_history(conv_id)
        handler.send_json({"history": history})

    def recommendations(handler, data):
        user_id = data.get("user_id", "anonymous")
        profile = handler.agent.get_user_profile(user_id)
        from user_profile.personalized_recommender import PersonalizedRecommendationEngine
        engine = PersonalizedRecommendationEngine()
        recs = engine.generate_recommendations(profile, count=3)
        handler.send_json({
            "recommendations": [
                {
                    "action": r.action,
                    "category": r.category,
                    "reason": r.reason,
                    "carbon_saving": r.estimated_carbon_saving,
                    "difficulty": r.difficulty,
                    "impact": r.impact,
                    "examples": r.examples,
                }
                for r in recs
            ]
        })

    # P6.A: P5-D 鉴权真落地 — chat/conversation/recommendations 全员需 Bearer session_id
    registry.add_route("POST", "/api/chat", chat, auth_required=True, description="基础聊天")
    registry.add_route("POST", "/api/chat/enhanced", chat_enhanced, auth_required=True, description="增强聊天(RAG+个性化)")
    registry.add_route("POST", "/api/conversation/reset", conversation_reset, auth_required=True, description="重置对话")
    registry.add_route("POST", "/api/conversation/history", conversation_history, auth_required=True, description="对话历史")
    registry.add_route("POST", "/api/recommendations", recommendations, auth_required=True, description="个性化推荐")
