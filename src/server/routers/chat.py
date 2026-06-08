"""
聊天路由
"""
import uuid


def register_chat_routes(registry) -> None:

    def chat(handler, data):
        user_id = data.get("user_id", "anonymous")
        message = data.get("message", "")
        conversation_id = data.get("conversation_id")

        if not message:
            handler.send_json({"error": "Message is required"}, status=400)
            return

        try:
            response = handler.agent.chat(user_id, message, conversation_id)
            handler.send_json({
                "message": response.message,
                "conversation_id": response.conversation_id,
                "intent": response.intent if hasattr(response, "intent") else None,
            })
        except Exception as e:
            handler.send_error(500, f"Internal error: {str(e)}")

    def chat_enhanced(handler, data):
        user_id = data.get("user_id", "anonymous")
        message = data.get("message", "")
        conversation_id = data.get("conversation_id")

        if not message:
            handler.send_json({"error": "Message is required"}, status=400)
            return

        try:
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
        except Exception as e:
            handler.send_error(500, f"Internal error: {str(e)}")

    def conversation_reset(handler, data):
        conv_id = data.get("conversation_id")
        if conv_id:
            handler.agent.reset_conversation(conv_id)
        handler.send_json({"status": "success"})

    def conversation_history(handler, data):
        conv_id = data.get("conversation_id")
        if not conv_id:
            handler.send_json({"error": "conversation_id required"}, status=400)
            return
        history = handler.agent.get_conversation_history(conv_id)
        handler.send_json({"history": history})

    def recommendations(handler, data):
        user_id = data.get("user_id", "anonymous")
        try:
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
        except Exception as e:
            handler.send_error(500, f"Internal error: {str(e)}")

    def personalization_context(handler, data):
        user_id = data.get("user_id")
        if not user_id:
            handler.send_json({"error": "user_id required"}, status=400)
            return
        ctx = handler.agent.get_personalization_context(user_id)
        handler.send_json({"context": ctx})

    registry.add_route("POST", "/api/chat", chat, auth_required=False, description="基础聊天")
    registry.add_route("POST", "/api/chat/enhanced", chat_enhanced, auth_required=False, description="增强聊天(RAG+个性化)")
    registry.add_route("POST", "/api/conversation/reset", conversation_reset, auth_required=False, description="重置对话")
    registry.add_route("POST", "/api/conversation/history", conversation_history, auth_required=False, description="对话历史")
    registry.add_route("POST", "/api/recommendations", recommendations, auth_required=False, description="个性化推荐")
    registry.add_route("POST", "/api/personalization/context", personalization_context, auth_required=False, description="个性化上下文")
