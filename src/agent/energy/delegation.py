"""
P12.2: 委托级别 (Delegation Level) 模块

四档:
  0: 完全自动 — 写操作直接做(无确认)
  1: 默认自动 — 写操作直接做(可附 confirmation_required=false)
  2: 多方案可选 — 写操作前必须 confirmation(给 3 个 variant 让用户挑)
  3: 只看不存 — 写操作不持久化,只 echo

P5-D 鉴权: 所有委托级别变更需登录用户,P5-I 审计已就位。

API 集成点:
  - POST /api/energy/profile  按 level 决定 profile 持久化策略
  - POST /api/energy/plan     按 level 决定 plan 持久化策略 + 是否激活
  - POST /api/household/delegation  改 level(也支持聊天中改)
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from paths import HOUSEHOLDS_DB

logger = logging.getLogger(__name__)


class DelegationLevel(int, Enum):
    """4 档委托级别 — 越低越自动,越高越保守"""

    FULL_AUTO = 0          # 全自动,直接执行
    ASSUMED_AUTO = 1        # 默认自动(可关闭 confirmation 提示)
    MULTI_CHOICE = 2        # 多方案(需用户选)
    ECHO_ONLY = 3           # 只看不存


# 反向映射:数字 → 字符串(i18n 用)
LEVEL_LABELS = {
    0: "全自动",
    1: "默认自动",
    2: "多方案选择",
    3: "只看不存",
}


@dataclass
class DelegationDecision:
    """一次写操作的委托决策"""

    level: int
    should_persist: bool           # 是否持久化到 DB
    should_activate: bool          # 是否自动激活(plan 专用)
    confirmation_required: bool    # 是否需要用户再次确认
    variant_mode: bool             # 是否生成多 variant(2/3 档)
    echo_only: bool                # 是否只 echo 不存(3 档)


def should_ask_confirmation(level: int) -> bool:
    """Level 2/3 需要确认(API 拦截写操作)

    Args:
        level: 委托级别(0/1/2/3)

    Returns:
        True = 需要 confirmation,False = 直接做
    """
    return int(level) >= DelegationLevel.MULTI_CHOICE.value


def decide_for_write(level: int) -> DelegationDecision:
    """根据委托级别,返回写操作策略

    行为对照:
      0: persist=True,  activate=False (no confirmation needed),
         variant_mode=False, echo_only=False
         (激活交给调用方,这里只是 write 策略)
      1: persist=True,  confirmation_required=False,
         variant_mode=False, echo_only=False
      2: persist=False, confirmation_required=True,
         variant_mode=True,  echo_only=False
         (用户选完 variant 后会再调一次 level=0/1 路径持久化)
      3: persist=False, confirmation_required=True,
         variant_mode=False, echo_only=True
    """
    level = int(level)
    if level == 0:
        return DelegationDecision(
            level=0,
            should_persist=True,
            should_activate=False,
            confirmation_required=False,
            variant_mode=False,
            echo_only=False,
        )
    if level == 1:
        return DelegationDecision(
            level=1,
            should_persist=True,
            should_activate=False,
            confirmation_required=False,
            variant_mode=False,
            echo_only=False,
        )
    if level == 2:
        return DelegationDecision(
            level=2,
            should_persist=False,
            should_activate=False,
            confirmation_required=True,
            variant_mode=True,
            echo_only=False,
        )
    # level == 3
    return DelegationDecision(
        level=3,
        should_persist=False,
        should_activate=False,
        confirmation_required=True,
        variant_mode=False,
        echo_only=True,
    )


def _get_conn() -> sqlite3.Connection:
    """获取 households.db 连接(走 P6.E 连接池)"""
    from db.connection import get_connection

    return get_connection(str(HOUSEHOLDS_DB))


def get_delegation_level(user_id: str) -> int:
    """从 DB 读用户的委托级别;若无则默认 1

    Args:
        user_id: 用户 ID

    Returns:
        level(0/1/2/3),默认 1
    """
    try:
        conn = _get_conn()
        row = conn.execute(
            "SELECT delegation_level FROM household_profiles WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row:
            try:
                val = row["delegation_level"]
                # P12.2 fix: 不能用 `or 1`,level=0 时会被当成 None
                if val is None:
                    return 1
                return int(val)
            except (TypeError, ValueError):
                return 1
        return 1
    except Exception as e:
        logger.warning("[Delegation] get_level 失败 user_id=%s: %s", user_id, e)
        return 1


def set_delegation_level(user_id: str, level: int) -> bool:
    """设置委托级别(0/1/2/3)。若画像不存在则创建一个空的

    Args:
        user_id: 用户 ID
        level: 0/1/2/3

    Returns:
        True = 成功
    """
    level = int(level)
    if level not in (0, 1, 2, 3):
        raise ValueError(f"Invalid delegation_level: {level} (must be 0/1/2/3)")
    try:
        conn = _get_conn()
        now = datetime.now().isoformat()
        existing = conn.execute(
            "SELECT user_id FROM household_profiles WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE household_profiles SET delegation_level = ?, updated_at = ? "
                "WHERE user_id = ?",
                (level, now, user_id),
            )
        else:
            # 用空 profile 创建一条
            empty_profile = "{}"
            conn.execute(
                "INSERT INTO household_profiles "
                "(user_id, profile_json, delegation_level, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (user_id, empty_profile, level, now),
            )
        conn.commit()
        return True
    except Exception as e:
        logger.warning("[Delegation] set_level 失败 user_id=%s: %s", user_id, e)
        return False


def parse_level_from_natural_language(text: str) -> Optional[int]:
    """从自然语言里识别委托级别变更意图

    闲聊中用户说:"以后不用每次问我" → level=0
             "给我选就行" → level=1
             "我要自己选" → level=2
             "先别存" → level=3
    """
    if not text:
        return None
    text_lower = text.lower()
    # 完全自动
    if any(
        k in text
        for k in (
            "全自动",
            "不用问",
            "不用每次",
            "不用再问",
            "你帮我做",
            "全部自动",
            "fully auto",
        )
    ):
        return 0
    # 默认自动
    if any(k in text for k in ("默认自动", "你看着办", "你定", "默认即可", "assume auto")):
        return 1
    # 多方案
    if any(k in text for k in ("给我选", "我来选", "多方案", "选项", "let me choose")):
        return 2
    # 只看不存
    if any(k in text for k in ("先别存", "不要保存", "看看再说", "echo", "先给我看")):
        return 3
    # 数字识别:"级别改 2" / "level 2" / "切到 2 档"
    import re

    m = re.search(
        r"(?:level|级别|档|模式|切到|调到|设)\s*[:＝=到为]?\s*([0-3])",
        text_lower,
    )
    if m:
        return int(m.group(1))
    return None


__all__ = [
    "DelegationLevel",
    "DelegationDecision",
    "LEVEL_LABELS",
    "should_ask_confirmation",
    "decide_for_write",
    "get_delegation_level",
    "set_delegation_level",
    "parse_level_from_natural_language",
]