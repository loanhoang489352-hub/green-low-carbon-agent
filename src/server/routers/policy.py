"""
政策路由: latest / summary / check-updates
P5-D 迁移 (latest / summary 已在 system.py 注册,这里补 check-updates)
"""


def register_policy_routes(registry) -> None:
    """注册政策相关路由"""

    def policy_check_updates(handler, data):
        try:
            result = handler.policy_updater.check_updates()
            handler.send_json(result)
        except Exception as e:
            handler.send_json({"error": str(e)}, status=500)

    registry.add_route("POST", "/api/policy/check-updates", policy_check_updates, auth_required=False, description="检查政策更新")
