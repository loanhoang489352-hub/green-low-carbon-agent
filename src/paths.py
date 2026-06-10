"""
项目路径统一管理
所有模块应从这里导入路径,避免散落的 Path(__file__).parent.parent.parent
"""
from pathlib import Path

# src/paths.py → 项目根
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
SRC_DIR: Path = Path(__file__).resolve().parent

DATA_DIR: Path = PROJECT_ROOT / "data"
KNOWLEDGE_BASE_DIR: Path = PROJECT_ROOT / "knowledge_base"
CONFIG_DIR: Path = PROJECT_ROOT / "config"
WEB_DIR: Path = PROJECT_ROOT / "web"
LOG_DIR: Path = DATA_DIR / "logs"
VECTOR_DB_DIR: Path = DATA_DIR / "vector_db"

# 常用数据库路径
ACCOUNTS_DB: Path = DATA_DIR / "accounts.db"
USER_PROFILES_DB: Path = DATA_DIR / "user_profiles.db"
FEEDBACK_DB: Path = DATA_DIR / "feedback.db"
POLICY_UPDATES_DB: Path = DATA_DIR / "policy_updates.db"
SHORT_TERM_DB: Path = DATA_DIR / "short_term.db"  # P5-G: STM 持久化
LONG_TERM_MEMORY_DB: Path = DATA_DIR / "long_term_memory.db"
BEHAVIOR_TRACKER_DB: Path = DATA_DIR / "behavior_tracker.db"


def ensure_data_dirs() -> None:
    """确保所有数据目录存在"""
    for d in (DATA_DIR, VECTOR_DB_DIR, LOG_DIR, KNOWLEDGE_BASE_DIR):
        d.mkdir(parents=True, exist_ok=True)
