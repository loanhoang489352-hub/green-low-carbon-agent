"""
引导路由: start / answer / status / questions
P5-D 迁移
"""
import uuid


def register_onboarding_routes(registry) -> None:
    """注册引导相关路由"""

    def onboarding_questions(handler):
        try:
            questions = handler.agent.profile_manager.get_onboarding_questions()
            handler.send_json({"questions": questions})
        except Exception as e:
            handler.send_json({"error": str(e)}, status=500)

    def onboarding_status(handler, data):
        user_id = data.get("user_id")
        if not user_id:
            handler.send_json({"error": "user_id required"}, status=400)
            return
        status = handler.agent.get_onboarding_status(user_id)
        handler.send_json(status)

    def onboarding_start(handler, data):
        user_id = data.get("user_id")
        if not user_id:
            handler.send_json({"error": "user_id required"}, status=400)
            return
        result = handler.agent.start_onboarding(user_id)
        handler.send_json(result)

    def onboarding_answer(handler, data):
        user_id = data.get("user_id")
        step = data.get("step")
        answer = data.get("answer")

        if not user_id or user_id.startswith("temp_"):
            user_id = str(uuid.uuid4())[:12]

        if step is None:
            handler.send_json({"error": "step required"}, status=400)
            return

        result = handler.agent.process_onboarding_answer(user_id, step, answer)
        handler.send_json({"user_id": user_id, **result})

    def user_register(handler, data):
        user_info = data.get("user_info", {})
        try:
            user_id = handler.agent.register_user(user_info)
            handler.send_json({"user_id": user_id, "status": "registered"})
        except Exception as e:
            handler.send_json({"error": f"注册失败: {str(e)}"}, status=500)

    def user_update(handler, data):
        user_id = data.get("user_id")
        profile_data = data.get("profile", {})
        if not user_id:
            handler.send_json({"error": "user_id required"}, status=400)
            return
        handler.agent.profile_manager.update_profile(user_id, profile_data)
        handler.send_json({"status": "updated"})

    registry.add_route("GET", "/api/onboarding/questions", onboarding_questions, auth_required=False, description="获取引导问题")
    registry.add_route("POST", "/api/onboarding/status", onboarding_status, auth_required=False, description="引导状态")
    registry.add_route("POST", "/api/onboarding/start", onboarding_start, auth_required=False, description="开始引导")
    registry.add_route("POST", "/api/onboarding/answer", onboarding_answer, auth_required=False, description="回答引导问题")
    registry.add_route("POST", "/api/user/register", user_register, auth_required=False, description="注册用户")
    registry.add_route("POST", "/api/user/update", user_update, auth_required=False, description="更新用户画像")
