"""
统一身份解析(identity 策略)

解决"聊天与节能各用一套 user_id"的漂移问题:
所有需要个人身份的路由(chat/chat_enhanced/recommendations/energy/*)都通过
resolve_user_id(handler, data) 得到同一个 user_id,禁止各自重复实现。

策略(本地决策,写在这文件里,永不漂移):
  1. 已登录(handler.current_user.user_id 存在,由 verify_token 注入):
       使用账号关联的 user_id(登录时 agent.register_user(account_id=...) 生成)。
       聊天 / 节能 / 推荐在此情形下都用**同一个** user_id,访同一个画像库。
  2. 未登录(匿名/游客):
       使用 body 里的 user_id(前端生成的 guest id)。
       但 guest id 必须是 "anonymous" 或以 "temp_" 开头(与 chat.py 历史约束一致),
       否则统一兜底回 "anonymous"。节能与推荐因涉及隐私,通常要求登录(auth_required=True),
       guest 场景多用于基础聊天。

这样:同一个人无论从聊天页还是节能页进入,只要是同一登录 token,拿到的都是同一个 user_id,
profile / memory / energy 画像全落在同一主键下。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

GUEST_PREFIXES = ("anonymous", "temp_")


def resolve_user_id(handler, data: Optional[Dict[str, Any]] = None) -> str:
    """从请求上下文解析并**规范化** user_id(聊天与节能统一入口)

    规则:
      - 已登录 → current_user.user_id(账号关联,唯一身份)
      - 未登录 → 允许 guest id(body user_id 且为 anonymous/temp_ 前缀),否则兜底 "anonymous"
    """
    current = getattr(handler, "current_user", None) or {}
    if current.get("user_id"):
        return str(current["user_id"])

    uid = (data or {}).get("user_id", "anonymous") or "anonymous"
    uid = str(uid)
    if uid == "anonymous" or uid.startswith(GUEST_PREFIXES[1]):
        return uid
    # 随机 uuid 等不合规 guest id → 统一兜底 anonymous,避免伪造他人
    return "anonymous"


def is_logged_in(handler) -> bool:
    """是否已登录(有 current_user.user_id)"""
    current = getattr(handler, "current_user", None) or {}
    return bool(current.get("user_id"))


__all__ = ["resolve_user_id", "is_logged_in", "GUEST_PREFIXES"]
