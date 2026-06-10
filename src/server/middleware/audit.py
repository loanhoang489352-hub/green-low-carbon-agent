"""
审计日志记录器(P5-I.B)

落库到 accounts.db.audit_log(Schema Registry 初始化):
- user_id: 关联账号(可空,如未鉴权请求)
- action: 动作标识(如 "auth.login" / "chat.enhanced" / "auth.login.fail")
- target: 目标资源(message_id / account_id / endpoint 等)
- ip / user_agent: 客户端标识
- status_code: HTTP 状态(200 / 401 / 429 等)
- detail: 自由文本(已做 PII 脱敏)

写入失败不应阻塞主流程:try/except + logger.warning。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional


def _audit_db_path() -> str:
    """审计日志 DB 路径(accounts.db)"""
    try:
        from paths import ACCOUNTS_DB
        return str(ACCOUNTS_DB)
    except Exception:
        # 兜底:相对路径(测试环境)
        return str(Path(__file__).resolve().parent.parent.parent.parent / "data" / "accounts.db")


def record_audit(
    action: str,
    user_id: Optional[str] = None,
    target: Optional[str] = None,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    status_code: Optional[int] = None,
    detail: Optional[str] = None,
) -> bool:
    """写一条审计日志

    Returns:
        True = 写入成功,False = 失败(失败原因 logger.warning,不抛)
    """
    try:
        conn = sqlite3.connect(_audit_db_path(), timeout=2.0)
        # PII 脱敏(防 detail 中残留)
        try:
            from utils.pii import mask_pii
            if detail:
                detail = mask_pii(detail)
            if target:
                target = mask_pii(target)
        except Exception:
            pass

        conn.execute(
            """
            INSERT INTO audit_log
            (user_id, action, target, ip, user_agent, status_code, detail, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id, action, target, ip, user_agent,
                status_code, detail, datetime.now().isoformat(),
            ),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        import logging
        logging.getLogger("server.audit").warning(
            "[Audit] 写入失败: action=%s err=%s", action, e,
        )
        return False


def query_audit(
    user_id: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = 100,
) -> list:
    """查询审计日志(管理用)"""
    try:
        conn = sqlite3.connect(_audit_db_path())
        conn.row_factory = sqlite3.Row
        query = "SELECT * FROM audit_log WHERE 1=1"
        params = []
        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)
        if action:
            query += " AND action = ?"
            params.append(action)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []
