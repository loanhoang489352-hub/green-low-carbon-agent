"""
引导路由: start / answer / status / questions (P5-E: APIError 化)
"""

import uuid


def register_onboarding_routes(registry) -> None:
    """注册引导相关路由"""

    from server.errors import APIError
    from server.identity import resolve_user_id

    def onboarding_questions(handler):
        questions = handler.agent.profile_manager.get_onboarding_questions()
        handler.send_json({"questions": questions})

    def onboarding_status(handler, data):
        user_id = data.get("user_id")
        if not user_id:
            raise APIError("BAD_REQUEST", "user_id required")
        status = handler.agent.get_onboarding_status(user_id)
        handler.send_json(status)

    def onboarding_start(handler, data):
        user_id = resolve_user_id(handler, data)
        if user_id == "anonymous":
            raise APIError("UNAUTHORIZED", "需登录后开始引导")
        result = handler.agent.start_onboarding(user_id)
        handler.send_json(result)

    def onboarding_answer(handler, data):
        user_id = resolve_user_id(handler, data)
        step = data.get("step")
        answer = data.get("answer")

        if user_id == "anonymous":
            user_id = data.get("user_id") or str(uuid.uuid4())[:12]

        if step is None:
            raise APIError("BAD_REQUEST", "step required")

        result = handler.agent.process_onboarding_answer(user_id, step, answer)
        handler.send_json({"user_id": user_id, **result})

    def user_register(handler, data):
        user_info = data.get("user_info", {})
        # 已登录用户:把引导信息写入账号关联的 user_id,避免新建游离的独立画像 id。
        # /api/user/register 保持 auth_required=False(登录前匿名引导仍可用),
        # 但若请求带了 Bearer token,则手动识别登录身份,写入账号画像。
        account_identity = None
        try:
            from auth.account_manager import AccountManager

            mgr = AccountManager()
            account_identity = mgr.verify_token(handler.headers, data)
        except Exception:
            account_identity = None
        if account_identity and account_identity.get("user_id"):
            user_id = handler.agent.apply_onboarding_to_profile(
                account_identity["user_id"], user_info
            )
            handler.send_json({"user_id": user_id, "status": "registered"})
            return
        user_id = handler.agent.register_user(user_info)
        handler.send_json({"user_id": user_id, "status": "registered"})

    def user_update(handler, data):
        # P0: 需鉴权 + owner 校验(只能改自己的画像)
        current = getattr(handler, "current_user", None) or {}
        user_id = data.get("user_id")
        profile_data = data.get("profile", {})
        if not user_id:
            raise APIError("BAD_REQUEST", "user_id required")
        if current.get("user_id"):
            # 已登录:强制改自己的画像
            if user_id != current["user_id"]:
                raise APIError("FORBIDDEN", "无权修改该用户画像")
        else:
            # 未登录(理论上不会到这,路由已鉴权):仅允许匿名/temp_ 用户
            if not (user_id == "anonymous" or user_id.startswith("temp_")):
                raise APIError("UNAUTHORIZED", "需登录后才能更新画像")
        handler.agent.profile_manager.update_profile(user_id, profile_data)
        handler.send_json({"status": "updated"})

    # P5-D 鉴权策略:
    #   - questions / status 保持公开(只读,无需鉴权)
    #   - start / answer 翻转 auth_required=True(写入用户画像,需鉴权)
    #   - user.register 保持公开(等同 auth/register,登录前可用)
    #   - user.update 需鉴权(P0 修复:防公开越权改写任意用户画像)
    registry.add_route(
        "GET",
        "/api/onboarding/questions",
        onboarding_questions,
        auth_required=False,
        description="获取引导问题(公开,只读)",
    )
    registry.add_route(
        "POST",
        "/api/onboarding/status",
        onboarding_status,
        auth_required=False,
        description="引导状态(公开,只读)",
    )
    registry.add_route(
        "POST",
        "/api/onboarding/start",
        onboarding_start,
        auth_required=True,
        description="开始引导(P5-D:需鉴权,写入用户画像)",
    )
    registry.add_route(
        "POST",
        "/api/onboarding/answer",
        onboarding_answer,
        auth_required=True,
        description="回答引导问题(P5-D:需鉴权,写入用户画像)",
    )
    registry.add_route(
        "POST",
        "/api/user/register",
        user_register,
        auth_required=False,
        description="注册用户(等同 auth/register,公开)",
    )
    registry.add_route(
        "POST",
        "/api/user/update",
        user_update,
        auth_required=True,
        description="更新用户画像(需鉴权,P0 修复防越权写)",
    )
