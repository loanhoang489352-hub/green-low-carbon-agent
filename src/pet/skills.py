"""
任务6: 宠物 Skill 注册(MCP 兼容)
3 个 Skill:
  - pet_status_read: 读状态
  - pet_feed: 投喂
  - pet_appearance_change: 换装
"""

from __future__ import annotations

import logging
from typing import Any, Dict

_logger = logging.getLogger("pet.skills")


def register_pet_skills(skill_registry=None) -> None:
    """任务6: 注册 3 个宠物 Skill

    如果 skill_registry 传入,注册到对应系统;否则尝试从 agent.skills 拿。
    """
    from .pet_engine import get_pet_engine

    engine = get_pet_engine()

    def _status_read(params: Dict[str, Any]) -> Dict[str, Any]:
        user_id = params.get("user_id", "anonymous")
        state = engine.get_state(user_id)
        return state.to_dict()

    def _feed(params: Dict[str, Any]) -> Dict[str, Any]:
        user_id = params.get("user_id", "anonymous")
        item_id = params.get("item_id", "led_bulb")
        return engine.feed(user_id, item_id)

    def _appearance_change(params: Dict[str, Any]) -> Dict[str, Any]:
        user_id = params.get("user_id", "anonymous")
        appearance_id = params.get("appearance_id", "seed")
        try:
            from .constants import _get_conn

            conn = _get_conn()
            conn.execute(
                "INSERT OR REPLACE INTO pet_appearance_unlocks (user_id, appearance_id, equipped) VALUES (?, ?, ?)",
                (user_id, appearance_id, True),
            )
            conn.execute("UPDATE pets SET appearance=? WHERE user_id=?", (appearance_id, user_id))
            conn.commit()
            return {"ok": True, "appearance": appearance_id}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    if skill_registry is not None:
        try:
            skill_registry.register(
                "pet_status_read", _status_read, description="查询用户的低碳守护精灵当前状态"
            )
            skill_registry.register("pet_feed", _feed, description="给用户的低碳守护精灵投喂道具")
            skill_registry.register(
                "pet_appearance_change", _appearance_change, description="切换精灵形态或装备装扮"
            )
            _logger.info("[pet] 3 个 Skill 已注册到 skill_registry")
        except Exception as e:
            _logger.warning("[pet] Skill 注册失败: %s", e)
    else:
        _logger.info("[pet] 3 个 Skill 函数已定义,等待外部注册")
