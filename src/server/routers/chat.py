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
        # P6.S.3: 完整序列化(含 tool_result 让前端可渲染地图/天气/路线)
        handler.send_json({
            "message": response.message,
            "conversation_id": response.conversation_id,
            "intent": response.intent if hasattr(response, "intent") else None,
            "suggestions": response.suggestions if hasattr(response, "suggestions") else [],
            "tool_result": response.tool_result if hasattr(response, "tool_result") else None,
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

    # P6.S.14: chat 端点对匿名 user_id 公开(避免浏览器无 token 时 401)
    #   - 用 user_id(在 body 里)做身份,不再强制 Bearer session_id
    #   - 浏览器 onboarding 后 / 匿名 user 都能直接聊天
    #   - 仍支持 Bearer token:有则用 login user,无则用 body user_id
    #   - 敏感端点(feedback/memory/profile)仍需 auth
    registry.add_route("POST", "/api/chat", chat, auth_required=False, description="基础聊天")
    registry.add_route("POST", "/api/chat/enhanced", chat_enhanced, auth_required=False, description="增强聊天(RAG+个性化)")
    registry.add_route("POST", "/api/conversation/reset", conversation_reset, auth_required=False, description="重置对话")
    registry.add_route("POST", "/api/conversation/history", conversation_history, auth_required=False, description="对话历史")
    registry.add_route("POST", "/api/recommendations", recommendations, auth_required=False, description="个性化推荐")
