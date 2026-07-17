"""
反馈事件订阅者
收到 FEEDBACK_RECEIVED 时更新用户画像(likes/dislikes 反映偏好)
"""

import logging

from events import EventType, get_event_bus

logger = logging.getLogger(__name__)


def _update_profile_preferences(
    user_id: str, feedback_type: str, reason=None, comment=None
) -> None:
    """根据反馈调整用户画像的偏好"""
    try:
        from user_profile.user_profile import UserProfileManager

        pm = UserProfileManager()
        profile = pm.get_profile(user_id)
        prefs = profile.get("eco_profile", {}).setdefault(
            "feedback_preferences",
            {
                "liked_categories": [],
                "disliked_categories": [],
                "last_feedback": None,
            },
        )
        if feedback_type == "like":
            # 点赞:把 comment 或 reason 提到的领域记为偏好
            text = comment or reason or ""
            if text and text not in prefs["liked_categories"]:
                prefs["liked_categories"].append(text)
        elif feedback_type == "dislike":
            text = reason or comment or ""
            if text and text not in prefs["disliked_categories"]:
                prefs["disliked_categories"].append(text)
        from datetime import datetime

        prefs["last_feedback"] = datetime.now().isoformat()
        pm.update_eco_profile(user_id, {"feedback_preferences": prefs})
        logger.info("[Feedback→Profile] 更新用户 %s 画像: type=%s", user_id, feedback_type)
    except Exception as e:
        logger.exception("[Feedback→Profile] 更新画像失败: %s", e)


def register_feedback_subscribers() -> None:
    """注册反馈事件订阅者(应用启动时调用一次)"""
    bus = get_event_bus()
    bus.subscribe(EventType.FEEDBACK_RECEIVED, _on_feedback_received)
    logger.info("反馈事件订阅者已注册")


def _on_feedback_received(event_type, user_id, feedback_type, reason=None, comment=None, **kwargs):
    """事件回调"""
    _update_profile_preferences(user_id, feedback_type, reason, comment)
