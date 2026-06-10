"""
设置路由: API Key / 模型设置
P5-D 迁移
"""
import os
from pathlib import Path


def register_settings_routes(registry) -> None:
    """注册设置相关路由"""

    from server.errors import APIError

    def save_api_key(handler, data):
        api_key = data.get("api_key")
        provider = data.get("provider", "openai")
        model = data.get("model")

        if not api_key:
            raise APIError("BAD_REQUEST", "api_key required")

        os.environ["API_PROVIDER"] = provider
        provider_key_map = {
            "openai": "OPENAI_API_KEY",
            "minimax": "MINIMAX_API_KEY",
            "zhipu": "ZHIPU_API_KEY",
            "baidu": "BAIDU_API_KEY",
            "ali": "ALI_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
        }
        key_name = provider_key_map.get(provider, "OPENAI_API_KEY")
        os.environ[key_name] = api_key

        if model:
            os.environ["API_MODEL"] = model
        else:
            default_models = {
                "openai": "gpt-4o-mini",
                "minimax": "abab6.5s",
                "zhipu": "glm-4-flash",
                "baidu": "ernie-4.0-8k",
                "ali": "qwen-plus",
                "deepseek": "deepseek-chat",
            }
            os.environ["API_MODEL"] = default_models.get(provider, "gpt-4o-mini")

        # 持久化到 .env
        try:
            from server.app import PROJECT_ROOT
            env_path = PROJECT_ROOT / ".env"
            if env_path.exists():
                with open(env_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                updated_lines = []
                for line in lines:
                    stripped = line.strip()
                    if stripped.startswith("API_PROVIDER="):
                        updated_lines.append(f"API_PROVIDER={provider}\n")
                    elif stripped.startswith("API_MODEL="):
                        updated_lines.append(f"API_MODEL={os.environ.get('API_MODEL')}\n")
                    elif stripped.startswith(f"{key_name}="):
                        updated_lines.append(f"{key_name}={api_key}\n")
                    else:
                        updated_lines.append(line)
                with open(env_path, "w", encoding="utf-8") as f:
                    f.writelines(updated_lines)
        except Exception as e:
            handler.send_json({"warning": f".env write failed: {e}"})

        # 重置 LLM 客户端
        try:
            from llm import reset_llm_client
            reset_llm_client()
        except Exception:
            pass

        handler.send_json({
            "status": "saved",
            "message": "设置已保存",
            "model": os.environ.get("API_MODEL"),
        })

    registry.add_route("POST", "/api/settings/api-key", save_api_key, auth_required=False, description="保存 API Key")
