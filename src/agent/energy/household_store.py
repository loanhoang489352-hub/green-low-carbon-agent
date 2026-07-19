"""
P12.2: HouseholdProfile 持久化层

存 households.db (household_profiles / household_plans)
- save_profile(user_id, profile) — UPSERT
- load_profile(user_id) → HouseholdProfile or None
- save_plan_variant(user_id, plan_id, variant_id, plan, status)
- list_plans(user_id) → 历史方案(供 /api/energy/plan 查 variant)
- get_active_plan(user_id) → 用户的 active plan
- set_plan_status(plan_id, status)
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from paths import HOUSEHOLDS_DB

from .delegation import get_delegation_level
from .models import EnergyPlan, HouseholdProfile, PlanStatus

logger = logging.getLogger(__name__)


def _get_conn() -> sqlite3.Connection:
    from db.connection import get_connection

    return get_connection(str(HOUSEHOLDS_DB))


# ========== Profile 持久化 ==========


def save_profile(user_id: str, profile: HouseholdProfile) -> bool:
    """UPSERT household profile(连同 delegation_level 一起存)"""
    try:
        conn = _get_conn()
        now = datetime.now().isoformat()
        conn.execute(
            """
            INSERT INTO household_profiles
                (user_id, profile_json, delegation_level, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                profile_json = excluded.profile_json,
                delegation_level = excluded.delegation_level,
                updated_at = excluded.updated_at
            """,
            (
                user_id,
                json.dumps(profile.to_dict(), ensure_ascii=False),
                int(profile.delegation_level),
                now,
            ),
        )
        conn.commit()
        return True
    except Exception as e:
        logger.exception("[household_store] save_profile 失败: %s", e)
        return False


def load_profile(user_id: str) -> Optional[HouseholdProfile]:
    """读 household profile;若没有再尝试从 user_profiles 兜底迁移"""
    try:
        conn = _get_conn()
        row = conn.execute(
            "SELECT profile_json, delegation_level FROM household_profiles WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row:
            try:
                data = json.loads(row["profile_json"])
                # 兼容:画像里没有 delegation_level 字段就以 DB 列为权威
                if "delegation_level" not in data:
                    data["delegation_level"] = int(row["delegation_level"] or 1)
                data["user_id"] = user_id  # 强制一致
                return HouseholdProfile.from_dict(data)
            except Exception as e:
                logger.warning("[household_store] load_profile parse 失败: %s", e)
                return None
        return None
    except Exception as e:
        logger.exception("[household_store] load_profile 失败: %s", e)
        return None


# ========== Plan 持久化 ==========


def save_plan_variant(
    user_id: str,
    plan: EnergyPlan,
    variant_id: Optional[str] = None,
    status: Optional[str] = None,
) -> bool:
    """存一份 plan(可关联 variant_id)。variant_id 用于 level=2 时的多方案选择

    blocked plan 也存(status 强制 "blocked",警告字段保留在 plan_json 里)
    """
    try:
        conn = _get_conn()
        # blocked plan 强制 status="blocked"(不允许被外部覆盖)
        if getattr(plan, "blocked", False):
            effective_status = "blocked"
        else:
            effective_status = status or "draft"
        conn.execute(
            """
            INSERT INTO household_plans
                (plan_id, user_id, variant_id, plan_json, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(plan_id) DO UPDATE SET
                plan_json = excluded.plan_json,
                status = excluded.status,
                variant_id = excluded.variant_id
            """,
            (
                plan.id,
                user_id,
                variant_id,
                json.dumps(plan.to_dict(), ensure_ascii=False),
                effective_status,
                plan.created_at,
            ),
        )
        conn.commit()
        return True
    except Exception as e:
        logger.exception("[household_store] save_plan_variant 失败: %s", e)
        return False


def load_plan(plan_id: str) -> Optional[EnergyPlan]:
    """按 plan_id 加载;老 plan 没有 warning/blocked 字段时 backfill"""
    try:
        conn = _get_conn()
        row = conn.execute(
            "SELECT plan_json, user_id FROM household_plans WHERE plan_id = ?",
            (plan_id,),
        ).fetchone()
        if not row:
            return None
        data = json.loads(row["plan_json"])
        # 兼容旧 plan_json:backfill warning/blocked
        warning = data.get("warning")
        blocked = bool(data.get("blocked", False))
        return EnergyPlan(
            id=data["id"],
            user_id=data.get("user_id", row["user_id"]),
            profile_snapshot=HouseholdProfile.from_dict(data["profile_snapshot"]),
            actions=[],
            total_estimated_saving_cny=data.get("total_estimated_saving_cny", 0),
            total_estimated_saving_co2_kg=data.get("total_estimated_saving_co2_kg", 0),
            created_at=data.get("created_at", ""),
            status=data.get("status", "draft"),
            warning=warning,
            blocked=blocked,
        )
    except Exception as e:
        logger.exception("[household_store] load_plan 失败: %s", e)
        return None


def get_active_plan(user_id: str) -> Optional[EnergyPlan]:
    """取用户当前的 active plan"""
    try:
        conn = _get_conn()
        row = conn.execute(
            "SELECT plan_id FROM household_plans "
            "WHERE user_id = ? AND status = 'active' "
            "ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        if not row:
            return None
        return load_plan(row["plan_id"])
    except Exception as e:
        logger.warning("[household_store] get_active_plan 失败: %s", e)
        return None


def list_plans(user_id: str, limit: int = 20) -> List[Dict]:
    """列出用户的所有 plan(variant 也算一条记录)"""
    try:
        conn = _get_conn()
        rows = conn.execute(
            """
            SELECT plan_id, variant_id, status, created_at
            FROM household_plans
            WHERE user_id = ?
            ORDER BY created_at DESC LIMIT ?
            """,
            (user_id, int(limit)),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("[household_store] list_plans 失败: %s", e)
        return []


def set_plan_status(plan_id: str, status: str) -> bool:
    """改 plan 状态(draft → active → completed)"""
    try:
        conn = _get_conn()
        conn.execute(
            "UPDATE household_plans SET status = ? WHERE plan_id = ?",
            (status, plan_id),
        )
        conn.commit()
        return True
    except Exception as e:
        logger.warning("[household_store] set_plan_status 失败: %s", e)
        return False


__all__ = [
    "save_profile",
    "load_profile",
    "save_plan_variant",
    "load_plan",
    "get_active_plan",
    "list_plans",
    "set_plan_status",
]