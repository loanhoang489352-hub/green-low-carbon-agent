"""
用户画像 / 个性化 / 统计 / 会话 路由 (P5-E: APIError 化)
"""


def register_profile_routes(registry) -> None:
    """注册画像相关路由"""

    from server.errors import APIError

    def _require_owner(handler, user_id) -> None:
        """P0: 校验 URL/body 中的 user_id 属于当前登录用户(防 IDOR 水平越权)"""
        current = getattr(handler, "current_user", None) or {}
        if not current.get("user_id"):
            raise APIError("UNAUTHORIZED", "需要登录")
        if user_id != current["user_id"]:
            raise APIError("FORBIDDEN", "无权访问该用户数据")

    def profile_get(handler):
        # /api/profile/{user_id} — 直接用 token 身份,避免前端 userId 与 token 不一致导致 403
        current = getattr(handler, "current_user", None) or {}
        user_id = current.get("user_id")
        if not user_id:
            raise APIError("UNAUTHORIZED", "需要登录")
        profile = handler.agent.get_user_profile(user_id)
        handler.send_json({"user_id": user_id, "profile": profile})

    def personalization_get(handler):
        # /api/personalization/{user_id}  (GET) — 用 token 身份
        current = getattr(handler, "current_user", None) or {}
        user_id = current.get("user_id")
        if not user_id:
            raise APIError("UNAUTHORIZED", "需要登录")
        ctx = handler.agent.get_personalization_context(user_id)
        handler.send_json({"user_id": user_id, "context": ctx})

    def personalization_context(handler, data):
        # /api/personalization/context  (POST)
        user_id = data.get("user_id")
        if not user_id:
            raise APIError("BAD_REQUEST", "user_id required")
        _require_owner(handler, user_id)
        ctx = handler.agent.get_personalization_context(user_id)
        handler.send_json({"context": ctx})

    def user_stats(handler):
        # /api/stats/{user_id} — 用 token 身份
        current = getattr(handler, "current_user", None) or {}
        user_id = current.get("user_id")
        if not user_id:
            raise APIError("UNAUTHORIZED", "需要登录")
        stats = handler.agent.get_user_stats(user_id)
        handler.send_json({"user_id": user_id, "stats": stats})

    def conversation_get(handler):
        # /api/conversation/{conv_id}  (GET)
        parts = handler.path.strip("/").split("/")
        conv_id = parts[-1] if len(parts) >= 3 else None
        if not conv_id:
            raise APIError("BAD_REQUEST", "conversation_id required")
        current = getattr(handler, "current_user", None) or {}
        if not current.get("user_id"):
            raise APIError("UNAUTHORIZED", "需要登录")
        try:
            store = handler.agent.conversation_store
            ctx = store.get(conv_id) if hasattr(store, "get") else None
            if ctx is not None and ctx.user_id != current["user_id"]:
                raise APIError("FORBIDDEN", "无权访问该对话")
        except APIError:
            raise
        except Exception:
            pass
        history = handler.agent.get_conversation_history(conv_id)
        handler.send_json({"history": history})

    # P5-D 鉴权强制落地: profile/personalization/stats 全部需鉴权
    # (user 隐私数据,无 token 不可访问;前端已带 token 调 loadProfile)
    registry.add_route(
        "GET", "^/api/profile/", profile_get, auth_required=True, description="用户画像(GET)"
    )
    registry.add_route(
        "GET",
        "^/api/personalization/",
        personalization_get,
        auth_required=True,
        description="个性化上下文(GET)",
    )
    registry.add_route(
        "POST",
        "/api/personalization/context",
        personalization_context,
        auth_required=True,
        description="个性化上下文(POST)",
    )
    registry.add_route(
        "GET", "^/api/stats/", user_stats, auth_required=True, description="用户统计"
    )
    registry.add_route(
        "GET",
        "^/api/conversation/",
        conversation_get,
        auth_required=True,
        description="对话历史(GET)",
    )
