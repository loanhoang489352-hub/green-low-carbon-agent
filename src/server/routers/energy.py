"""
P12.2: 节能规划 HTTP 路由 — 7 个端点

端点:
  POST /api/energy/profile         保存家庭画像(按 delegation_level 拦截)
  POST /api/energy/plan            生成节能方案(按 delegation_level 决定是否激活)
  GET  /api/energy/today           今日 3 件 + 1 提醒
  POST /api/energy/actions/{id}/complete   完成度登记
  GET  /api/energy/stats           累计节能 + 趋势
  POST /api/household/delegation   改委托级别
  GET  /api/energy/actions         列出 pending/done 行动

P5-D: 全部 auth_required=True
P5-E: 错误统一 APIError
P5-I: 写操作自动落 audit_log
P5-B: trace_id 已在 _dispatch 设
"""
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _current_user_id(handler, data: Dict) -> Optional[str]:
    """从鉴权结果拿 user_id(由 _dispatch 注入 handler.current_user)"""
    identity = getattr(handler, "current_user", None)
    if isinstance(identity, dict):
        uid = identity.get("user_id")
        if uid:
            return str(uid)
    # 兜底:body 里有 user_id(anon)
    return data.get("user_id")


def _audit(action: str, user_id: Optional[str], target: Optional[str], detail: Optional[Dict] = None) -> None:
    """P5-I 审计(失败不阻塞)"""
    try:
        from server.middleware.audit import record_audit

        record_audit(
            action=action,
            user_id=user_id,
            target=target,
            status_code=200,
            detail=json.dumps(detail, ensure_ascii=False) if detail else None,
        )
    except Exception:
        pass


def _safe_int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


# ========== Profile 保存(按 delegation_level 拦截) ==========


def _save_profile_impl(handler, data: Dict, user_id: str) -> Dict[str, Any]:
    """核心:按 delegation_level 处理 profile 保存"""
    from agent.energy.delegation import (
        decide_for_write,
        get_delegation_level,
    )
    from agent.energy.household_store import save_profile
    from agent.energy.models import HouseholdProfile

    level = get_delegation_level(user_id)
    decision = decide_for_write(level)

    # 构造 profile 对象(用 HouseholdProfile.from_dict 容错)
    raw = dict(data or {})
    raw.setdefault("user_id", user_id)
    # P12.2 fix: 用 DB 当前 level(避免 dataclass 默认 1 覆盖用户在 delegation 端点的设置)
    raw.setdefault("delegation_level", level)
    profile = HouseholdProfile.from_dict(raw)

    # 委托级别拦截
    if decision.echo_only:
        # Level 3: 不存,只 echo
        _audit(
            "energy.profile.echo",
            user_id,
            "household_profile",
            {"level": level, "echoed": True},
        )
        return {
            "ok": True,
            "delegation_level": level,
            "persisted": False,
            "echo_only": True,
            "confirmation_required": True,
            "message": "Level 3: 仅 echo,未持久化",
            "profile_echo": profile.to_dict(),
        }

    if decision.variant_mode:
        # Level 2: 给 3 个 variants,等用户选
        variants = _build_profile_variants(profile)
        _audit(
            "energy.profile.variants",
            user_id,
            "household_profile",
            {"level": level, "variants": len(variants)},
        )
        return {
            "ok": True,
            "delegation_level": level,
            "persisted": False,
            "variant_mode": True,
            "confirmation_required": True,
            "message": "Level 2: 请选择 1 个画像变体",
            "variants": variants,
            "profile_echo": profile.to_dict(),
        }

    # Level 0/1: 直接存
    saved = save_profile(user_id, profile)
    _audit(
        "energy.profile.save",
        user_id,
        "household_profile",
        {"level": level, "persisted": saved, "city": profile.city},
    )
    return {
        "ok": True,
        "delegation_level": level,
        "persisted": saved,
        "confirmation_required": False,
        "profile": profile.to_dict(),
        "message": (
            "已自动激活"
            if level == 0
            else "已保存(默认自动)"
        ),
    }


def _build_profile_variants(base) -> List[Dict[str, Any]]:
    """Level 2 时生成 3 个变体(侧重不同)

    变体 1: 面积小,电器少 → 节省潜力低但省钱快
    变体 2: 中等(默认值)
    变体 3: 面积大,电器多 → 节省潜力高但需要大动作
    """
    from agent.energy.models import HouseholdProfile

    v1 = HouseholdProfile.from_dict({**base.to_dict()})
    v1.home_size_sqm = max(50.0, base.home_size_sqm * 0.7)
    v1.appliances = [a for a in (base.appliances or [])[:3]] or ["空调", "热水器", "冰箱"]

    v2 = HouseholdProfile.from_dict({**base.to_dict()})  # 默认

    v3 = HouseholdProfile.from_dict({**base.to_dict()})
    v3.home_size_sqm = base.home_size_sqm * 1.3
    v3.appliances = list(set((base.appliances or []) + ["空调", "热水器", "冰箱", "洗衣机", "洗碗机"]))

    return [
        {
            "variant_id": "small_apartment",
            "title": "小户型(省钱快)",
            "description": "电器少,行动少,省钱快",
            "profile": v1.to_dict(),
        },
        {
            "variant_id": "balanced",
            "title": "标准家庭(平衡)",
            "description": "你提供的默认画像",
            "profile": v2.to_dict(),
        },
        {
            "variant_id": "large_household",
            "title": "大户家庭(潜力高)",
            "description": "面积大电器多,节省潜力高",
            "profile": v3.to_dict(),
        },
    ]


# ========== 方案生成(按 delegation_level 拦截) ==========


def _generate_plan_impl(handler, data: Dict, user_id: str) -> Dict[str, Any]:
    """核心:生成 plan(按 delegation_level 决定激活 / 多 variant / echo)"""
    from agent.energy.delegation import decide_for_write, get_delegation_level
    from agent.energy.household_store import (
        get_active_plan,
        load_profile,
        save_plan_variant,
        set_plan_status,
    )
    from agent.energy.models import HouseholdProfile, PlanStatus
    from agent.energy.planner import EnergyPlanner

    level = get_delegation_level(user_id)
    decision = decide_for_write(level)

    # 优先用 body 里的 profile,否则读 DB
    if data and "profile" in data and isinstance(data["profile"], dict):
        profile = HouseholdProfile.from_dict(
            {**data["profile"], "user_id": user_id}
        )
    else:
        profile = load_profile(user_id)
        if profile is None:
            # 用默认画像
            profile = HouseholdProfile(user_id=user_id)

    planner = EnergyPlanner()

    # Level 3: 不存只 echo
    if decision.echo_only:
        plan = planner.generate_plan(profile)
        if plan.blocked:
            _audit(
                "energy.plan.echo.blocked",
                user_id,
                plan.id,
                {"level": level, "warning": plan.warning},
            )
            return {
                "ok": False,
                "delegation_level": level,
                "persisted": False,
                "echo_only": True,
                "blocked": True,
                "warning": plan.warning,
                "plan": None,
                "message": "画像不完整,无法预览方案 — 请补充信息",
            }
        card = planner.generate_today_card(plan)
        _audit(
            "energy.plan.echo",
            user_id,
            plan.id,
            {"level": level},
        )
        return {
            "ok": True,
            "delegation_level": level,
            "persisted": False,
            "echo_only": True,
            "confirmation_required": True,
            "message": "Level 3: 仅查看,未激活",
            "plan": plan.to_dict(),
            "today_card": card.to_dict(),
        }

    # Level 2: 给 3 个 plan(省钱 / 减碳 / 易执行),让用户选
    if decision.variant_mode:
        base_plan = planner.generate_plan(profile)
        if base_plan.blocked:
            _audit(
                "energy.plan.variants.blocked",
                user_id,
                base_plan.id,
                {"level": level, "warning": base_plan.warning},
            )
            return {
                "ok": False,
                "delegation_level": level,
                "persisted": False,
                "variant_mode": True,
                "blocked": True,
                "warning": base_plan.warning,
                "variants": [],
                "profile_echo": profile.to_dict(),
                "message": "画像不完整,无法生成方案候选 — 请补充信息",
            }
        plans = _build_plan_variants(planner, profile)
        _audit(
            "energy.plan.variants",
            user_id,
            "household_plan",
            {"level": level, "variants": len(plans)},
        )
        return {
            "ok": True,
            "delegation_level": level,
            "persisted": False,
            "variant_mode": True,
            "confirmation_required": True,
            "message": "Level 2: 请选择 1 个方案",
            "variants": plans,
            "profile_echo": profile.to_dict(),
        }

    # Level 0/1: 生成 1 个 + 存
    plan = planner.generate_plan(profile)

    # 守卫拦截 → blocked plan(200 + 显式标记,UI 提示重填画像)
    if plan.blocked:
        _audit(
            "energy.plan.blocked",
            user_id,
            plan.id,
            {"level": level, "warning": plan.warning},
        )
        return {
            "ok": False,
            "delegation_level": level,
            "persisted": False,
            "blocked": True,
            "warning": plan.warning,
            "plan": None,
            "message": "画像不完整,无法生成节能方案 — 请补充信息",
        }

    card = planner.generate_today_card(plan)
    # Level 0 自动激活;Level 1 默认 draft,等用户激活
    target_status = (
        PlanStatus.ACTIVE.value if level == 0 else PlanStatus.DRAFT.value
    )
    save_plan_variant(
        user_id=user_id,
        plan=plan,
        variant_id="default",
        status=target_status,
    )
    _audit(
        "energy.plan.save",
        user_id,
        plan.id,
        {"level": level, "status": target_status},
    )
    msg = "已激活" if target_status == PlanStatus.ACTIVE.value else "已生成(待你激活)"
    return {
        "ok": True,
        "delegation_level": level,
        "persisted": True,
        "confirmation_required": (level == 1),
        "message": msg,
        "plan": plan.to_dict(),
        "today_card": card.to_dict(),
        "status": target_status,
    }


def _build_plan_variants(planner, profile) -> List[Dict[str, Any]]:
    """Level 2: 生成 3 个 plan 变体

    - 省钱优先:电/燃气便宜的高节省 actions
    - 减碳优先:CO2 减少最多的 actions
    - 易执行:全 difficulty=1 的 actions
    """
    from agent.energy.models import EnergyAction

    base_plan = planner.generate_plan(profile)

    def _variant_by_score(actions, top_n=8):
        return actions[:top_n]

    # 省钱:按 estimated_saving_cny 降序
    money_actions = sorted(
        base_plan.actions,
        key=lambda a: -a.estimated_saving_cny,
    )
    # 减碳:按 estimated_saving_co2_kg 降序
    co2_actions = sorted(
        base_plan.actions,
        key=lambda a: -a.estimated_saving_co2_kg,
    )
    # 易执行:difficulty=1 优先,再按 cny 排序
    easy_actions = sorted(
        base_plan.actions,
        key=lambda a: (a.difficulty, -a.estimated_saving_cny),
    )

    money_picked = _variant_by_score(money_actions)
    co2_picked = _variant_by_score(co2_actions)
    easy_picked = _variant_by_score(easy_actions)

    def _to_variant(variant_id: str, title: str, desc: str, actions: List[EnergyAction]):
        return {
            "variant_id": variant_id,
            "title": title,
            "description": desc,
            "total_estimated_saving_cny": round(
                sum(a.estimated_saving_cny for a in actions), 2
            ),
            "total_estimated_saving_co2_kg": round(
                sum(a.estimated_saving_co2_kg for a in actions), 3
            ),
            "actions": [a.to_dict() for a in actions],
        }

    return [
        _to_variant(
            "money_first",
            "省钱优先",
            "选预计省钱最多的行动",
            money_picked,
        ),
        _to_variant(
            "co2_first",
            "减碳优先",
            "选预计减排最多的行动",
            co2_picked,
        ),
        _to_variant(
            "easy_first",
            "易执行",
            "只选难度低的行动(difficulty=1)",
            easy_picked,
        ),
    ]


# ========== 路由注册 ==========


def register_energy_routes(registry) -> None:
    """注册 7 个能源端点"""

    from server.errors import APIError

    # ----- POST /api/energy/profile -----

    def energy_profile(handler, data):
        user_id = _current_user_id(handler, data)
        if not user_id:
            raise APIError("UNAUTHORIZED", "需要登录")
        # 即使 level=3 也允许 echo,不算 forbidden
        result = _save_profile_impl(handler, data, user_id)
        handler.send_json(result)

    # ----- POST /api/energy/plan -----

    def energy_plan(handler, data):
        user_id = _current_user_id(handler, data)
        if not user_id:
            raise APIError("UNAUTHORIZED", "需要登录")
        result = _generate_plan_impl(handler, data, user_id)
        handler.send_json(result)

    # ----- GET /api/energy/today -----

    def energy_today(handler, data):
        user_id = _current_user_id(handler, data)
        if not user_id:
            raise APIError("UNAUTHORIZED", "需要登录")
        # 优先 active plan,否则生成一个新 plan(不存)
        from agent.energy.household_store import get_active_plan, load_profile
        from agent.energy.models import HouseholdProfile
        from agent.energy.planner import EnergyPlanner

        plan = get_active_plan(user_id)
        if plan is None:
            profile = load_profile(user_id) or HouseholdProfile(user_id=user_id)
            planner = EnergyPlanner()
            plan = planner.generate_plan(profile)
        else:
            # plan actions 在 household_plans 里没存,需要重建
            from agent.energy.household_store import load_profile
            profile = load_profile(user_id) or HouseholdProfile(user_id=user_id)
            planner = EnergyPlanner()
            plan = planner.generate_plan(profile)

        # 守卫拦截 → blocked(返回 200 + 显式标记)
        if plan.blocked:
            handler.send_json(
                {
                    "ok": False,
                    "user_id": user_id,
                    "blocked": True,
                    "warning": plan.warning,
                    "plan": None,
                    "today_card": None,
                    "plan_id": plan.id,
                    "message": "画像不完整,无法生成今日行动卡 — 请补充信息",
                }
            )
            return

        card = planner.generate_today_card(plan)
        handler.send_json(
            {
                "ok": True,
                "user_id": user_id,
                "today_card": card.to_dict(),
                "plan_id": plan.id,
            }
        )

    # ----- POST /api/energy/actions/{action_id}/complete -----

    def energy_action_complete(handler, data):
        user_id = _current_user_id(handler, data)
        if not user_id:
            raise APIError("UNAUTHORIZED", "需要登录")
        # 从 path 抽 action_id
        parts = (handler.path or "").strip("/").split("/")
        action_id = parts[-2] if len(parts) >= 4 else None
        if not action_id:
            raise APIError("BAD_REQUEST", "action_id required in path")
        completion_level = (data or {}).get("completion_level", "none")
        plan_id = (data or {}).get("plan_id")
        note = (data or {}).get("note")
        action_date = (data or {}).get("action_date")
        # estimated_saving_* 可选(查 action 详情或外部传入)
        from agent.energy.tracker import get_action_tracker

        tracker = get_action_tracker()
        # 优先从 active plan 找 action 元数据
        estimated_cny = 0.0
        estimated_kwh = 0.0
        estimated_co2 = 0.0
        try:
            from agent.energy.household_store import get_active_plan
            active = get_active_plan(user_id)
            if active:
                from agent.energy.policies import appliance_potential
                # 先从 energy_plans.db(老表)找
                from agent.energy.planner import EnergyPlanner
                ep = EnergyPlanner()
                db_plans = ep.list_plans(user_id)
                for p in db_plans:
                    for a in p.actions:
                        if a.id == action_id:
                            estimated_cny = a.estimated_saving_cny
                            estimated_kwh = a.estimated_saving_kwh
                            estimated_co2 = a.estimated_saving_co2_kg
                            if not plan_id:
                                plan_id = p.id
                            break
                    if estimated_cny:
                        break
        except Exception:
            pass
        # body 显式传入的覆盖
        if "estimated_saving_cny" in (data or {}):
            estimated_cny = float(data["estimated_saving_cny"])
        if "estimated_saving_kwh" in (data or {}):
            estimated_kwh = float(data["estimated_saving_kwh"])
        if "estimated_saving_co2_kg" in (data or {}):
            estimated_co2 = float(data["estimated_saving_co2_kg"])

        result = tracker.mark_completion_extended(
            user_id=user_id,
            action_id=action_id,
            completion_level=completion_level,
            plan_id=plan_id,
            action_date=action_date,
            estimated_saving_cny=estimated_cny,
            estimated_saving_kwh=estimated_kwh,
            estimated_saving_co2_kg=estimated_co2,
            note=note,
        )
        if not result.get("ok"):
            raise APIError("BAD_REQUEST", result.get("error", "completion failed"))
        handler.send_json(result)

    # ----- GET /api/energy/stats -----

    def energy_stats(handler, data):
        user_id = _current_user_id(handler, data)
        if not user_id:
            raise APIError("UNAUTHORIZED", "需要登录")
        # 解析 query string (?period=week)
        from urllib.parse import urlparse, parse_qs

        q = parse_qs(urlparse(handler.path).query)
        period = (
            (q.get("period", [None])[0] if q.get("period") else None)
            or (data or {}).get("period")
            or "week"
        )
        from agent.energy.tracker import get_action_tracker

        tracker = get_action_tracker()
        stats = tracker.get_stats(user_id, period=period)
        handler.send_json(stats)

    # ----- POST /api/household/delegation -----

    def household_delegation(handler, data):
        user_id = _current_user_id(handler, data)
        if not user_id:
            raise APIError("UNAUTHORIZED", "需要登录")
        new_level = _safe_int((data or {}).get("new_level"), default=-1)
        if new_level not in (0, 1, 2, 3):
            raise APIError(
                "VALIDATION",
                f"new_level must be 0/1/2/3, got {new_level}",
            )
        from agent.energy.delegation import (
            LEVEL_LABELS,
            get_delegation_level,
            set_delegation_level,
        )

        old = get_delegation_level(user_id)
        ok = set_delegation_level(user_id, new_level)
        if not ok:
            raise APIError("INTERNAL", "set_delegation_level failed")
        _audit(
            "household.delegation.change",
            user_id,
            "delegation_level",
            {"old": old, "new": new_level},
        )
        handler.send_json(
            {
                "ok": True,
                "user_id": user_id,
                "old_level": old,
                "new_level": new_level,
                "label": LEVEL_LABELS.get(new_level, ""),
                "message": f"委托级别已从 {LEVEL_LABELS.get(old, '')} 改为 {LEVEL_LABELS.get(new_level, '')}",
            }
        )

    # ----- GET /api/energy/actions -----

    def energy_actions_list(handler, data):
        user_id = _current_user_id(handler, data)
        if not user_id:
            raise APIError("UNAUTHORIZED", "需要登录")
        # 解析 query string (?status=done&limit=50)
        from urllib.parse import urlparse, parse_qs

        q = parse_qs(urlparse(handler.path).query)
        status = (
            (q.get("status", [None])[0] if q.get("status") else None)
            or (data or {}).get("status")
            or "pending"
        )
        limit_raw = (
            q.get("limit", [None])[0] if q.get("limit") else None
        ) or (data or {}).get("limit") or 50
        limit = _safe_int(limit_raw, default=50)
        from agent.energy.tracker import get_action_tracker

        tracker = get_action_tracker()
        items = tracker.list_actions(user_id, status=status, limit=limit)
        handler.send_json(
            {
                "ok": True,
                "user_id": user_id,
                "status": status,
                "count": len(items),
                "items": items,
            }
        )

    # ----- 注册(全部 auth_required=True,P5-D) -----

    registry.add_route(
        "POST",
        "/api/energy/profile",
        energy_profile,
        auth_required=True,
        description="保存家庭画像(按 delegation_level 拦截)",
    )
    registry.add_route(
        "POST",
        "/api/energy/plan",
        energy_plan,
        auth_required=True,
        description="生成节能方案",
    )
    registry.add_route(
        "GET",
        "/api/energy/today",
        energy_today,
        auth_required=True,
        description="今日行动卡",
    )
    registry.add_route(
        "POST",
        "^/api/energy/actions/",  # /api/energy/actions/{id}/complete
        energy_action_complete,
        auth_required=True,
        description="标记行动完成度",
    )
    registry.add_route(
        "GET",
        "/api/energy/stats",
        energy_stats,
        auth_required=True,
        description="累计节能 + 趋势",
    )
    registry.add_route(
        "POST",
        "/api/household/delegation",
        household_delegation,
        auth_required=True,
        description="改委托级别(0/1/2/3)",
    )
    registry.add_route(
        "GET",
        "/api/energy/actions",
        energy_actions_list,
        auth_required=True,
        description="列出节能行动(pending/done)",
    )