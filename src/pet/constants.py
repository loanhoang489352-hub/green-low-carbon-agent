"""
任务6: 宠物养成 - 数据层
独立表 + 低碳行为双写,不污染原 carbon_footprint。
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

# 任务6: 独立 DB 文件,SQLite WAL
PET_DB_PATH = Path(__file__).parent.parent.parent / "data" / "pet.db"
_LOCK = threading.Lock()


def _get_conn() -> sqlite3.Connection:
    PET_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(PET_DB_PATH), check_same_thread=False, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


def init_pet_schema() -> None:
    """任务6: 幂等初始化 7 张表"""
    with _LOCK:
        conn = _get_conn()
        try:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS pets (
                user_id TEXT PRIMARY KEY,
                level INTEGER DEFAULT 1,
                exp INTEGER DEFAULT 0,
                hunger INTEGER DEFAULT 50,
                mood INTEGER DEFAULT 50,
                vitality INTEGER DEFAULT 50,
                coins INTEGER DEFAULT 0,
                fragments INTEGER DEFAULT 0,
                appearance TEXT DEFAULT 'seed',
                habitat TEXT DEFAULT 'green_house',
                total_co2_saved REAL DEFAULT 0.0,
                consecutive_days INTEGER DEFAULT 0,
                last_active_date TEXT,
                last_decay_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS pet_state_change_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                behavior_type TEXT,
                amount REAL,
                co2_saved REAL,
                rewards_json TEXT,
                old_state_json TEXT,
                new_state_json TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS pet_appearance_unlocks (
                user_id TEXT,
                appearance_id TEXT,
                unlocked_at TEXT DEFAULT CURRENT_TIMESTAMP,
                equipped BOOLEAN DEFAULT FALSE,
                PRIMARY KEY (user_id, appearance_id)
            );

            CREATE TABLE IF NOT EXISTS pet_habitat_unlocks (
                user_id TEXT,
                habitat_id TEXT,
                unlocked_at TEXT DEFAULT CURRENT_TIMESTAMP,
                current BOOLEAN DEFAULT FALSE,
                PRIMARY KEY (user_id, habitat_id)
            );

            CREATE TABLE IF NOT EXISTS pet_achievements (
                user_id TEXT,
                achievement_id TEXT,
                unlocked_at TEXT DEFAULT CURRENT_TIMESTAMP,
                reward_claimed BOOLEAN DEFAULT FALSE,
                PRIMARY KEY (user_id, achievement_id)
            );

            CREATE TABLE IF NOT EXISTS pet_skill_uses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                skill_id TEXT,
                used_at TEXT DEFAULT CURRENT_TIMESTAMP,
                result_json TEXT
            );

            CREATE TABLE IF NOT EXISTS pet_codex (
                user_id TEXT,
                codex_id TEXT,
                unlocked_at TEXT,
                progress INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, codex_id)
            );
            """)
            conn.commit()
        finally:
            conn.close()


# 任务6: 启动时自动初始化(无侵入,可重复调)
init_pet_schema()
