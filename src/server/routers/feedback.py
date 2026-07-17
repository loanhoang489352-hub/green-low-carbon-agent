"""
反馈路由: 点赞/点踩/评论 + 统计/历史 (P5-D + P5-E: APIError 化)
"""

from urllib.parse import urlparse, parse_qs


def register_feedback_routes(registry) -> None:
    """注册反馈相关路由"""

    from server.errors import APIError

    def feedback_submit(handler, data):
        message_id = data.get("message_id")
        feedback_type = data.get("type")
        if not message_id or not feedback_type:
            raise APIError("BAD_REQUEST", "message_id and type are required")
        from main import get_feedback_manager

        fm = get_feedback_manager()
        result = fm.add_feedback(
            message_id=message_id,
            user_id=data.get("user_id", "anonymous"),
            conversation_id=data.get("conversation_id"),
            feedback_type=feedback_type,
            reason=data.get("reason"),
            comment=data.get("comment"),
        )
        if result.get("success"):
            handler.send_json({"status": "success", "action": result.get("action")})
        else:
            raise APIError("BAD_REQUEST", result.get("error", "Feedback failed"))

    def feedback_message(handler, data):
        message_id = data.get("message_id")
        if not message_id:
            raise APIError("BAD_REQUEST", "message_id is required")
        from main import get_feedback_manager

        fm = get_feedback_manager()
        stats = fm.get_message_feedback(message_id)
        user_status = fm.check_user_feedback(message_id, data.get("user_id", "anonymous"))
        stats["user_status"] = user_status
        handler.send_json(stats)

    def feedback_stats(handler, data):
        try:
            days = int(parse_qs(urlparse(handler.path).query).get("days", ["7"])[0])
        except (ValueError, TypeError):
            days = 7
        from main import get_feedback_manager

        fm = get_feedback_manager()
        handler.send_json(fm.get_feedback_stats(days))

    def feedback_history(handler, data):
        # 路径: /api/feedback/history/{user_id}  或直接 body
        parts = handler.path.strip("/").split("/")
        user_id = (
            parts[-1]
            if len(parts) > 3 and parts[-1] != "history"
            else data.get("user_id", "anonymous")
        )
        try:
            limit = int(parse_qs(urlparse(handler.path).query).get("limit", ["50"])[0])
        except (ValueError, TypeError):
            limit = 50
        from main import get_feedback_manager

        fm = get_feedback_manager()
        handler.send_json({"history": fm.get_user_feedback_history(user_id, limit)})

    def feedback_negative(handler, data):
        try:
            limit = int(parse_qs(urlparse(handler.path).query).get("limit", ["20"])[0])
        except (ValueError, TypeError):
            limit = 20
        from main import get_feedback_manager

        fm = get_feedback_manager()
        handler.send_json({"negative_feedback": fm.get_recent_negative_feedback(limit)})

    # P6.A: feedback 全部需鉴权(写敏感读操作,P5-I 审计)
    registry.add_route(
        "POST", "/api/feedback", feedback_submit, auth_required=True, description="提交反馈"
    )
    registry.add_route(
        "POST",
        "/api/feedback/message",
        feedback_message,
        auth_required=True,
        description="消息反馈详情",
    )
    registry.add_route(
        "POST", "/api/feedback/stats", feedback_stats, auth_required=True, description="反馈统计"
    )
    registry.add_route(
        "POST",
        "/api/feedback/history",
        feedback_history,
        auth_required=True,
        description="用户反馈历史",
    )
    registry.add_route(
        "POST",
        "/api/feedback/negative",
        feedback_negative,
        auth_required=True,
        description="最近负面反馈",
    )
