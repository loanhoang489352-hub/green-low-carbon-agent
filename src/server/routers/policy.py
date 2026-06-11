"""
政策路由: latest / summary / check-updates (P5-E: 异常由 _dispatch 兜底)
"""


def register_policy_routes(registry) -> None:
    """注册政策相关路由"""

    def policy_check_updates(handler, data):
        result = handler.policy_updater.check_updates()
        handler.send_json(result)

    registry.add_route("POST", "/api/policy/check-updates", policy_check_updates, auth_required=True, description="检查政策更新(写操作,触发爬取)")
