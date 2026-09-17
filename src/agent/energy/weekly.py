"""Seven-day self-reported action experiments, never monetary/carbon credits."""
from contextlib import closing
from datetime import date, timedelta, datetime
import json
import sqlite3
import uuid

from paths import HOUSEHOLDS_DB

WEEKLY_SCHEMA = """CREATE TABLE IF NOT EXISTS energy_weeks (
    user_id TEXT PRIMARY KEY, week_id TEXT NOT NULL, start_date TEXT NOT NULL,
    plan_json TEXT NOT NULL, feedback_json TEXT NOT NULL DEFAULT '{}'
)"""
HISTORY_SCHEMA = "CREATE TABLE IF NOT EXISTS energy_week_history (week_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, snapshot_json TEXT NOT NULL)"
BARRIERS = {"none": "无困难", "comfort": "影响舒适", "family": "家人不同意",
            "unsupported": "设备不支持", "forgot": "忘记了", "already": "本来就在做"}


class WeeklyEnergy:
    def __init__(self, db_path=None):
        self.db_path = db_path or HOUSEHOLDS_DB

    def _conn(self):
        conn = sqlite3.connect(str(self.db_path), timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute(WEEKLY_SCHEMA)
        conn.execute(HISTORY_SCHEMA)
        return conn

    def start(self, user_id, plan, action_ids, today=None):
        today = today or date.today()
        if plan.user_id != user_id or plan.blocked:
            raise ValueError("方案不可用")
        if not isinstance(action_ids, list) or not 1 <= len(action_ids) <= 3 or any(not isinstance(x, str) for x in action_ids):
            raise ValueError("请选择1至3件行动")
        actions = {a.id: a.to_dict() for a in plan.actions}
        if len(set(action_ids)) != len(action_ids) or any(x not in actions for x in action_ids):
            raise ValueError("行动不属于本次方案")
        snapshot = plan.to_dict()
        snapshot["actions"] = [actions[x] for x in action_ids]
        with closing(self._conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM energy_weeks WHERE user_id=?", (user_id,)).fetchone()
            if row and today <= date.fromisoformat(row["start_date"]) + timedelta(days=6):
                old_ids = [a["id"] for a in json.loads(row["plan_json"])["actions"]]
                if old_ids != action_ids:
                    raise ValueError("本周行动已开始，请先完成本周记录；重复点击不会重置进度")
            else:
                if row:
                    conn.execute("INSERT OR REPLACE INTO energy_week_history VALUES (?, ?, ?)",
                                 (row["week_id"], user_id, json.dumps(dict(row), ensure_ascii=False)))
                conn.execute("INSERT OR REPLACE INTO energy_weeks VALUES (?, ?, ?, ?, '{}')",
                             (user_id, "week-" + uuid.uuid4().hex, today.isoformat(), json.dumps(snapshot, ensure_ascii=False)))
            conn.commit()
        return self.get(user_id, today)

    def feedback(self, user_id, week_id, action_id, level, barrier="none", action_date=None, today=None):
        today = today or date.today()
        if level not in ("full", "partial", "none") or barrier not in BARRIERS:
            raise ValueError("请选择有效的完成情况和困难原因")
        day = date.fromisoformat(action_date) if action_date else today
        with closing(self._conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM energy_weeks WHERE user_id=? AND week_id=?", (user_id, week_id)).fetchone()
            if row is None:
                raise ValueError("本周行动不存在或不属于你")
            start = date.fromisoformat(row["start_date"])
            if not start <= day <= min(today, start + timedelta(days=6)):
                raise ValueError("只能记录本周已经发生的日期")
            plan = json.loads(row["plan_json"])
            if action_id not in {a["id"] for a in plan["actions"]}:
                raise ValueError("行动不属于本周计划")
            feedback = json.loads(row["feedback_json"])
            feedback[f"{day.isoformat()}:{action_id}"] = {
                "date": day.isoformat(), "action_id": action_id, "level": level, "barrier": barrier}
            conn.execute("UPDATE energy_weeks SET feedback_json=? WHERE user_id=?",
                         (json.dumps(feedback, ensure_ascii=False), user_id))
            conn.commit()
        return self.get(user_id, today)

    def get(self, user_id, today=None):
        today = today or date.today()
        with closing(self._conn()) as conn:
            row = conn.execute("SELECT * FROM energy_weeks WHERE user_id=?", (user_id,)).fetchone()
        if row is None:
            return {"ok": True, "week": None}
        plan = json.loads(row["plan_json"])
        entries = list(json.loads(row["feedback_json"]).values())
        start = date.fromisoformat(row["start_date"])
        end = start + timedelta(days=6)
        active_days = len({x["date"] for x in entries if x["level"] in ("full", "partial")})
        barriers = {k: sum(x["barrier"] == k for x in entries) for k in BARRIERS if k != "none"}
        suggestions = []
        if barriers["comfort"]: suggestions.append("下周先缩小改变幅度，以舒适为前提。")
        if barriers["family"]: suggestions.append("先选择只影响自己的行动，再与家人商量共同习惯。")
        if barriers["unsupported"]: suggestions.append("先核对设备；标记不支持的行动会从下一次建议中暂时排除。")
        if barriers["forgot"]: suggestions.append("把行动安排在已有日常习惯之后；此处不会自动发送提醒。")
        if barriers["already"]: suggestions.append("已在做的行动不再当成新增节省，下一次换一件尝试。")
        if not suggestions: suggestions.append("继续记录执行感受；有困难时可以改为部分完成。")
        return {"ok": True, "week": {"week_id": row["week_id"], "start_date": str(start),
            "plan_id": plan["id"], "end_date": str(end), "completed": today > end, "day": min(7, max(1, (today-start).days+1)),
            "actions": plan["actions"], "entries": entries, "active_days": active_days,
            "record_count": len(entries), "barriers": barriers, "next_week_suggestions": suggestions,
            "measurement_status": "self_reported", "verified_savings": None,
            "summary": f"7天行动中，已有{active_days}天报告执行，共{len(entries)}条记录。未接入实测数据，不能确认实际节能量。"}}

    def exclusions(self, user_id):
        week = self.get(user_id).get("week")
        if not week:
            return []
        # Only latest feedback for each action; a correction can remove exclusion.
        latest = {}
        for entry in sorted(week["entries"], key=lambda x: x["date"]):
            latest[entry["action_id"]] = entry
        return [k for k, v in latest.items() if v["barrier"] in ("unsupported", "already")]
