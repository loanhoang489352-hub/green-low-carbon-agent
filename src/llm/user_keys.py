"""
每用户 LLM API key 存储(P17)

修复多租户成本/安全漏洞:此前所有用户共用全局 .env 里的 owner key,
且任意登录用户能通过 /api/settings/api-key 覆盖全局 .env(后写覆盖先写)。

现在:
  - 每个 user_id 存自己的 (provider/model/api_key),Fernet 加密落 accounts.db
  - 主密钥:LLM_KEY_MASTER_SECRET env;未设则用 data/.llm_key_secret(首次自动生成,已被 data/ gitignore)
  - get_llm_client(user_id) 按 user_id 解析;无 key → 严格阻断(不 fallback 到 owner)

依赖 cryptography(已作为传递依赖存在,这里显式使用 Fernet)。
"""
from __future__ import annotations

import base64
import hashlib
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from cryptography.fernet import Fernet, InvalidToken

from paths import ACCOUNTS_DB, DATA_DIR

_fernet: Optional[Fernet] = None
_fernet_lock = threading.Lock()


def _derive_key(secret: str) -> bytes:
    """从主密钥字符串派生 32 字节 Fernet key"""
    return base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())


def _key_file() -> Path:
    return Path(DATA_DIR) / ".llm_key_secret"


def _load_master_key() -> bytes:
    """主密钥来源:env 优先,否则 data/.llm_key_secret(首次生成并持久化)"""
    secret = os.environ.get("LLM_KEY_MASTER_SECRET", "").strip()
    if secret:
        return _derive_key(secret)
    kf = _key_file()
    if kf.exists():
        key = kf.read_text(encoding="utf-8").strip()
        if key:
            return key.encode("utf-8")
    key = Fernet.generate_key()
    kf.parent.mkdir(parents=True, exist_ok=True)
    kf.write_text(key.decode("utf-8"), encoding="utf-8")
    return key


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        with _fernet_lock:
            if _fernet is None:
                _fernet = Fernet(_load_master_key())
    return _fernet


def reset_fernet() -> None:
    """重置缓存(测试用)"""
    global _fernet
    with _fernet_lock:
        _fernet = None


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(ACCOUNTS_DB))
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=5000")
    return c


def _init_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_llm_keys (
            user_id TEXT PRIMARY KEY,
            api_key_encrypted TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )


def save_key(user_id: str, api_key: str, provider: str, model: Optional[str] = None) -> None:
    """加密保存某用户的 LLM key(UPSERT)"""
    enc = _get_fernet().encrypt(api_key.encode("utf-8")).decode("utf-8")
    conn = _conn()
    try:
        _init_table(conn)
        conn.execute(
            "INSERT OR REPLACE INTO user_llm_keys "
            "(user_id, api_key_encrypted, provider, model, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, enc, provider, model, datetime.now().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def get_key(user_id: str) -> Optional[Tuple[str, str, Optional[str]]]:
    """返回 (api_key, provider, model) 或 None(未配置/解密失败)"""
    if not user_id:
        return None
    conn = _conn()
    try:
        _init_table(conn)
        row = conn.execute(
            "SELECT api_key_encrypted, provider, model FROM user_llm_keys WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    try:
        api_key = _get_fernet().decrypt(row[0].encode("utf-8")).decode("utf-8")
    except (InvalidToken, Exception):
        return None
    return api_key, row[1], row[2]


def has_key(user_id: str) -> bool:
    return get_key(user_id) is not None


def delete_key(user_id: str) -> None:
    conn = _conn()
    try:
        _init_table(conn)
        conn.execute("DELETE FROM user_llm_keys WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()


__all__ = ["save_key", "get_key", "has_key", "delete_key", "reset_fernet"]
