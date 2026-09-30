"""
设置路由: API Key / 模型设置
P5-D 迁移
"""

import os


def register_settings_routes(registry) -> None:
    """注册设置相关路由"""

    from server.errors import APIError

    def save_api_key(handler, data):
        api_key = data.get("api_key")
        provider = data.get("provider", "openai")
        model = data.get("model")

        if not api_key:
            raise APIError("BAD_REQUEST", "api_key required")
        # 防 .env 注入:provider 必须在白名单内,key/provider/model 不允许换行或 '='
        if provider not in ("openai", "minimax", "zhipu", "baidu", "ali", "deepseek"):
            raise APIError("BAD_REQUEST", f"不支持的 provider: {provider}")
        for _name, _val in (("api_key", api_key), ("provider", provider), ("model", model or "")):
            if any(_c in str(_val) for _c in ("\n", "\r", "=")):
                raise APIError("BAD_REQUEST", f"{_name} 含非法字符(换行/等号)")

        # P17: 按 user_id 存(加密落库),不再写全局 .env、不再改全局 os.environ
        from server.identity import resolve_user_id

        user_id = resolve_user_id(handler, data)
        if not user_id or user_id == "anonymous" or user_id.startswith("temp_"):
            raise APIError("UNAUTHORIZED", "匿名用户无法保存 API key,请先登录")

        from llm.user_keys import save_key

        save_key(user_id, api_key, provider, model)

        # 清掉该用户的缓存客户端,下次调用用新 key
        try:
            from llm.client import reset_user_llm_client

            reset_user_llm_client(user_id)
        except Exception:
            pass

        handler.send_json(
            {
                "status": "saved",
                "message": "已保存到你的账号(仅本人使用,加密存储)",
                "provider": provider,
                "model": model or "默认",
            }
        )

    registry.add_route(
        "POST",
        "/api/settings/api-key",
        save_api_key,
        auth_required=True,
        description="保存 API Key(写操作,需鉴权)",
    )
