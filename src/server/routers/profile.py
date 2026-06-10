"""
用户画像 / 个性化 / 统计 / 会话 路由 (P5-E: APIError 化)
"""


def register_profile_routes(registry) -> None:
    """注册画像相关路由"""

    from server.errors import APIError

    def profile_get(handler):
        # /api/profile/{user_id}
        parts = handler.path.strip("/").split("/")
        user_id = parts[-1] if len(parts) >= 3 else "anonymous"
        profile = handler.agent.get_user_profile(user_id)
        handler.send_json({"user_id": user_id, "profile": profile})

    def personalization_get(handler):
        # /api/personalization/{user_id}  (GET)
        parts = handler.path.strip("/").split("/")
        user_id = parts[-1] if len(parts) >= 3 else None
        if not user_id:
            raise APIError("BAD_REQUEST", "user_id required")
        ctx = handler.agent.get_personalization_context(user_id)
        handler.send_json({"user_id": user_id, "context": ctx})

    def personalization_context(handler, data):
        # /api/personalization/context  (POST)
        user_id = data.get("user_id")
        if not user_id:
            raise APIError("BAD_REQUEST", "user_id required")
        ctx = handler.agent.get_personalization_context(user_id)
        handler.send_json({"context": ctx})

    def user_stats(handler):
        # /api/stats/{user_id}
        parts = handler.path.strip("/").split("/")
        user_id = parts[-1] if len(parts) >= 3 else "anonymous"
        stats = handler.agent.get_user_stats(user_id)
        handler.send_json({"user_id": user_id, "stats": stats})

    def conversation_get(handler):
        # /api/conversation/{conv_id}  (GET)
        parts = handler.path.strip("/").split("/")
        conv_id = parts[-1] if len(parts) >= 3 else None
        if not conv_id:
            raise APIError("BAD_REQUEST", "conversation_id required")
        history = handler.agent.get_conversation_history(conv_id)
        handler.send_json({"history": history})

    registry.add_route("GET", "^/api/profile/", profile_get, auth_required=False, description="用户画像(GET)")
    registry.add_route("GET", "^/api/personalization/", personalization_get, auth_required=False, description="个性化上下文(GET)")
    registry.add_route("POST", "/api/personalization/context", personalization_context, auth_required=False, description="个性化上下文(POST)")
    registry.add_route("GET", "^/api/stats/", user_stats, auth_required=False, description="用户统计")
    registry.add_route("GET", "^/api/conversation/", conversation_get, auth_required=False, description="对话历史(GET)")
