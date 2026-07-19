"""
P12.4: 节能规划 Skill

把 `EnergyPlanner` + `HouseholdProfileStore` + `ActionTracker` 组合成一个标准 Skill,
让 LLM 能识别节能规划类查询,自动调用并产出可执行的家庭节能方案。

设计要点:
  - 严格无幻觉:数值字段都从 APPLIANCE_SAVINGS 模板生成,不二次创作
  - 委托级别 0-3 决策:是否自动落库、是否生成多 variant、是否 echo only
  - 今日行动卡:固定 5 字段(目标 / 方案 / 提醒 / 时间 / 判定)
  - 守卫接口:GUARD_NO_APPLIANCES / GUARD_UNKNOWN_CITY / GUARD_ZERO_USAGE /
    GUARD_EXTREME_VALUES 失败时返 blocked plan,绝不"瞎编"
"""
from __future__ import annotations

import logging
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

# 让 src/ 在 import 路径中(项目根的子目录)
_script_path = Path(__file__).resolve()
_project_root = _script_path.parent.parent.parent.parent
if str(_project_root / "src") not in sys.path:
    sys.path.insert(0, str(_project_root / "src"))

from agent.tools.base import BaseTool, ToolResult  # noqa: E402
from agent.skills.skill import Skill, SkillContext  # noqa: E402

_log = logging.getLogger(__name__)


# ============ 节能规划专用 Tool 实现 ============


class HouseholdProfileTool(BaseTool):
    """家庭画像读写工具"""

    @property
    def name(self) -> str:
        return "household_profile"

    @property
    def description(self) -> str:
        return "读写家庭画像(人数/面积/城市/家电/月费用/委托级别),节能规划的输入端。"

    @property
    def parameters(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "user_id",
                "type": "string",
                "description": "用户ID",
                "required": True,
            },
            {
                "name": "operation",
                "type": "string",
                "description": "read | write",
                "required": False,
                "default": "read",
            },
            {
                "name": "profile",
                "type": "object",
                "description": "画像 dict(write 时必填)",
                "required": False,
                "default": None,
            },
        ]

    def execute(self, **kwargs) -> ToolResult:
        import time

        start = time.time()
        user_id = kwargs.get("user_id", "")
        operation = (kwargs.get("operation") or "read").lower()
        profile = kwargs.get("profile")

        if not user_id:
            return ToolResult(
                success=False, error="缺少 user_id", execution_time=time.time() - start
            )

        try:
            from agent.energy.household_store import (
                load_profile,
                save_profile,
            )

            if operation == "read":
                p = load_profile(user_id)
                if p is None:
                    # 兜底:返回一个空画像的描述
                    return ToolResult(
                        success=True,
                        data={"user_id": user_id, "profile": None,
                              "note": "用户尚未建立画像,首次规划时会触发 blocked"},
                        execution_time=time.time() - start,
                    )
                return ToolResult(
                    success=True,
                    data={"user_id": user_id, "profile": p.to_dict()},
                    execution_time=time.time() - start,
                )

            if operation == "write":
                if not profile:
                    return ToolResult(
                        success=False,
                        error="write 操作必须传 profile",
                        execution_time=time.time() - start,
                    )
                from agent.energy.models import HouseholdProfile

                if isinstance(profile, HouseholdProfile):
                    p = profile
                else:
                    p = HouseholdProfile.from_dict(dict(profile))
                p.user_id = user_id
                ok = save_profile(user_id, p)
                return ToolResult(
                    success=ok,
                    data={"user_id": user_id, "profile": p.to_dict(), "saved": ok},
                    error=None if ok else "save_profile 失败",
                    execution_time=time.time() - start,
                )

            return ToolResult(
                success=False,
                error=f"未知 operation: {operation}",
                execution_time=time.time() - start,
            )
        except Exception as e:
            _log.exception("[EnergyPlanning] HouseholdProfileTool 失败: %s", e)
            return ToolResult(
                success=False,
                error=f"家庭画像操作失败: {e}",
                execution_time=time.time() - start,
            )


class EnergyPlannerTool(BaseTool):
    """节能方案生成工具(无幻觉 + 守卫契约)"""

    @property
    def name(self) -> str:
        return "energy_planner"

    @property
    def description(self) -> str:
        return (
            "根据家庭画像生成 5-12 条可执行节能方案(空调温度/电热水器时段/LED 替换/"
            "低流量花洒/修滴漏/燃气保温等),含数值(元/kg CO2)溯源。今日行动卡自动抽 3 件易做。"
        )

    @property
    def parameters(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "profile",
                "type": "object",
                "description": "家庭画像 dict(HouseholdProfile 字段)",
                "required": True,
            },
            {
                "name": "save_plan",
                "type": "boolean",
                "description": "是否落库(默认 False;level=0/1 自动 True)",
                "required": False,
                "default": False,
            },
            {
                "name": "delegation_level",
                "type": "number",
                "description": "委托级别 0/1/2/3(默认 1)",
                "required": False,
                "default": 1,
            },
        ]

    def execute(self, **kwargs) -> ToolResult:
        import time

        start = time.time()
        profile = kwargs.get("profile")
        save_plan = bool(kwargs.get("save_plan", False))
        delegation_level = int(kwargs.get("delegation_level", 1) or 1)

        if not profile:
            return ToolResult(
                success=False, error="缺少 profile", execution_time=time.time() - start
            )

        try:
            from agent.energy.planner import EnergyPlanner
            from agent.energy.models import HouseholdProfile, PlanStatus
            from agent.energy.delegation import (
                decide_for_write,
                should_ask_confirmation,
            )

            if isinstance(profile, HouseholdProfile):
                p = profile
            else:
                p = HouseholdProfile.from_dict(dict(profile))

            planner = EnergyPlanner()
            plan = planner.generate_plan(p)

            decision = decide_for_write(delegation_level)
            persisted = False

            # blocked plan 也存一份(审计 + history),但 status 强制 "blocked"
            if plan.blocked:
                try:
                    planner.save_plan(plan)
                    persisted = True
                except Exception:
                    pass
            else:
                # 0/1 自动落库 + 激活;2 仅生成 variant 不落;3 echo 不落
                if decision.should_persist and (save_plan or delegation_level in (0, 1)):
                    try:
                        planner.save_plan(plan)
                        persisted = True
                    except Exception as e:
                        _log.warning("[EnergyPlanning] save_plan 失败: %s", e)

            # 今日行动卡:仅 normal plan 生成;blocked 不抽卡
            card = None
            if not plan.blocked:
                card = planner.generate_today_card(plan)

            return ToolResult(
                success=True,
                data={
                    "plan": plan.to_dict(),
                    "today_card": card.to_dict() if card else None,
                    "persisted": persisted,
                    "delegation_level": delegation_level,
                    "decision": {
                        "should_persist": decision.should_persist,
                        "confirmation_required": decision.confirmation_required,
                        "variant_mode": decision.variant_mode,
                        "echo_only": decision.echo_only,
                    },
                    "should_ask_confirmation": should_ask_confirmation(delegation_level),
                },
                execution_time=time.time() - start,
            )
        except Exception as e:
            _log.exception("[EnergyPlanning] EnergyPlannerTool 失败: %s", e)
            return ToolResult(
                success=False,
                error=f"节能方案生成失败: {e}",
                execution_time=time.time() - start,
            )


class EnergyActionTrackerTool(BaseTool):
    """节能行动完成度跟踪工具(streak + 累计)"""

    @property
    def name(self) -> str:
        return "action_tracker"

    @property
    def description(self) -> str:
        return (
            "记录今日节能行动的完成度(full/partial/none),返回 streak 与累计节省;"
            "支持查 stats(week/month/year/all)和今日已完成列表。"
        )

    @property
    def parameters(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "operation",
                "type": "string",
                "description": "mark | stats | today | pending",
                "required": True,
            },
            {
                "name": "user_id",
                "type": "string",
                "description": "用户ID",
                "required": True,
            },
            {
                "name": "action_id",
                "type": "string",
                "description": "行动 ID(mark 时必填,如 ac_temp_up_1c)",
                "required": False,
                "default": "",
            },
            {
                "name": "completion_level",
                "type": "string",
                "description": "full | partial | none(mark 时必填)",
                "required": False,
                "default": "none",
            },
            {
                "name": "plan_id",
                "type": "string",
                "description": "方案 ID(可选,mark 时)",
                "required": False,
                "default": "",
            },
            {
                "name": "period",
                "type": "string",
                "description": "week/month/year/all(stats 时)",
                "required": False,
                "default": "all",
            },
            {
                "name": "note",
                "type": "string",
                "description": "备注(mark 时自动 PII 脱敏)",
                "required": False,
                "default": "",
            },
        ]

    def execute(self, **kwargs) -> ToolResult:
        import time

        start = time.time()
        operation = (kwargs.get("operation") or "").lower()
        user_id = kwargs.get("user_id", "")

        if not operation:
            return ToolResult(
                success=False, error="缺少 operation", execution_time=time.time() - start
            )
        if not user_id:
            return ToolResult(
                success=False, error="缺少 user_id", execution_time=time.time() - start
            )

        try:
            from agent.energy.tracker import get_action_tracker

            tracker = get_action_tracker()

            if operation == "mark":
                action_id = kwargs.get("action_id", "")
                completion_level = kwargs.get("completion_level", "none")
                plan_id = kwargs.get("plan_id") or None
                note = kwargs.get("note") or None
                if not action_id:
                    return ToolResult(
                        success=False,
                        error="mark 操作必须传 action_id",
                        execution_time=time.time() - start,
                    )
                result = tracker.mark_completion_extended(
                    user_id=user_id,
                    action_id=action_id,
                    completion_level=completion_level,
                    plan_id=plan_id,
                    note=note,
                )
                return ToolResult(
                    success=result.get("ok", False),
                    data=result,
                    error=result.get("error"),
                    execution_time=time.time() - start,
                )

            if operation == "stats":
                period = kwargs.get("period", "all")
                stats = tracker.get_stats(user_id=user_id, period=period)
                return ToolResult(
                    success=True,
                    data=stats,
                    execution_time=time.time() - start,
                )

            if operation == "today":
                today = tracker.get_today_completions(user_id)
                return ToolResult(
                    success=True,
                    data={"user_id": user_id, "today": today,
                          "count": len(today)},
                    execution_time=time.time() - start,
                )

            if operation == "pending":
                limit = int(kwargs.get("limit", 50) or 50)
                pending = tracker.list_actions(user_id=user_id,
                                               status="pending",
                                               limit=limit)
                return ToolResult(
                    success=True,
                    data={"user_id": user_id, "pending": pending,
                          "count": len(pending)},
                    execution_time=time.time() - start,
                )

            return ToolResult(
                success=False,
                error=f"未知 operation: {operation}",
                execution_time=time.time() - start,
            )
        except Exception as e:
            _log.exception("[EnergyPlanning] ActionTracker 失败: %s", e)
            return ToolResult(
                success=False,
                error=f"行动跟踪失败: {e}",
                execution_time=time.time() - start,
            )


# ============ Skill 主体 ============


class EnergyPlanningSkill(Skill):
    """节能规划 Skill

    把"用户想节能"类查询直接路由到家庭画像 + 方案生成 + 行动跟踪。
    LLM 看到 `when_to_use` 命中即应优先选本 Skill。

    委托级别契约(参考 delegation.py):
      0: 完全自动 — 写操作直接落库 + 默认激活
      1: 默认自动 — 写操作直接落库
      2: 多方案   — 暂不持久化,等用户确认
      3: 只看不存 — 仅 echo,绝不入库
    """

    name = "energy_planning"
    description = (
        "根据家庭画像生成可执行的节能方案(节水/节电/节气),"
        "含幻觉防火墙 + 委托级别 0-3 控制,自动落今日行动卡"
    )
    category = "lifestyle"
    version = "1.0.0"
    when_to_use = (
        "节能 / 节能规划 / 节水 / 节电 / 节气 / 家庭能源 / 月度节能 / 环保方案 / "
        "节省电费 / 降碳 / 减碳 / 绿色生活 / 低碳 / 节能方案 / 电费太高 / "
        "电费高 / 水费 / 燃气费 / 月用电 / 空调温度 / 电热水器 / LED / 待机功耗 / "
        "滴漏 / 漏气 / 保温 / 花洒 / 节能 / 节能技巧 / 家庭节能 / "
        "energy / saving / electricity / utility / power / water / gas / "
        "energy efficiency / utility bill / save energy / home energy / "
        "appliance / appliance saving / monthly bill / reduce carbon / eco home"
    )
    allowed_tools: List[str] = [
        "household_profile",
        "energy_planner",
        "action_tracker",
    ]

    @property
    def tools(self) -> List[BaseTool]:
        return [
            HouseholdProfileTool(),
            EnergyPlannerTool(),
            EnergyActionTrackerTool(),
        ]

    def execute(self, context: SkillContext) -> ToolResult:
        import time

        start = time.time()
        user_id = context.user_id or context.metadata.get("user_id", "")
        operation = (context.metadata.get("operation") or "plan").lower()
        delegation_level = int(
            context.metadata.get("delegation_level", 1) or 1
        )

        if not user_id:
            return ToolResult(
                success=False,
                error="缺少 user_id",
                execution_time=time.time() - start,
            )

        try:
            # 1. 拿 / 加载家庭画像
            hp_tool = HouseholdProfileTool()
            profile_result = hp_tool.execute(user_id=user_id, operation="read")
            profile_dict: Optional[Dict[str, Any]] = None
            if profile_result.success and profile_result.data:
                profile_dict = profile_result.data.get("profile")

            # 用户没画像 → 提示先建立画像
            if not profile_dict:
                return ToolResult(
                    success=True,
                    data={
                        "status": "no_profile",
                        "user_id": user_id,
                        "hint": "请先回答几个家庭画像问题(人数/面积/城市/家电/月费用),"
                                "再生成节能方案",
                        "operations": ["stats", "today", "pending"],
                    },
                    execution_time=time.time() - start,
                )

            # 2. 不同操作走不同分支
            if operation in ("plan", "today_card", "今日", "规划", "方案", "card"):
                ep_tool = EnergyPlannerTool()
                plan_result = ep_tool.execute(
                    profile=profile_dict,
                    save_plan=delegation_level in (0, 1),
                    delegation_level=delegation_level,
                )
                if not plan_result.success:
                    return ToolResult(
                        success=False,
                        error=plan_result.error,
                        execution_time=time.time() - start,
                    )

                # blocked plan 单独返
                plan_dict = plan_result.data["plan"] if plan_result.data else {}
                if plan_dict.get("blocked"):
                    return ToolResult(
                        success=True,
                        data={
                            "status": "blocked",
                            "user_id": user_id,
                            "warning": plan_dict.get("warning"),
                            "delegation_level": delegation_level,
                            "operations": ["stats", "today", "pending"],
                        },
                        execution_time=time.time() - start,
                    )

                # 3. 委托级别 2 / 3 → 不落库,只 echo
                persisted = plan_result.data.get("persisted", False)

                return ToolResult(
                    success=True,
                    data={
                        "status": "ok",
                        "user_id": user_id,
                        "plan": plan_dict,
                        "today_card": plan_result.data.get("today_card"),
                        "persisted": persisted,
                        "delegation_level": delegation_level,
                        "decision": plan_result.data.get("decision"),
                        "should_ask_confirmation": plan_result.data.get(
                            "should_ask_confirmation"
                        ),
                        "operations": ["stats", "today", "pending", "plan"],
                    },
                    execution_time=time.time() - start,
                )

            if operation in ("stats", "统计"):
                at_tool = EnergyActionTrackerTool()
                period = context.metadata.get("period", "all")
                stats_result = at_tool.execute(
                    operation="stats",
                    user_id=user_id,
                    period=period,
                )
                return ToolResult(
                    success=stats_result.success,
                    data={
                        "status": "ok",
                        "user_id": user_id,
                        "stats": stats_result.data,
                    },
                    error=stats_result.error,
                    execution_time=time.time() - start,
                )

            if operation in ("today", "今日完成"):
                at_tool = EnergyActionTrackerTool()
                today_result = at_tool.execute(
                    operation="today",
                    user_id=user_id,
                )
                return ToolResult(
                    success=today_result.success,
                    data={
                        "status": "ok",
                        "user_id": user_id,
                        "today": today_result.data,
                    },
                    error=today_result.error,
                    execution_time=time.time() - start,
                )

            if operation in ("pending", "待办"):
                at_tool = EnergyActionTrackerTool()
                pending_result = at_tool.execute(
                    operation="pending",
                    user_id=user_id,
                    limit=int(context.metadata.get("limit", 50) or 50),
                )
                return ToolResult(
                    success=pending_result.success,
                    data={
                        "status": "ok",
                        "user_id": user_id,
                        "pending": pending_result.data,
                    },
                    error=pending_result.error,
                    execution_time=time.time() - start,
                )

            if operation in ("mark", "标记"):
                at_tool = EnergyActionTrackerTool()
                mark_result = at_tool.execute(
                    operation="mark",
                    user_id=user_id,
                    action_id=context.metadata.get("action_id", ""),
                    completion_level=context.metadata.get(
                        "completion_level", "none"
                    ),
                    plan_id=context.metadata.get("plan_id"),
                    note=context.metadata.get("note"),
                )
                return ToolResult(
                    success=mark_result.success,
                    data={
                        "status": "ok",
                        "user_id": user_id,
                        "mark_result": mark_result.data,
                    },
                    error=mark_result.error,
                    execution_time=time.time() - start,
                )

            # 默认操作:plan
            return ToolResult(
                success=False,
                error=f"未知 operation: {operation} (可用: plan / stats / today / pending / mark)",
                execution_time=time.time() - start,
            )
        except Exception as e:
            _log.exception("[EnergyPlanning] execute 失败: %s", e)
            return ToolResult(
                success=False,
                error=f"节能规划 Skill 执行失败: {e}",
                execution_time=time.time() - start,
            )


__all__ = [
    "HouseholdProfileTool",
    "EnergyPlannerTool",
    "EnergyActionTrackerTool",
    "EnergyPlanningSkill",
]