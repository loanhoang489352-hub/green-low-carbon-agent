"""
路由模块包
每个模块负责一个资源组的路由:
- system: 健康检查、根路径
- chat: 聊天接口
- auth: 认证(注册/登录/会话)
- profile: 用户画像
- onboarding: 引导流程
- feedback: 反馈
- policy: 政策
- knowledge: 知识库
- settings: API Key 设置
"""
from .system import register_system_routes
from .chat import register_chat_routes


def register_all_routes(registry) -> None:
    """注册所有路由"""
    register_system_routes(registry)
    register_chat_routes(registry)


__all__ = ["register_all_routes"]
