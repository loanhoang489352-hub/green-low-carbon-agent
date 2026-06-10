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
    SHORT_TERM_DB,
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
                    tags TEXT,
                    embedding BLOB
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
    # short_term.db (P5-G: STM 持久化)
    (
        str(SHORT_TERM_DB),
        "short_term",
        [
            ("conversations", """
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """),
            ("conversation_meta", """
                CREATE TABLE IF NOT EXISTS conversation_meta (
                    conversation_id TEXT PRIMARY KEY,
                    user_id TEXT,
                    message_count INTEGER DEFAULT 0,
                    last_activity TEXT,
                    created_at TEXT
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
                    intent_type TEXT,
                    context TEXT,
                    carbon_impact REAL,
                    duration_minutes INTEGER,
                    related_interests TEXT,
                    created_at TEXT NOT NULL
                )
            """),
            ("user_goals", """
                CREATE TABLE IF NOT EXISTS user_goals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    goal_type TEXT NOT NULL,
                    target_value REAL NOT NULL,
                    current_value REAL DEFAULT 0,
                    deadline TEXT,
                    status TEXT DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """),
            ("user_achievements", """
                CREATE TABLE IF NOT EXISTS user_achievements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    achievement_code TEXT NOT NULL,
                    earned_at TEXT NOT NULL,
                    metadata TEXT,
                    UNIQUE(user_id, achievement_code)
                )
            """),
            ("carbon_footprint_log", """
                CREATE TABLE IF NOT EXISTS carbon_footprint_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    amount_kg_co2e REAL NOT NULL,
                    recorded_at TEXT NOT NULL,
                    source TEXT,
                    metadata TEXT
                )
            """),
        ],
    ),
    # P5-I.B: 审计日志(写入 accounts.db,跨模块共享)
    (
        str(ACCOUNTS_DB),
        "audit",
        [
            ("audit_log", """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    action TEXT NOT NULL,
                    target TEXT,
                    ip TEXT,
                    user_agent TEXT,
                    status_code INTEGER,
                    detail TEXT,
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
    P4-C: 对已存在的表,补齐新增列(intent_type / context / carbon_impact 等)
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
    # P4-C: 补齐新增列(对已存在的表)
    _migrate_existing_columns()
    return created


def _migrate_existing_columns() -> None:
    """对已存在的表,补齐新增列(P4-C)

    用 PRAGMA table_info 检查列是否存在,缺失则 ALTER TABLE ADD COLUMN。
    """
    migrations: List[Tuple[str, str, str, str]] = [
        # (db_path, table, column, type_with_default)
        (str(BEHAVIOR_TRACKER_DB), "behavior_events", "event_data", "TEXT"),
        (str(BEHAVIOR_TRACKER_DB), "behavior_events", "intent_type", "TEXT"),
        (str(BEHAVIOR_TRACKER_DB), "behavior_events", "context", "TEXT"),
        (str(BEHAVIOR_TRACKER_DB), "behavior_events", "carbon_impact", "REAL"),
        (str(BEHAVIOR_TRACKER_DB), "behavior_events", "duration_minutes", "INTEGER"),
        (str(BEHAVIOR_TRACKER_DB), "behavior_events", "related_interests", "TEXT"),
        # P5-G: LTM 向量检索 — embedding 列(384-dim float32 → 1536 bytes BLOB)
        (str(LONG_TERM_MEMORY_DB), "user_memories", "embedding", "BLOB"),
        # P5-I.B: 审计日志列(避免旧表没 detail 等字段)
        (str(ACCOUNTS_DB), "audit_log", "user_id", "TEXT"),
        (str(ACCOUNTS_DB), "audit_log", "target", "TEXT"),
        (str(ACCOUNTS_DB), "audit_log", "ip", "TEXT"),
        (str(ACCOUNTS_DB), "audit_log", "user_agent", "TEXT"),
        (str(ACCOUNTS_DB), "audit_log", "status_code", "INTEGER"),
        (str(ACCOUNTS_DB), "audit_log", "detail", "TEXT"),
    ]
    for db_path, table, column, col_type in migrations:
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA table_info({table})")
            existing = {row[1] for row in cursor.fetchall()}
            if column not in existing:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
                conn.commit()
                logger.info("[Schema-Migration] %s.%s ADD COLUMN %s %s",
                            db_path, table, column, col_type)
            conn.close()
        except Exception as e:
            logger.warning("[Schema-Migration] %s.%s.%s failed: %s",
                           db_path, table, column, e)


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
