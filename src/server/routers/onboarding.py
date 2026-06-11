"""
引导路由: start / answer / status / questions (P5-E: APIError 化)
"""
import uuid


def register_onboarding_routes(registry) -> None:
    """注册引导相关路由"""

    from server.errors import APIError

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
        user_id = data.get("user_id")
        if not user_id:
            raise APIError("BAD_REQUEST", "user_id required")
        result = handler.agent.start_onboarding(user_id)
        handler.send_json(result)

    def onboarding_answer(handler, data):
        user_id = data.get("user_id")
        step = data.get("step")
        answer = data.get("answer")

        if not user_id or user_id.startswith("temp_"):
            user_id = str(uuid.uuid4())[:12]

        if step is None:
            raise APIError("BAD_REQUEST", "step required")

        result = handler.agent.process_onboarding_answer(user_id, step, answer)
        handler.send_json({"user_id": user_id, **result})

    def user_register(handler, data):
        user_info = data.get("user_info", {})
        user_id = handler.agent.register_user(user_info)
        handler.send_json({"user_id": user_id, "status": "registered"})

    def user_update(handler, data):
        user_id = data.get("user_id")
        profile_data = data.get("profile", {})
        if not user_id:
            raise APIError("BAD_REQUEST", "user_id required")
        handler.agent.profile_manager.update_profile(user_id, profile_data)
        handler.send_json({"status": "updated"})

    # P6.A: questions 公开(初次访问展示问题);status/start/answer/user.update 全部需鉴权
    registry.add_route("GET", "/api/onboarding/questions", onboarding_questions, auth_required=False, description="获取引导问题")
    registry.add_route("POST", "/api/onboarding/status", onboarding_status, auth_required=True, description="引导状态")
    registry.add_route("POST", "/api/onboarding/start", onboarding_start, auth_required=True, description="开始引导")
    registry.add_route("POST", "/api/onboarding/answer", onboarding_answer, auth_required=True, description="回答引导问题")
    registry.add_route("POST", "/api/user/register", user_register, auth_required=False, description="注册用户(等同 auth/register)")
    registry.add_route("POST", "/api/user/update", user_update, auth_required=True, description="更新用户画像")
