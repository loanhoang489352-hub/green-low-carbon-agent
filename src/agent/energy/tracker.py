"""
P12.1+P12.2: 行动跟踪器 — ActionTracker

三级完成 (full/partial/none),partial 也算 streak(从交小燃学)。
streak = 连续 N 天至少有 1 个 full 或 partial 的行动。
P12.2: 加 mark_completion_extended (带 estimated_saving + note + PII),
       get_stats (累计 + 趋势图),list_actions (按 status 查 pending/done)。
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from paths import ENERGY_ACTIONS_DB

from .models import CompletionLevel

logger = logging.getLogger(__name__)


# 三级完成 → 入账折扣
_RATIO = {
    CompletionLevel.FULL.value: 1.0,
    CompletionLevel.PARTIAL.value: 0.5,
    CompletionLevel.NONE.value: 0.0,
}


class ActionTracker:
    """行动完成度跟踪 + streak + 累计统计

    Usage:
        tracker = ActionTracker()
        tracker.mark_completion(user_id="alice", plan_id="plan-xxx",
                                action_id="ac_temp_up_1c",
                                level=CompletionLevel.FULL)
        streak = tracker.get_streak(user_id="alice")
        stats = tracker.get_stats(user_id="alice", period="week")
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or ENERGY_ACTIONS_DB

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(str(self.db_path))
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=5000")
        c.row_factory = sqlite3.Row  # P12.2: 让 r["col"] 访问生效
        return c

    # ========== 落完成度 ==========

    def mark_completion(
        self,
        user_id: str,
        plan_id: str,
        action_id: str,
        level: str,
        action_date: Optional[str] = None,
    ) -> int:
        """P12.1 基础版 — 记录一次行动完成度

        Returns: 写入记录 ID(< 0 表示失败)
        """
        if level not in {c.value for c in CompletionLevel}:
            raise ValueError(f"invalid level: {level}")

        action_date = action_date or date.today().isoformat()
        now_iso = datetime.utcnow().isoformat() + "Z"

        conn = self._conn()
        try:
            conn.execute(
                """
                INSERT INTO energy_completions
                  (user_id, plan_id, action_id, action_date, completion_level, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, action_id, action_date) DO UPDATE
                  SET completion_level = excluded.completion_level,
                      created_at = excluded.created_at
                """,
                (user_id, plan_id, action_id, action_date, level, now_iso),
            )
            has_activity = 1 if CompletionLevel.counts_as_streak(level) else 0
            conn.execute(
                """
                INSERT INTO energy_daily_streak (user_id, action_date, has_activity)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id, action_date) DO UPDATE
                  SET has_activity = MAX(has_activity, excluded.has_activity)
                """,
                (user_id, action_date, has_activity),
            )
            conn.commit()
            logger.info(
                "[tracker] user=%s action=%s level=%s date=%s",
                user_id, action_id, level, action_date,
            )
            return 1
        finally:
            conn.close()

    # ========== P12.2: 扩展版(带 estimated_saving + note + PII 脱敏) ==========

    def mark_completion_extended(
        self,
        user_id: str,
        action_id: str,
        completion_level: str,
        plan_id: Optional[str] = None,
        action_date: Optional[str] = None,
        estimated_saving_cny: float = 0.0,
        estimated_saving_kwh: float = 0.0,
        estimated_saving_co2_kg: float = 0.0,
        note: Optional[str] = None,
    ) -> Dict:
        """P12.2 扩展版 — 落完成度 + 返回 streak + 累计

        与 P12.1 区别:
          - level 用更直白的 completion_level 命名
          - 落库后立刻计算 streak / 累计返回
          - note 自动 PII 脱敏
          - P5-I.B 审计(失败不阻塞)
        """
        completion_level = (completion_level or "none").lower()
        if completion_level not in _RATIO:
            return {"ok": False, "error": f"invalid completion_level: {completion_level}"}

        action_date = action_date or date.today().isoformat()

        # PII 脱敏 note
        if note:
            try:
                from utils.pii import mask_pii

                note = mask_pii(note)
            except Exception:
                pass

        try:
            self.mark_completion(
                user_id=user_id,
                plan_id=plan_id or "unknown",
                action_id=action_id,
                level=completion_level,
                action_date=action_date,
            )
        except Exception as e:
            logger.warning("[tracker.ext] mark_completion 失败: %s", e)
            return {"ok": False, "error": str(e)}

        ratio = _RATIO[completion_level]
        credited_cny = round(float(estimated_saving_cny) * ratio, 2)
        credited_kwh = round(float(estimated_saving_kwh) * ratio, 3)
        credited_co2 = round(float(estimated_saving_co2_kg) * ratio, 3)

        # 累计
        stats = self.get_stats(user_id=user_id, period="all")
        streak = stats.get("streak_days", 0)

        # P5-I.B 审计
        try:
            from server.middleware.audit import record_audit

            record_audit(
                action="energy.action.completion",
                user_id=user_id,
                target=f"{action_id}@{action_date}",
                status_code=200,
                detail=json.dumps(
                    {
                        "completion_level": completion_level,
                        "credited_cny": credited_cny,
                        "credited_co2_kg": credited_co2,
                        "credited_kwh": credited_kwh,
                        "has_note": bool(note),
                    },
                    ensure_ascii=False,
                ),
            )
        except Exception:
            pass

        return {
            "ok": True,
            "action_id": action_id,
            "completion_level": completion_level,
            "action_date": action_date,
            "credited_saving_cny": credited_cny,
            "credited_saving_kwh": credited_kwh,
            "credited_saving_co2_kg": credited_co2,
            "streak_days": streak,
            "累计省_cny": stats["total_saving_cny"],
            "累计减_co2_kg": stats["total_saving_co2_kg"],
            "累计节_kwh": stats["total_saving_kwh"],
            "note": note,
        }

    # ========== P12.2: 累计统计 + 趋势图 ==========

    def get_stats(self, user_id: str, period: str = "all") -> Dict:
        """累计节能(元/度/kg) + streak + 趋势数据

        Args:
            user_id: 用户 ID
            period: "week"|"month"|"year"|"all"
        """
        period = (period or "all").lower()
        today = date.today()
        if period == "week":
            start = (today - timedelta(days=6)).isoformat()
            bucket = "day"
        elif period == "month":
            start = (today - timedelta(days=29)).isoformat()
            bucket = "day"
        elif period == "year":
            start = (today - timedelta(days=364)).isoformat()
            bucket = "month"
        else:
            start = "1970-01-01"
            bucket = "month"

        try:
            conn = self._conn()
            cur = conn.execute(
                """
                SELECT c.action_date, c.completion_level, c.action_id, c.plan_id,
                       p.actions AS plan_actions
                FROM energy_completions c
                LEFT JOIN energy_plans p ON c.plan_id = p.plan_id
                WHERE c.user_id = ? AND c.action_date >= ?
                ORDER BY c.action_date ASC
                """,
                (user_id, start),
            )
            rows = cur.fetchall()
            conn.close()

            total_cny = 0.0
            total_kwh = 0.0
            total_co2 = 0.0
            by_bucket: Dict[str, Dict[str, float]] = {}

            for r in rows:
                ratio = _RATIO.get(r["completion_level"], 0.0)
                if ratio == 0:
                    continue
                saved_cny, saved_kwh, saved_co2 = self._lookup_action_savings(
                    r["action_id"], r["plan_actions"]
                )
                day = r["action_date"]
                bucket_key = day[:7] if bucket == "month" else day
                slot = by_bucket.setdefault(
                    bucket_key, {"cny": 0.0, "kwh": 0.0, "co2_kg": 0.0}
                )
                slot["cny"] += saved_cny * ratio
                slot["kwh"] += saved_kwh * ratio
                slot["co2_kg"] += saved_co2 * ratio
                total_cny += saved_cny * ratio
                total_kwh += saved_kwh * ratio
                total_co2 += saved_co2 * ratio

            trend = [
                {
                    "date": d,
                    "cny": round(v["cny"], 2),
                    "kwh": round(v["kwh"], 3),
                    "co2_kg": round(v["co2_kg"], 3),
                }
                for d, v in sorted(by_bucket.items())
            ]

            return {
                "user_id": user_id,
                "period": period,
                "total_saving_cny": round(total_cny, 2),
                "total_saving_kwh": round(total_kwh, 3),
                "total_saving_co2_kg": round(total_co2, 3),
                "completions_count": len(rows),
                "streak_days": self.get_streak(user_id),
                "trend": trend,
            }
        except Exception as e:
            logger.exception("[tracker] get_stats 失败: %s", e)
            return {
                "user_id": user_id,
                "period": period,
                "total_saving_cny": 0.0,
                "total_saving_kwh": 0.0,
                "total_saving_co2_kg": 0.0,
                "completions_count": 0,
                "streak_days": 0,
                "trend": [],
                "error": str(e),
            }

    # ========== P12.2: 列出 actions ==========

    def list_actions(self, user_id: str, status: str = "pending", limit: int = 50) -> List[Dict]:
        """按 status 列出 actions

        Args:
            status: "pending"|"done"
                - pending: 当前 active plan 里的 actions(标记今天完成的会标 done_today)
                - done: 历史 completion 记录
        """
        status = (status or "pending").lower()
        try:
            conn = self._conn()
            if status == "done":
                cur = conn.execute(
                    """
                    SELECT action_id, action_date, completion_level, plan_id
                    FROM energy_completions
                    WHERE user_id = ?
                    ORDER BY action_date DESC
                    LIMIT ?
                    """,
                    (user_id, int(limit)),
                )
                return [
                    {
                        "action_id": r["action_id"],
                        "action_date": r["action_date"],
                        "completion_level": r["completion_level"],
                        "plan_id": r["plan_id"],
                    }
                    for r in cur.fetchall()
                ]
            # pending
            today = date.today().isoformat()
            done_today = {
                r["action_id"]
                for r in conn.execute(
                    "SELECT action_id FROM energy_completions "
                    "WHERE user_id = ? AND action_date = ?",
                    (user_id, today),
                ).fetchall()
            }
            cur = conn.execute(
                "SELECT plan_id, actions FROM energy_plans "
                "WHERE user_id = ? AND status = 'active' "
                "ORDER BY created_at DESC LIMIT 1",
                (user_id,),
            )
            pr = cur.fetchone()
            if not pr:
                return []
            try:
                actions = json.loads(pr["actions"] or "[]")
            except Exception:
                actions = []
            out: List[Dict] = []
            for a in actions[: int(limit)]:
                aid = a.get("id", "")
                out.append(
                    {
                        "plan_id": pr["plan_id"],
                        "action_id": aid,
                        "title": a.get("title", ""),
                        "category": a.get("category", ""),
                        "estimated_saving_cny": a.get("estimated_saving_cny", 0),
                        "estimated_saving_co2_kg": a.get("estimated_saving_co2_kg", 0),
                        "estimated_saving_kwh": a.get("estimated_saving_kwh", 0),
                        "difficulty": a.get("difficulty", 1),
                        "when_to_do": a.get("when_to_do", ""),
                        "status": "done_today" if aid in done_today else "pending",
                    }
                )
            return out
        except Exception as e:
            logger.warning("[tracker] list_actions 失败: %s", e)
            return []

    # ========== 工具 ==========

    def _lookup_action_savings(self, action_id: str, plan_actions_json: Optional[str]) -> tuple:
        """从 plan_actions JSON 查 action 的预期节省;若 plan 没找到则用 APPLIANCE_SAVINGS 兜底"""
        try:
            if plan_actions_json:
                actions = json.loads(plan_actions_json)
                for a in actions:
                    if a.get("id") == action_id:
                        return (
                            float(a.get("estimated_saving_cny", 0) or 0),
                            float(a.get("estimated_saving_kwh", 0) or 0),
                            float(a.get("estimated_saving_co2_kg", 0) or 0),
                        )
        except Exception:
            pass
        # P12.2 兜底:用 APPLIANCE_SAVINGS 模板,确保数字可追溯(source_ref 已在模板里)
        try:
            from .policies import appliance_potential

            saving = appliance_potential(action_id)
            if saving:
                return (
                    float(saving.saving_cny_per_action or 0),
                    float(saving.saving_kwh_per_action or 0),
                    float(saving.saving_co2_kg_per_action or 0),
                )
        except Exception:
            pass
        return (0.0, 0.0, 0.0)

    # ========== streak 统计 ==========

    def get_streak(self, user_id: str) -> int:
        """连续 streak 天数(从今天往前推,断一天就停)"""
        conn = self._conn()
        try:
            cur = conn.execute(
                "SELECT action_date FROM energy_daily_streak "
                "WHERE user_id = ? AND has_activity = 1 "
                "ORDER BY action_date DESC",
                (user_id,),
            )
            dates = [date.fromisoformat(r[0]) for r in cur.fetchall() if r[0]]
        finally:
            conn.close()
        if not dates:
            return 0

        streak = 1
        expected = dates[0]
        today = date.today()
        if (today - expected).days > 1:
            return 0

        for d in dates[1:]:
            expected = expected - timedelta(days=1)
            if d == expected:
                streak += 1
            else:
                break
        return streak

    def get_today_completions(self, user_id: str) -> List[Dict]:
        """今日的所有完成度记录"""
        today = date.today().isoformat()
        conn = self._conn()
        out: List[Dict] = []
        try:
            cur = conn.execute(
                "SELECT plan_id, action_id, completion_level, created_at "
                "FROM energy_completions "
                "WHERE user_id = ? AND action_date = ? "
                "ORDER BY created_at",
                (user_id, today),
            )
            for row in cur.fetchall():
                out.append({
                    "plan_id": row[0],
                    "action_id": row[1],
                    "completion_level": row[2],
                    "created_at": row[3],
                })
        finally:
            conn.close()
        return out

    def get_completion_stats(self, user_id: str, days: int = 30) -> Dict:
        """最近 N 天的完成统计"""
        since = (date.today() - timedelta(days=days)).isoformat()
        conn = self._conn()
        try:
            cur = conn.execute(
                "SELECT completion_level, COUNT(*) "
                "FROM energy_completions "
                "WHERE user_id = ? AND action_date >= ? "
                "GROUP BY completion_level",
                (user_id, since),
            )
            by_level = {r[0]: r[1] for r in cur.fetchall()}
            full = by_level.get(CompletionLevel.FULL.value, 0)
            partial = by_level.get(CompletionLevel.PARTIAL.value, 0)
            none = by_level.get(CompletionLevel.NONE.value, 0)
            total = full + partial + none
            completion_rate = (full + partial) / total if total else 0.0
            return {
                "user_id": user_id,
                "window_days": days,
                "full": full,
                "partial": partial,
                "none": none,
                "total_actions": total,
                "completion_rate": round(completion_rate, 3),
                "streak": self.get_streak(user_id),
            }
        finally:
            conn.close()


def get_action_tracker() -> ActionTracker:
    """单例工厂"""
    return ActionTracker()


__all__ = ["ActionTracker", "get_action_tracker"]
