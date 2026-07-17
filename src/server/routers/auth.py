"""
认证路由: 注册 / 登录 / 登出 / 会话验证 (P5-D + P5-E: APIError 化)
"""


def register_auth_routes(registry) -> None:
    """注册认证相关路由"""

    from server.errors import APIError

    def auth_register(handler, data):
        username = data.get("username")
        password = data.get("password")
        if not username or not password:
            raise APIError("BAD_REQUEST", "用户名和密码必填")
        result = handler.account_manager.register(username, password)
        if result.get("success"):
            handler.send_json(
                {
                    "status": "success",
                    "account_id": result.get("account_id"),
                    "username": result.get("username"),
                }
            )
        else:
            raise APIError("BAD_REQUEST", result.get("error", "注册失败"))

    def auth_login(handler, data):
        username = data.get("username")
        password = data.get("password")
        if not username or not password:
            raise APIError("BAD_REQUEST", "用户名和密码必填")
        result = handler.account_manager.login(username, password)
        if result.get("success"):
            account_id = result.get("account_id")
            user_id = handler.account_manager.get_user_id_by_account(account_id)
            if not user_id:
                agent = handler.agent
                user_id = agent.register_user(account_id=account_id)
            handler.send_json(
                {
                    "status": "success",
                    "session_id": result.get("session_id"),
                    "account_id": account_id,
                    "username": result.get("username"),
                    "user_id": user_id,
                    "expires_at": result.get("expires_at"),
                }
            )
        else:
            raise APIError("UNAUTHORIZED", result.get("error", "登录失败"))

    def auth_logout(handler, data):
        session_id = data.get("session_id")
        if session_id:
            handler.account_manager.logout(session_id)
        handler.send_json({"status": "success"})

    def auth_check(handler, data):
        session_id = data.get("session_id")
        if not session_id:
            handler.send_json({"valid": False, "error": "session_id required"})
            return
        account_id = handler.account_manager.validate_session(session_id)
        if account_id:
            info = handler.account_manager.get_account_info(account_id)
            if info:
                handler.send_json(
                    {
                        "valid": True,
                        "account_id": account_id,
                        "username": info.get("username"),
                    }
                )
                return
        handler.send_json({"valid": False})

    def auth_session(handler, data):
        session_id = data.get("session_id")
        if not session_id:
            raise APIError("BAD_REQUEST", "session_id required")
        session_info = handler.account_manager.get_session_info(session_id)
        handler.send_json({"status": "success", "session": session_info})

    # 任务2 P2-2: 新增鉴权端点(演示 secure 模式)
    def auth_whoami(handler, data):
        """检查当前会话身份 — 需鉴权"""
        user = getattr(handler, "current_user", None)
        if not user:
            raise APIError("UNAUTHORIZED", "未登录或 token 失效")
        handler.send_json({"status": "success", "user": user})

    def auth_change_password(handler, data):
        """修改密码 — 需鉴权 + fail-fast 校验"""
        old_pwd = data.get("old_password", "")
        new_pwd = data.get("new_password", "")
        if not old_pwd or not new_pwd:
            raise APIError("BAD_REQUEST", "old_password 与 new_password 必填")
        if len(new_pwd) < 8:
            raise APIError("BAD_REQUEST", "新密码至少 8 位")
        user = getattr(handler, "current_user", None)
        if not user:
            raise APIError("UNAUTHORIZED", "未登录")
        # 改密码
        mgr = handler.account_manager
        account_id = user.get("account_id")
        ok = mgr.change_password(account_id, old_pwd, new_pwd)
        if not ok:
            raise APIError("BAD_REQUEST", "旧密码错误")
        handler.send_json({"status": "success", "msg": "密码已修改"})

    # P6.A: register/login/check/session 公开(认证端点本身);logout 需鉴权(要验证 token 才登出)
    registry.add_route(
        "POST", "/api/auth/register", auth_register, auth_required=False, description="用户注册"
    )
    registry.add_route(
        "POST", "/api/auth/login", auth_login, auth_required=False, description="登录"
    )
    registry.add_route(
        "POST", "/api/auth/logout", auth_logout, auth_required=True, description="登出"
    )
    registry.add_route(
        "POST", "/api/auth/check", auth_check, auth_required=False, description="验证会话"
    )
    registry.add_route(
        "POST", "/api/auth/session", auth_session, auth_required=False, description="会话详情"
    )
    # 任务2 P2-2: secure 端点(默认需鉴权)
    registry.add_route(
        "POST", "/api/auth/whoami", auth_whoami, auth_required=True, description="查当前会话"
    )
    registry.add_route(
        "POST",
        "/api/auth/change_password",
        auth_change_password,
        auth_required=True,
        description="改密",
    )
