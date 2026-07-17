"""
路由模块包
每个模块负责一个资源组的路由:
- system: 健康检查、根路径、metrics
- chat: 聊天接口
- auth: 认证(注册/登录/会话)(P5-D)
- profile: 用户画像 / 个性化 / 统计(P5-D)
- onboarding: 引导流程
- feedback: 反馈
- policy: 政策
- knowledge: 知识库
- settings: API Key 设置(P5-D)
- pet: 宠物养成(任务 1+扩展)(M1/M2/M3 集成)— 默认禁用,见 ENABLE_PET
"""

import os

from .system import register_system_routes
from .chat import register_chat_routes
from .auth import register_auth_routes
from .feedback import register_feedback_routes
from .onboarding import register_onboarding_routes
from .profile import register_profile_routes
from .policy import register_policy_routes
from .settings import register_settings_routes


def register_all_routes(registry) -> None:
    """注册所有路由

    ENABLE_PET: 是否注册宠物路由(default false,2026-06-14 用户撤销 UI 后设置)
    - false: pet router 不注册(后端 PetEngine 仍可 import / 调,但无 HTTP 入口)
    - true:  恢复 19 端点(后续重做前端 UI 时设 true)
    """
    register_system_routes(registry)
    register_chat_routes(registry)
    register_auth_routes(registry)
    register_feedback_routes(registry)
    register_onboarding_routes(registry)
    register_profile_routes(registry)
    register_policy_routes(registry)
    register_settings_routes(registry)
    if os.environ.get("ENABLE_PET", "false").lower() in ("1", "true", "yes", "on"):
        from .pet import register_pet_routes
        register_pet_routes(registry)
        import logging
        logging.getLogger("server.routers").info("[pet] ENABLE_PET=true,19 路由已注册")
    else:
        import logging
        logging.getLogger("server.routers").info("[pet] ENABLE_PET 未启用,宠物路由不注册")


__all__ = ["register_all_routes"]
