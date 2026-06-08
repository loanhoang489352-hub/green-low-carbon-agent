"""
统一 Schema Registry
集中管理所有 SQLite 数据库表结构,作为 Alembic 全量迁移的轻量替代

- 各模块的 _init_database() 应委托给本模块
- 未来切换到 Alembic 时,本模块的 SCHEMAS 即初始迁移内容
"""
import logging
import sqlite3
from typing import Dict, List, Tuple

from paths import (
    ACCOUNTS_DB,
    BEHAVIOR_TRACKER_DB,
    DATA_DIR,
    FEEDBACK_DB,
    LONG_TERM_MEMORY_DB,
    POLICY_UPDATES_DB,
    USER_PROFILES_DB,
    ensure_data_dirs,
)

logger = logging.getLogger(__name__)


# (db_path, [(table_name, create_sql), ...])
SCHEMAS: List[Tuple[str, str, List[Tuple[str, str]]]] = [
    # accounts.db
    (
        str(ACCOUNTS_DB),
        "accounts",
        [
            ("accounts", """
                CREATE TABLE IF NOT EXISTS accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    email TEXT,
                    created_at TEXT NOT NULL,
                    last_login TEXT,
                    is_active INTEGER DEFAULT 1
                )
            """),
            ("sessions", """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    account_id INTEGER NOT NULL,
                    user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    FOREIGN KEY (account_id) REFERENCES accounts(id)
                )
            """),
        ],
    ),
    # user_profiles.db
    (
        str(USER_PROFILES_DB),
        "user_profiles",
        [
            ("profiles", """
                CREATE TABLE IF NOT EXISTS profiles (
                    user_id TEXT PRIMARY KEY,
                    basic_info TEXT,
                    eco_profile TEXT,
                    behavior TEXT,
                    preferences TEXT,
                    communication TEXT,
                    stats TEXT,
                    metadata TEXT,
                    onboarding_completed INTEGER DEFAULT 0,
                    onboarding_step INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """),
        ],
    ),
    # feedback.db
    (
        str(FEEDBACK_DB),
        "feedback",
        [
            ("message_feedback", """
                CREATE TABLE IF NOT EXISTS message_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    conversation_id TEXT,
                    feedback_type TEXT NOT NULL CHECK(feedback_type IN ('like', 'dislike', 'comment')),
                    reason TEXT,
                    comment TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(message_id, user_id, feedback_type)
                )
            """),
        ],
    ),
    # policy_updates.db
    (
        str(POLICY_UPDATES_DB),
        "policy_updates",
        [
            ("policies", """
                CREATE TABLE IF NOT EXISTS policies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    source TEXT NOT NULL,
                    url TEXT,
                    content TEXT NOT NULL,
                    publish_date TEXT,
                    fetched_at TEXT NOT NULL,
                    UNIQUE(title, source)
                )
            """),
            ("update_logs", """
                CREATE TABLE IF NOT EXISTS update_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    checked_at TEXT NOT NULL,
                    has_update INTEGER DEFAULT 0,
                    error TEXT
                )
            """),
        ],
    ),
    # long_term_memory.db
    (
        str(LONG_TERM_MEMORY_DB),
        "long_term_memory",
        [
            ("user_memories", """
                CREATE TABLE IF NOT EXISTS user_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    importance REAL DEFAULT 0.5,
                    created_at TEXT NOT NULL,
                    last_accessed TEXT NOT NULL,
                    access_count INTEGER DEFAULT 0,
                    tags TEXT
                )
            """),
            ("user_preferences", """
                CREATE TABLE IF NOT EXISTS user_preferences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    preference_type TEXT NOT NULL,
                    value TEXT NOT NULL,
                    confidence REAL DEFAULT 0.5,
                    updated_at TEXT NOT NULL,
                    UNIQUE(user_id, preference_type)
                )
            """),
        ],
    ),
    # behavior_tracker.db
    (
        str(BEHAVIOR_TRACKER_DB),
        "behavior_tracker",
        [
            ("behavior_events", """
                CREATE TABLE IF NOT EXISTS behavior_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_data TEXT,
                    created_at TEXT NOT NULL
                )
            """),
        ],
    ),
]


def _enable_wal(conn: sqlite3.Connection) -> None:
    """启用 WAL 模式"""
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")


def init_all_schemas() -> Dict[str, List[str]]:
    """初始化所有数据库 schema,返回 {db_name: [table_names]}

    幂等:已存在的表不会重建
    """
    ensure_data_dirs()
    created: Dict[str, List[str]] = {}
    for db_path, db_name, tables in SCHEMAS:
        conn = sqlite3.connect(db_path)
        _enable_wal(conn)
        for table_name, create_sql in tables:
            conn.execute(create_sql)
            created.setdefault(db_name, []).append(table_name)
        conn.commit()
        conn.close()
        logger.info("[Schema] %s: %d tables ready", db_name, len(tables))
    return created


def get_schema_info() -> List[Dict[str, str]]:
    """返回所有 schema 元信息(供文档/Alembic 迁移参考)"""
    return [
        {
            "db": db_name,
            "db_path": db_path,
            "tables": [{"name": t, "sql": s} for t, s in tables],
        }
        for db_path, db_name, tables in SCHEMAS
    ]


if __name__ == "__main__":
    import json
    result = init_all_schemas()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("\nSchema 数量:", len(SCHEMAS))
    print("表总数:", sum(len(t) for _, _, t in SCHEMAS))
