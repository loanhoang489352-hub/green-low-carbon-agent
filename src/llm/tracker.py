"""
M2-T1/M2-T2/M2-T3/M2-T4: LLM 全链路成本监控
- 多维埋点:model/scene/user/tokens/time
- 成本核算:单价绑定
- 3 级告警:日费用/单用户/异常暴涨
- 优化策略:缓存/截断/小模型/预生成
- 独立开关:env ENABLE_LLM_TRACKING
低耦合:不修改现有 LLM client,只在外层包装埋点
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

_logger = logging.getLogger("llm.tracker")

# 单价表(USD per 1K tokens)— DeepSeek 公开报价
PRICING = {
    "deepseek-chat":       {"input": 0.00027, "output": 0.0011},  # USD / 1K tokens
    "deepseek-v4-flash":   {"input": 0.00014, "output": 0.00028},
    "gpt-4o-mini":         {"input": 0.00015, "output": 0.0006},
    "gpt-4o":              {"input": 0.0025,  "output": 0.01},
    "gpt-3.5-turbo":       {"input": 0.0005,  "output": 0.0015},
    "claude-3-haiku":      {"input": 0.00025, "output": 0.00125},
    "qwen-turbo":          {"input": 0.0003,  "output": 0.0006},
    "mock":                {"input": 0,       "output": 0},
    "default":             {"input": 0.0005,  "output": 0.0015},  # fallback
}

# 告警阈值(USD)
THRESHOLD_DAILY_USD = 5.0
THRESHOLD_USER_DAILY_USD = 0.5
THRESHOLD_BURST_REQUESTS_PER_MIN = 30  # 单用户每分钟 > 30 次告警

# 独立开关
ENABLE_TRACKING = os.environ.get("ENABLE_LLM_TRACKING", "true").lower() in ("1", "true", "yes", "on")

DB_PATH = Path(__file__).parent.parent.parent / "data" / "llm_tracking.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

_lock = threading.Lock()


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_tracking_schema() -> None:
    """M2-T1: 3 张表"""
    conn = _get_conn()
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS llm_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            model TEXT,
            scene TEXT,
            user_id TEXT,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            cost_usd REAL DEFAULT 0,
            cached BOOLEAN DEFAULT FALSE,
            duration_ms INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS llm_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            level TEXT,        -- INFO / WARN / CRITICAL
            category TEXT,     -- daily_budget / user_quota / burst / total
            message TEXT,
            user_id TEXT,
            metric_json TEXT
        );

        CREATE TABLE IF NOT EXISTS llm_cache (
            cache_key TEXT PRIMARY KEY,
            model TEXT,
            response TEXT,
            created_at TEXT,
            hit_count INTEGER DEFAULT 0
        );
        """)
        conn.commit()
    finally:
        conn.close()


init_tracking_schema()


def compute_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """M2-T2: 成本核算(单价 × tokens)"""
    pricing = PRICING.get(model, PRICING["default"])
    cost = (prompt_tokens / 1000.0) * pricing["input"] + (completion_tokens / 1000.0) * pricing["output"]
    return round(cost, 6)


class LLMTracker:
    """M2: 全链路 LLM 用量+成本追踪器"""

    def __init__(self):
        self._conn = _get_conn()
        if not ENABLE_TRACKING:
            _logger.info("[LLMTracker] 已被 env 关闭")
        # M2-T3: 缓存
        self._cache_enabled = os.environ.get("ENABLE_LLM_CACHE", "true").lower() in ("1", "true", "yes", "on")
        self._burst_window: Dict[str, list] = {}  # user_id → [timestamp, ...]

    @contextmanager
    def track_call(self, model: str, scene: str, user_id: str = "anonymous"):
        """M2-T1: 上下文管理器,记录单次 LLM 调用"""
        start = time.time()
        record = {
            "model": model,
            "scene": scene,
            "user_id": user_id,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cost_usd": 0.0,
            "cached": False,
            "duration_ms": 0,
        }
        try:
            yield record
        finally:
            if not ENABLE_TRACKING:
                return
            record["duration_ms"] = int((time.time() - start) * 1000)
            record["cost_usd"] = compute_cost(
                model, record["prompt_tokens"], record["completion_tokens"]
            )
            self._insert_call(record)
            self._check_alerts(user_id, record)

    def _insert_call(self, record: Dict[str, Any]) -> None:
        with _lock:
            self._conn.execute("""
            INSERT INTO llm_calls
            (timestamp, model, scene, user_id, prompt_tokens, completion_tokens, total_tokens, cost_usd, cached, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                time.strftime("%Y-%m-%d %H:%M:%S"),
                record["model"],
                record["scene"],
                record["user_id"],
                record["prompt_tokens"],
                record["completion_tokens"],
                record["total_tokens"],
                record["cost_usd"],
                record["cached"],
                record["duration_ms"],
            ))
            self._conn.commit()

    def _check_alerts(self, user_id: str, record: Dict[str, Any]) -> None:
        # 1) 单用户日费用
        user_daily = self.get_user_daily_cost(user_id)
        if user_daily > THRESHOLD_USER_DAILY_USD:
            self._emit_alert("WARN", "user_quota", f"用户 {user_id} 当日累计 ${user_daily:.4f} > 阈值 ${THRESHOLD_USER_DAILY_USD}", user_id)
        # 2) 全局日费用
        daily_total = self.get_daily_total_cost()
        if daily_total > THRESHOLD_DAILY_USD:
            self._emit_alert("CRITICAL", "daily_budget", f"全局当日累计 ${daily_total:.4f} > 阈值 ${THRESHOLD_DAILY_USD}", user_id)
        # 3) 单用户突发频率(1 分钟内)
        now = time.time()
        if user_id not in self._burst_window:
            self._burst_window[user_id] = []
        self._burst_window[user_id] = [t for t in self._burst_window[user_id] if now - t < 60]
        self._burst_window[user_id].append(now)
        if len(self._burst_window[user_id]) > THRESHOLD_BURST_REQUESTS_PER_MIN:
            self._emit_alert("WARN", "burst", f"用户 {user_id} 1 分钟内 {len(self._burst_window[user_id])} 次请求", user_id)

    def _emit_alert(self, level: str, category: str, msg: str, user_id: str) -> None:
        _logger.warning("[LLM ALERT] %s %s: %s", level, category, msg)
        try:
            self._conn.execute(
                "INSERT INTO llm_alerts (timestamp, level, category, message, user_id) VALUES (?, ?, ?, ?, ?)",
                (time.strftime("%Y-%m-%d %H:%M:%S"), level, category, msg, user_id)
            )
            self._conn.commit()
        except Exception as e:
            _logger.debug("[LLMTracker] 告警写库失败: %s", e)

    # ===== 统计接口 =====

    def get_daily_total_cost(self, day: Optional[date] = None) -> float:
        day = day or date.today()
        cur = self._conn.execute(
            "SELECT SUM(cost_usd) FROM llm_calls WHERE timestamp LIKE ?",
            (day.isoformat() + "%",)
        )
        row = cur.fetchone()
        return row[0] or 0.0

    def get_user_daily_cost(self, user_id: str, day: Optional[date] = None) -> float:
        day = day or date.today()
        cur = self._conn.execute(
            "SELECT SUM(cost_usd) FROM llm_calls WHERE user_id=? AND timestamp LIKE ?",
            (user_id, day.isoformat() + "%")
        )
        row = cur.fetchone()
        return row[0] or 0.0

    def get_top_consumers(self, top: int = 10, period: str = "day") -> List[Dict[str, Any]]:
        """M2-T2: 高消耗接口/用户 TOP"""
        if period == "day":
            today = date.today().isoformat()
            like = today + "%"
        elif period == "month":
            ym = time.strftime("%Y-%m")
            like = ym + "%"
        else:
            like = "%"
        # Top 模型
        cur = self._conn.execute(
            f"SELECT model, COUNT(*) as n, SUM(cost_usd) as cost, SUM(total_tokens) as tokens "
            f"FROM llm_calls WHERE timestamp LIKE ? GROUP BY model ORDER BY cost DESC LIMIT ?",
            (like, top)
        )
        models = [{"model": r[0], "calls": r[1], "cost_usd": r[2], "tokens": r[3]} for r in cur.fetchall()]
        # Top 用户
        cur = self._conn.execute(
            f"SELECT user_id, COUNT(*) as n, SUM(cost_usd) as cost "
            f"FROM llm_calls WHERE timestamp LIKE ? GROUP BY user_id ORDER BY cost DESC LIMIT ?",
            (like, top)
        )
        users = [{"user_id": r[0], "calls": r[1], "cost_usd": r[2]} for r in cur.fetchall()]
        return {"top_models": models, "top_users": users}

    def get_recent_alerts(self, limit: int = 20) -> List[Dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT timestamp, level, category, message, user_id FROM llm_alerts ORDER BY id DESC LIMIT ?",
            (limit,)
        )
        return [
            {"timestamp": r[0], "level": r[1], "category": r[2], "message": r[3], "user_id": r[4]}
            for r in cur.fetchall()
        ]

    def get_summary(self, period: str = "day") -> Dict[str, Any]:
        """M2-T2: 综合成本报表"""
        if period == "day":
            today = date.today().isoformat()
            like = today + "%"
        else:
            ym = time.strftime("%Y-%m")
            like = ym + "%"
        cur = self._conn.execute(
            f"SELECT COUNT(*), SUM(prompt_tokens), SUM(completion_tokens), SUM(cost_usd) "
            f"FROM llm_calls WHERE timestamp LIKE ?",
            (like,)
        )
        row = cur.fetchone()
        n, pt, ct, cost = (row[0] or 0, row[1] or 0, row[2] or 0, row[3] or 0.0)
        return {
            "period": period,
            "total_calls": n,
            "prompt_tokens": pt,
            "completion_tokens": ct,
            "total_tokens": (pt or 0) + (ct or 0),
            "cost_usd": round(cost, 4),
            "top": self.get_top_consumers(5, period),
            "alerts_recent": self.get_recent_alerts(5),
        }

    # ===== 缓存策略(M2-T3) =====

    def cache_key(self, model: str, prompt: str, scene: str) -> str:
        import hashlib
        raw = f"{model}::{scene}::{prompt}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def get_cache(self, key: str) -> Optional[str]:
        if not self._cache_enabled:
            return None
        cur = self._conn.execute(
            "SELECT response FROM llm_cache WHERE cache_key=?", (key,)
        )
        row = cur.fetchone()
        if row:
            # 命中 +1
            self._conn.execute(
                "UPDATE llm_cache SET hit_count = hit_count + 1 WHERE cache_key=?", (key,)
            )
            self._conn.commit()
            return row[0]
        return None

    def set_cache(self, key: str, model: str, response: str) -> None:
        if not self._cache_enabled:
            return
        try:
            self._conn.execute(
                "INSERT OR REPLACE INTO llm_cache (cache_key, model, response, created_at, hit_count) VALUES (?, ?, ?, ?, 0)",
                (key, model, response, time.strftime("%Y-%m-%d %H:%M:%S"))
            )
            self._conn.commit()
        except Exception as e:
            _logger.debug("[LLMTracker] set_cache 失败: %s", e)


_tracker: Optional[LLMTracker] = None


def get_tracker() -> LLMTracker:
    global _tracker
    if _tracker is None:
        _tracker = LLMTracker()
    return _tracker


# 便捷包装(供现有代码 0 改造接入)
def tracked_chat(model: str, scene: str, user_id: str, prompt: str, chat_fn):
    """M2-T4: 0 改造包装 — 现有 chat() 调用前用此包装

    用法:
        from llm.tracker import tracked_chat
        resp = tracked_chat("deepseek-chat", "rag_qa", user_id, prompt,
                            lambda: client.chat([{"role":"user","content":prompt}]))
    """
    tracker = get_tracker()
    cache_key = tracker.cache_key(model, prompt, scene)
    cached = tracker.get_cache(cache_key)
    if cached is not None:
        # 缓存命中,直接返回
        class _Resp:
            pass
        _r = _Resp()
        _r.content = cached
        _r.cached = True
        _r.prompt_tokens = 0
        _r.completion_tokens = 0
        return _r
    # 实际调用
    with tracker.track_call(model, scene, user_id) as rec:
        resp = chat_fn()
        # 尽量从 resp 提取 tokens
        pt = getattr(resp, "prompt_tokens", 0) or 0
        ct = getattr(resp, "completion_tokens", 0) or 0
        rec["prompt_tokens"] = pt
        rec["completion_tokens"] = ct
        rec["total_tokens"] = pt + ct
        # 写缓存
        try:
            content = getattr(resp, "content", str(resp))
            tracker.set_cache(cache_key, model, content)
        except Exception:
            pass
        return resp
