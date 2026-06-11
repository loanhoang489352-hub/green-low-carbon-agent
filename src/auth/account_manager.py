# -*- coding: utf-8 -*-
"""
用户账号管理器
管理用户注册、登录、登出、密码加密存储
"""

import sqlite3
import os
import sys
import uuid
import re
import secrets
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

# Windows UTF-8 encoding
if sys.platform == 'win32':
    import io
    if hasattr(sys.stdout, 'buffer') and not isinstance(sys.stdout, io.TextIOWrapper):
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
        except Exception:
            pass

script_path = Path(__file__).resolve()
project_root = script_path.parent.parent.parent
data_dir = project_root / "data"
data_dir.mkdir(exist_ok=True)

DB_PATH = str(data_dir / "accounts.db")

# bcrypt 兼容：如果 bcrypt 不可用，使用内置的简单哈希
try:
    import bcrypt
    BCRYPT_AVAILABLE = True
except ImportError:
    BCRYPT_AVAILABLE = False

# P5-F: 模块级 logger(无论 bcrypt 是否安装都需要)
import logging
_auth_logger = logging.getLogger("auth")

if not BCRYPT_AVAILABLE:
    _auth_logger.warning("bcrypt 未安装,将使用 PBKDF2 替代(建议安装 bcrypt: pip install bcrypt)")


def _hash_password(password: str) -> str:
    """密码哈希"""
    if BCRYPT_AVAILABLE:
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    else:
        # PBKDF2 fallback
        import hashlib
        import base64
        salt = secrets.token_hex(16)
        key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000)
        return f"$pbkdf2${salt}${base64.b64encode(key).decode('utf-8')}"


def _check_password(password: str, hashed: str) -> bool:
    """验证密码"""
    # 如果是 bcrypt 哈希（以 $2 开头）
    if hashed.startswith('$2'):
        if BCRYPT_AVAILABLE:
            return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
        else:
            return False  # bcrypt不可用但存的是bcrypt哈希，无法验证
    # PBKDF2 哈希（以 $pbkdf2$ 开头）
    elif hashed.startswith('$pbkdf2$'):
        import hashlib
        import base64
        try:
            parts = hashed.split("$")
            if len(parts) != 3:
                return False
            salt = parts[1]
            stored_key = parts[2]
            key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000)
            return base64.b64encode(key).decode('utf-8') == stored_key
        except Exception:
            return False
    else:
        return False  # 未知格式


def _get_connection() -> sqlite3.Connection:
    """获取数据库连接(P6.E: 使用连接池,60s 内同线程复用)"""
    from db.connection import get_connection
    return get_connection(DB_PATH)


def _init_database():
    """初始化账号数据库"""
    conn = _get_connection()
    cursor = conn.cursor()

    # 账号表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS accounts (
            account_id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_login TEXT,
            is_active INTEGER DEFAULT 1
        )
    ''')

    # 会话表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_sessions (
            session_id TEXT PRIMARY KEY,
            account_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            is_valid INTEGER DEFAULT 1,
            last_active TEXT,
            FOREIGN KEY (account_id) REFERENCES accounts(account_id)
        )
    ''')

    # 用户画像关联表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS account_profiles (
            account_id TEXT PRIMARY KEY,
            user_id TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (account_id) REFERENCES accounts(account_id)
        )
    ''')

    # 创建索引
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_accounts_username
        ON accounts(username)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_sessions_account
        ON user_sessions(account_id)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_sessions_expires
        ON user_sessions(expires_at)
    ''')

    conn.commit()
    conn.close()


# 默认会话有效期（7天）
DEFAULT_SESSION_EXPIRY_DAYS = 7


class AccountManager:
    """用户账号管理器"""

    _initialized = False

    def __init__(self):
        if not AccountManager._initialized:
            _init_database()
            AccountManager._initialized = True

    def register(self, username: str, password: str) -> Dict[str, Any]:
        """
        注册新账号

        Args:
            username: 用户名（3-20位字母数字）
            password: 密码（至少6位）

        Returns:
            包含状态和账号信息的字典
        """
        # 验证用户名格式
        username = username.strip()
        if len(username) < 3 or len(username) > 20:
            return {"success": False, "error": "用户名长度必须在3-20个字符之间"}

        if not re.match(r'^[a-zA-Z0-9_]+$', username):
            return {"success": False, "error": "用户名只能包含字母、数字和下划线"}

        # 验证密码强度
        if len(password) < 6:
            return {"success": False, "error": "密码长度至少6位"}

        try:
            conn = _get_connection()
            cursor = conn.cursor()

            # 检查用户名是否已存在
            cursor.execute('SELECT account_id FROM accounts WHERE username = ? AND is_active = 1', (username,))
            if cursor.fetchone():
                conn.close()
                return {"success": False, "error": "用户名已存在"}

            # 创建账号
            account_id = str(uuid.uuid4())[:12]
            password_hash = _hash_password(password)

            cursor.execute('''
                INSERT INTO accounts (account_id, username, password_hash, created_at, is_active)
                VALUES (?, ?, ?, ?, 1)
            ''', (account_id, username, password_hash, datetime.now().isoformat()))

            conn.commit()
            conn.close()

            _auth_logger.info(f"[Auth] 新账号注册: {username} (account_id: {account_id})")

            return {
                "success": True,
                "account_id": account_id,
                "username": username
            }

        except Exception as e:
            _auth_logger.warning(f"[Auth] 注册失败: {e}")
            return {"success": False, "error": f"注册失败: {str(e)}"}

    def login(self, username: str, password: str) -> Dict[str, Any]:
        """
        登录验证

        Args:
            username: 用户名
            password: 密码

        Returns:
            包含登录结果的字典
        """
        username = username.strip()

        try:
            conn = _get_connection()
            cursor = conn.cursor()

            # 查询账号
            cursor.execute('''
                SELECT account_id, username, password_hash, is_active
                FROM accounts
                WHERE username = ?
            ''', (username,))
            row = cursor.fetchone()

            if not row:
                conn.close()
                return {"success": False, "error": "用户名或密码错误"}

            if not row['is_active']:
                conn.close()
                return {"success": False, "error": "账号已被禁用"}

            # 验证密码
            if not _check_password(password, row['password_hash']):
                conn.close()
                return {"success": False, "error": "用户名或密码错误"}

            account_id = row['account_id']

            # 更新最后登录时间
            cursor.execute('''
                UPDATE accounts SET last_login = ? WHERE account_id = ?
            ''', (datetime.now().isoformat(), account_id))

            # 创建会话
            session_id = str(uuid.uuid4())
            expires_at = (datetime.now() + timedelta(days=DEFAULT_SESSION_EXPIRY_DAYS)).isoformat()

            cursor.execute('''
                INSERT INTO user_sessions (session_id, account_id, created_at, expires_at, is_valid, last_active)
                VALUES (?, ?, ?, ?, 1, ?)
            ''', (session_id, account_id, datetime.now().isoformat(), expires_at, datetime.now().isoformat()))

            conn.commit()
            conn.close()

            _auth_logger.info(f"[Auth] 用户登录: {username} (account_id: {account_id})")

            return {
                "success": True,
                "session_id": session_id,
                "account_id": account_id,
                "username": username,
                "expires_at": expires_at
            }

        except Exception as e:
            _auth_logger.warning(f"[Auth] 登录失败: {e}")
            return {"success": False, "error": f"登录失败: {str(e)}"}

    def logout(self, session_id: str) -> bool:
        """
        登出，销毁会话

        Args:
            session_id: 会话ID

        Returns:
            是否成功
        """
        try:
            conn = _get_connection()
            cursor = conn.cursor()

            cursor.execute('''
                UPDATE user_sessions SET is_valid = 0 WHERE session_id = ?
            ''', (session_id,))

            conn.commit()
            affected = cursor.rowcount > 0
            conn.close()

            if affected:
                _auth_logger.info(f"[Auth] 会话销毁: {session_id}")

            return affected

        except Exception as e:
            _auth_logger.warning(f"[Auth] 登出失败: {e}")
            return False

    def validate_session(self, session_id: str) -> Optional[str]:
        """
        验证会话有效性

        Args:
            session_id: 会话ID

        Returns:
            有效的 account_id，如果无效则返回 None
        """
        if not session_id:
            return None

        try:
            conn = _get_connection()
            cursor = conn.cursor()

            cursor.execute('''
                SELECT account_id, expires_at, is_valid
                FROM user_sessions
                WHERE session_id = ?
            ''', (session_id,))
            row = cursor.fetchone()

            if not row:
                conn.close()
                return None

            if not row['is_valid']:
                conn.close()
                return None

            # 检查是否过期
            expires_at = datetime.fromisoformat(row['expires_at'])
            if expires_at < datetime.now():
                # 标记为无效
                cursor.execute('''
                    UPDATE user_sessions SET is_valid = 0 WHERE session_id = ?
                ''', (session_id,))
                conn.commit()
                conn.close()
                return None

            # 更新最后活跃时间
            cursor.execute('''
                UPDATE user_sessions SET last_active = ? WHERE session_id = ?
            ''', (datetime.now().isoformat(), session_id))
            conn.commit()
            conn.close()

            return row['account_id']

        except Exception as e:
            _auth_logger.warning(f"[Auth] 会话验证失败: {e}")
            return None

    def verify_token(
        self,
        headers,
        body: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        P5-D 鉴权: 从 HTTP headers (和 body) 提取 session_id 验证,返回用户身份

        优先顺序:
        1. Authorization: Bearer <session_id> 头
        2. X-Session-Id: <session_id> 头
        3. body.session_id 字段
        4. body.sessionId 字段

        Args:
            headers: 任意 dict-like / HTTP 头对象(BaseHTTPRequestHandler.headers / dict)
            body: 可选 POST body dict,作为最后 fallback

        Returns:
            成功: {"account_id": ..., "user_id": ..., "username": ...}
            失败: None
        """
        token = None

        # 1. Authorization 头
        try:
            auth_header = headers.get("Authorization") if hasattr(headers, "get") else None
            if auth_header:
                if isinstance(auth_header, str) and auth_header.lower().startswith("bearer "):
                    token = auth_header[7:].strip()
        except Exception:
            pass

        # 2. X-Session-Id 头
        if not token:
            try:
                token = headers.get("X-Session-Id") if hasattr(headers, "get") else None
                if token:
                    token = str(token).strip()
            except Exception:
                pass

        # 3. body.session_id / body.sessionId
        if not token and body:
            token = body.get("session_id") or body.get("sessionId")
            if token:
                token = str(token).strip()

        if not token:
            return None

        # 验证 session
        account_id = self.validate_session(token)
        if not account_id:
            return None

        # 获取用户 ID + 用户名
        user_id = self.get_user_id_by_account(account_id)
        info = self.get_account_info(account_id)
        username = info.get("username") if info else None

        return {
            "account_id": account_id,
            "user_id": user_id or account_id,  # 兜底用 account_id
            "username": username,
            "session_id": token,
        }

    def get_account_info(self, account_id: str) -> Optional[Dict[str, Any]]:
        """
        获取账号信息（不含密码）

        Args:
            account_id: 账号ID

        Returns:
            账号信息字典
        """
        try:
            conn = _get_connection()
            cursor = conn.cursor()

            cursor.execute('''
                SELECT account_id, username, created_at, last_login, is_active
                FROM accounts
                WHERE account_id = ?
            ''', (account_id,))
            row = cursor.fetchone()
            conn.close()

            if not row:
                return None

            return {
                "account_id": row['account_id'],
                "username": row['username'],
                "created_at": row['created_at'],
                "last_login": row['last_login'],
                "is_active": bool(row['is_active'])
            }

        except Exception as e:
            _auth_logger.warning(f"[Auth] 获取账号信息失败: {e}")
            return None

    def get_user_id_by_account(self, account_id: str) -> Optional[str]:
        """
        根据账号ID获取关联的用户ID

        Args:
            account_id: 账号ID

        Returns:
            用户ID（如果没有关联则返回 None）
        """
        try:
            conn = _get_connection()
            cursor = conn.cursor()

            cursor.execute('''
                SELECT user_id FROM account_profiles WHERE account_id = ?
            ''', (account_id,))
            row = cursor.fetchone()
            conn.close()

            return row['user_id'] if row else None

        except Exception as e:
            _auth_logger.warning(f"[Auth] 获取用户ID失败: {e}")
            return None

    def link_user_profile(self, account_id: str, user_id: str) -> bool:
        """
        将用户画像关联到账号

        Args:
            account_id: 账号ID
            user_id: 用户画像ID

        Returns:
            是否成功
        """
        try:
            conn = _get_connection()
            cursor = conn.cursor()

            cursor.execute('''
                INSERT OR REPLACE INTO account_profiles (account_id, user_id, created_at)
                VALUES (?, ?, ?)
            ''', (account_id, user_id, datetime.now().isoformat()))

            conn.commit()
            conn.close()
            return True

        except Exception as e:
            _auth_logger.warning(f"[Auth] 关联用户画像失败: {e}")
            return False

    def delete_account(self, account_id: str, password: str) -> bool:
        """
        注销账号

        Args:
            account_id: 账号ID
            password: 密码确认

        Returns:
            是否成功
        """
        try:
            conn = _get_connection()
            cursor = conn.cursor()

            # 获取账号信息
            cursor.execute('SELECT password_hash FROM accounts WHERE account_id = ?', (account_id,))
            row = cursor.fetchone()

            if not row:
                conn.close()
                return False

            # 验证密码
            if not _check_password(password, row['password_hash']):
                conn.close()
                return False

            # 软删除账号
            cursor.execute('UPDATE accounts SET is_active = 0 WHERE account_id = ?', (account_id,))

            # 使所有会话无效
            cursor.execute('UPDATE user_sessions SET is_valid = 0 WHERE account_id = ?', (account_id,))

            conn.commit()
            conn.close()

            _auth_logger.info(f"[Auth] 账号注销: {account_id}")

            return True

        except Exception as e:
            _auth_logger.warning(f"[Auth] 注销账号失败: {e}")
            return False

    def cleanup_expired_sessions(self) -> int:
        """
        清理过期会话

        Returns:
            清理的会话数量
        """
        try:
            conn = _get_connection()
            cursor = conn.cursor()

            cursor.execute('''
                UPDATE user_sessions SET is_valid = 0
                WHERE expires_at < ? AND is_valid = 1
            ''', (datetime.now().isoformat(),))

            affected = cursor.rowcount
            conn.commit()
            conn.close()

            if affected > 0:
                _auth_logger.info(f"[Auth] 清理了 {affected} 个过期会话")

            return affected

        except Exception as e:
            _auth_logger.warning(f"[Auth] 清理过期会话失败: {e}")
            return 0

    def get_session_info(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        获取会话信息

        Args:
            session_id: 会话ID

        Returns:
            会话信息
        """
        try:
            conn = _get_connection()
            cursor = conn.cursor()

            cursor.execute('''
                SELECT s.session_id, s.account_id, s.created_at, s.expires_at, s.is_valid,
                       a.username
                FROM user_sessions s
                JOIN accounts a ON s.account_id = a.account_id
                WHERE s.session_id = ?
            ''', (session_id,))
            row = cursor.fetchone()
            conn.close()

            if not row:
                return None

            return {
                "session_id": row['session_id'],
                "account_id": row['account_id'],
                "username": row['username'],
                "created_at": row['created_at'],
                "expires_at": row['expires_at'],
                "is_valid": bool(row['is_valid'])
            }

        except Exception as e:
            _auth_logger.warning(f"[Auth] 获取会话信息失败: {e}")
            return None

    def get_all_accounts(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        获取所有账号（管理员用）

        Args:
            limit: 返回数量限制

        Returns:
            账号列表
        """
        try:
            conn = _get_connection()
            cursor = conn.cursor()

            cursor.execute('''
                SELECT account_id, username, created_at, last_login, is_active
                FROM accounts
                ORDER BY created_at DESC
                LIMIT ?
            ''', (limit,))

            accounts = []
            for row in cursor.fetchall():
                accounts.append({
                    "account_id": row['account_id'],
                    "username": row['username'],
                    "created_at": row['created_at'],
                    "last_login": row['last_login'],
                    "is_active": bool(row['is_active'])
                })

            conn.close()
            return accounts

        except Exception as e:
            _auth_logger.warning(f"[Auth] 获取账号列表失败: {e}")
            return []
