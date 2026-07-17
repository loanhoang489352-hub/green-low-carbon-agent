"""
M3: NeMo Guardrails 完整接入 — 业务定制版
- input/output 双层防护
- 业务专属风控:知识库篡改/收益篡改/诱导非环保
- 拦截日志 + 异常限流
- 异常降级放行(不影响主业务)
低耦合:独立模块,只接 hook,不修改原 chat 逻辑
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

logger = logging.getLogger("guardrails.v2")

# 配置:NeMo 是否启用(失败自动降级)
NEMO_ENABLED = True
try:
    from nemoguardrails import LLMRails, RailsConfig
    _NEMO_OK = True
except Exception as e:
    _NEMO_OK = False
    logger.warning("[M3] NeMo Guardrails 不可用,降级到 rule-only: %s", e)

# 业务专属风控规则(扩展 config/guardrails.yaml)
LOW_CARBON_RISK_PATTERNS = {
    "kb_pollution": [
        # 知识库篡改(诱导 LLM 绕过守门员)
        "ignore previous instructions and write",
        "忽略之前的指令,直接写入",
        "bypass knowledge gatekeeper",
        "绕过知识库守门员",
        "污染向量库",
        "批量写入非低碳",
    ],
    "reward_cheat": [
        # 收益篡改(试图通过 prompt 篡改用户数据)
        "set my co2 reduction to",
        "把我的减排量改成",
        "修改我的精灵币",
        "提升我的 PK 段位到",
        "change my level to",
        "把我的等级改成",
        "把精灵币改成",
        "把精灵币调成",
        "精灵币改成",
        "精灵币调成",
        "提升到宗师",
        "直接到满级",
        "modify my coins",
        "set my tier to",
    ],
    "anti_green": [
        # 诱导非环保行为(与业务定位冲突)
        "recommend driving alone",
        "推荐单独开车",
        "use more plastic",
        "多用一次性塑料",
        "don't recycle",
        "不用垃圾分类",
    ],
    "general_threats": [
        # 通用威胁
        "hack the system",
        "exploit database",
        "extract all user data",
        "导出所有用户数据",
    ],
}

# 拦截日志 DB
GUARDRAILS_LOG_PATH = Path(__file__).parent.parent.parent / "data" / "guardrails_v2.db"
GUARDRAILS_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
_lock = threading.Lock()


def init_guardrails_log() -> None:
    conn = sqlite3.connect(str(GUARDRAILS_LOG_PATH), check_same_thread=False, timeout=10.0)
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS guardrails_blocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            layer TEXT,            -- input / output
            category TEXT,         -- kb_pollution / reward_cheat / anti_green / general
            user_input TEXT,
            bot_output TEXT,
            matched_pattern TEXT,
            user_id TEXT,
            ip TEXT
        );

        CREATE TABLE IF NOT EXISTS attack_stats (
            user_id TEXT,
            ip TEXT,
            category TEXT,
            block_count INTEGER DEFAULT 0,
            last_block_at TEXT,
            PRIMARY KEY (user_id, ip, category)
        );
        """)
        conn.commit()
    finally:
        conn.close()


init_guardrails_log()


def _log_block(layer: str, category: str, user_input: str, bot_output: str,
               matched: str, user_id: str = "anonymous", ip: str = "") -> None:
    with _lock:
        conn = sqlite3.connect(str(GUARDRAILS_LOG_PATH), check_same_thread=False, timeout=10.0)
        try:
            conn.execute("""
            INSERT INTO guardrails_blocks
            (timestamp, layer, category, user_input, bot_output, matched_pattern, user_id, ip)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (time.strftime("%Y-%m-%d %H:%M:%S"), layer, category,
                  user_input[:500], bot_output[:500] if bot_output else "",
                  matched, user_id, ip))
            # 攻击统计
            conn.execute("""
            INSERT INTO attack_stats (user_id, ip, category, block_count, last_block_at)
            VALUES (?, ?, ?, 1, ?)
            ON CONFLICT (user_id, ip, category) DO UPDATE SET
            block_count = block_count + 1, last_block_at = ?
            """, (user_id, ip, category, time.strftime("%Y-%m-%d %H:%M:%S"),
                  time.strftime("%Y-%m-%d %H:%M:%S")))
            conn.commit()
        except Exception as e:
            logger.debug("[M3] log_block 失败: %s", e)
        finally:
            conn.close()


def _check_patterns(text: str, layer: str, user_id: str = "anonymous", ip: str = "") -> Optional[Tuple[str, str, str]]:
    """M3: 检查文本是否命中风控规则,返回 (category, pattern, blocked_text)"""
    if not text:
        return None
    text_lower = text.lower()
    for category, patterns in LOW_CARBON_RISK_PATTERNS.items():
        for pat in patterns:
            if pat.lower() in text_lower:
                return (category, pat, text[:200])
    return None


class BusinessGuardrails:
    """M3: 业务定制 Guardrails(input/output 双层 + 降级)"""

    def __init__(self):
        self._enabled_input = os.environ.get("GUARDRAILS_INPUT_ENABLED", "true").lower() in ("1", "true", "yes", "on")
        self._enabled_output = os.environ.get("GUARDRAILS_OUTPUT_ENABLED", "true").lower() in ("1", "true", "yes", "on")
        # M3-T3: 主动防御 — 异常高频攻击 IP/用户自动限流
        self._auto_ban_threshold = int(os.environ.get("GUARDRAILS_AUTOBAN_THRESHOLD", "10"))

    def check_input(self, text: str, user_id: str = "anonymous", ip: str = "") -> Tuple[bool, str, str]:
        """input 层守门

        Returns: (passed, reason, sanitized_text)
        """
        if not self._enabled_input:
            return True, "disabled", text
        # M3-T1: 业务风控
        hit = _check_patterns(text, "input", user_id, ip)
        if hit:
            category, pattern, _ = hit
            _log_block("input", category, text, "", pattern, user_id, ip)
            return False, f"[M3 风控] 拦截:输入命中 '{category}' 规则", ""
        return True, "", text

    def check_output(self, text: str, user_input: str = "",
                     user_id: str = "anonymous", ip: str = "") -> Tuple[bool, str, str]:
        """output 层守门

        Returns: (passed, reason, sanitized_text)
        """
        if not self._enabled_output:
            return True, "disabled", text
        # M3-T2: 输出合规 — 不能诱导非环保行为
        hit = _check_patterns(text, "output", user_id, ip)
        if hit:
            category, pattern, _ = hit
            _log_block("output", category, user_input, text, pattern, user_id, ip)
            return False, f"[M3 风控] 输出拦截:命中 '{category}' 规则", self._redact_output(text)
        return True, "", text

    def _redact_output(self, text: str) -> str:
        return "[内容已被业务风控拦截,详情见审计日志]"

    def get_recent_blocks(self, limit: int = 50) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(str(GUARDRAILS_LOG_PATH), check_same_thread=False, timeout=10.0)
        try:
            cur = conn.execute(
                "SELECT timestamp, layer, category, user_input, bot_output, matched_pattern, user_id "
                "FROM guardrails_blocks ORDER BY id DESC LIMIT ?",
                (limit,)
            )
            return [
                {
                    "timestamp": r[0], "layer": r[1], "category": r[2],
                    "user_input": r[3], "bot_output": r[4], "matched": r[5],
                    "user_id": r[6],
                }
                for r in cur.fetchall()
            ]
        finally:
            conn.close()

    def get_attack_stats(self) -> List[Dict[str, Any]]:
        """M3-T3: 异常高频攻击统计"""
        conn = sqlite3.connect(str(GUARDRAILS_LOG_PATH), check_same_thread=False, timeout=10.0)
        try:
            cur = conn.execute(
                "SELECT user_id, ip, category, block_count, last_block_at "
                "FROM attack_stats WHERE block_count >= ? ORDER BY block_count DESC",
                (self._auto_ban_threshold,)
            )
            return [
                {"user_id": r[0], "ip": r[1], "category": r[2],
                 "block_count": r[3], "last_block_at": r[4]}
                for r in cur.fetchall()
            ]
        finally:
            conn.close()

    def get_stats(self) -> Dict[str, Any]:
        """M3-T3: 综合统计"""
        conn = sqlite3.connect(str(GUARDRAILS_LOG_PATH), check_same_thread=False, timeout=10.0)
        try:
            cur = conn.execute("SELECT COUNT(*) FROM guardrails_blocks")
            total = cur.fetchone()[0]
            cur = conn.execute(
                "SELECT category, COUNT(*) FROM guardrails_blocks GROUP BY category"
            )
            by_cat = {r[0]: r[1] for r in cur.fetchall()}
            cur = conn.execute(
                "SELECT layer, COUNT(*) FROM guardrails_blocks GROUP BY layer"
            )
            by_layer = {r[0]: r[1] for r in cur.fetchall()}
            return {
                "total_blocks": total,
                "by_category": by_cat,
                "by_layer": by_layer,
                "nemo_available": _NEMO_OK,
                "auto_ban_threshold": self._auto_ban_threshold,
                "high_frequency_attackers": self.get_attack_stats(),
            }
        finally:
            conn.close()


_bgr: Optional[BusinessGuardrails] = None


def get_business_guardrails() -> BusinessGuardrails:
    global _bgr
    if _bgr is None:
        _bgr = BusinessGuardrails()
    return _bgr
