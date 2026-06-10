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
"""
from .system import register_system_routes
from .chat import register_chat_routes
from .auth import register_auth_routes
from .feedback import register_feedback_routes
from .onboarding import register_onboarding_routes
from .profile import register_profile_routes
from .policy import register_policy_routes
from .settings import register_settings_routes


def register_all_routes(registry) -> None:
    """注册所有路由"""
    register_system_routes(registry)
    register_chat_routes(registry)
    register_auth_routes(registry)
    register_feedback_routes(registry)
    register_onboarding_routes(registry)
    register_profile_routes(registry)
    register_policy_routes(registry)
    register_settings_routes(registry)


__all__ = ["register_all_routes"]
