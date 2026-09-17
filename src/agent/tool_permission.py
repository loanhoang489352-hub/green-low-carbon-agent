"""
工具级权限门(P16)

在路由级鉴权(auth_required)之外,给工具执行加一道风险门:
  - 工具声明 risk(low/medium/high,见 BaseTool.risk)
  - high 风险工具需用户确认(ConfirmationStore 里有 approved 记录)才执行
  - medium/low 直接放行(medium 的确认在 plan 层做,见 agent.confirmation)

默认所有工具 risk=low → 不改变现有行为(向后兼容)。
把某个工具 risk 改为 "high" 后,dispatch_tool_call 会在执行前拦截并返回 NEEDS_CONFIRMATION。
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional

from agent.confirmation import (
    ActionRisk,
    risk_for_action,
    get_confirmation_store,
)


class PermissionDecision(str, Enum):
    ALLOW = "allow"
    CONFIRM = "confirm"
    DENY = "deny"


def tool_risk(tool) -> ActionRisk:
    """读工具的 risk 声明;缺失则按 name/description 启发式兜底,默认 low。"""
    declared = getattr(tool, "risk", None)
    if declared:
        try:
            return ActionRisk(str(declared).lower())
        except ValueError:
            pass
    name = (getattr(tool, "name", "") or "").lower()
    desc = (getattr(tool, "description", "") or "").lower()
    return risk_for_action(f"{name} {desc}")


def decide(tool, ctx: Optional[Dict[str, Any]] = None) -> PermissionDecision:
    """工具执行前的权限裁决。默认 allow;high 风险 → confirm。"""
    if tool_risk(tool) == ActionRisk.HIGH:
        return PermissionDecision.CONFIRM
    return PermissionDecision.ALLOW


def is_confirmed(conf_id: str) -> bool:
    """查询某待确认是否已 approved"""
    conf = get_confirmation_store().get(conf_id)
    return conf is not None and conf.status == "approved"


def check_tool_permission(tool, ctx: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """执行前检查:返回 None 表示放行;否则返回错误信息(需确认)。"""
    if decide(tool, ctx) == PermissionDecision.CONFIRM:
        return "该操作涉及高风险,需要用户确认后才能执行"
    return None


__all__ = [
    "PermissionDecision",
    "tool_risk",
    "decide",
    "is_confirmed",
    "check_tool_permission",
]
