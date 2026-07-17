"""
Query Cache — P6.C

按 (标准化 query + 画像指纹) 缓存 LLM 响应(message + suggestions),
1h TTL,画像更新触发 invalidate。

不缓存:
- knowledge_refs(实时 RAG 检索,KB 更新后可能变)
- recommendations(画像变化会改推荐)
- profile_updates(每次都要回写)
- conversation_id / timestamp(每次唯一)
- memory_hints(记忆召回实时)
- personalization_info(画像快照)

metrics:暴露 hit / miss / size / hit_rate 给 /api/metrics(P5-B)
invalidation:订阅画像更新事件,清除该 user_id 的所有缓存
"""

import hashlib
import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from paths import DATA_DIR

logger = logging.getLogger(__name__)


# ========== 缓存键构造 ==========


def _normalize_query(query: str) -> str:
    """标准化 query:小写 + 去空白 + 去标点

    '  你好  ' / '你好!' / '你好?' / '你好' → 同一键
    """
    import re

    s = query.strip().lower()
    s = re.sub(r"[\s　]+", " ", s)  # 多个空白 → 1 个
    s = re.sub(r"[^\w\s一-鿿]+", "", s)  # 去标点(保留中文/英文/数字)
    return s[:200]  # 截断 200 字符


def _profile_fingerprint(user_profile: Dict[str, Any]) -> str:
    """画像指纹:影响 LLM 响应的关键字段

    包含:region / interests / knowledge_level / behavior_stage
          / eco_focus / suggestion_intensity
    """
    eco = user_profile.get("eco_profile", {}) or {}
    basic = user_profile.get("basic_info", {}) or {}
    strategy = user_profile.get("behavior", {}) or {}

    fingerprint = {
        "region": basic.get("region", ""),
        "interests": sorted(eco.get("primary_interests", []) or []),
        "knowledge_level": eco.get("knowledge_level", ""),
        "behavior_stage": eco.get("behavior_stage", ""),
        "eco_focus": eco.get("focus", ""),
        "suggestion_intensity": strategy.get("suggestion_intensity", ""),
    }
    s = json.dumps(fingerprint, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:12]


def _make_cache_key(query: str, user_id: str, user_profile: Dict[str, Any]) -> str:
    """缓存键 = sha1(用户 + 标准化query + 画像指纹)"""
    nq = _normalize_query(query)
    fp = _profile_fingerprint(user_profile)
    raw = f"{user_id}|{nq}|{fp}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


# ========== SQLite-backed 缓存 ==========


class QueryCache:
    """
    LLM 响应缓存
    - key: SHA1(用户 + 标准化 query + 画像指纹)
    - value: {message, suggestions} JSON
    - TTL: 1h(默认)
    - invalidation: invalidate(user_id) 清该用户全部
    """

    DEFAULT_TTL = 3600.0  # 1h

    def __init__(self, db_path: Optional[Path] = None, ttl: float = DEFAULT_TTL):
        self.db_path = Path(db_path) if db_path else (DATA_DIR / "query_cache.db")
        self.ttl = ttl
        self._lock = threading.Lock()
        # metrics
        self._hits = 0
        self._misses = 0
        self._sets = 0
        self._invalidations = 0
        self._init_db()

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS query_cache (
                    cache_key TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON query_cache(user_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_expires_at ON query_cache(expires_at)")

    def get(
        self, query: str, user_id: str, user_profile: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        读缓存。命中返 {message, suggestions};miss/过期返 None。
        """
        key = _make_cache_key(query, user_id, user_profile)
        now = time.time()
        try:
            with sqlite3.connect(str(self.db_path), timeout=2.0) as conn:
                row = conn.execute(
                    "SELECT payload, expires_at FROM query_cache WHERE cache_key = ?",
                    (key,),
                ).fetchone()
            if row is None:
                with self._lock:
                    self._misses += 1
                return None
            payload_json, expires_at = row
            if expires_at < now:
                # 过期,惰性删除
                self._delete_key(key)
                with self._lock:
                    self._misses += 1
                return None
            with self._lock:
                self._hits += 1
            return json.loads(payload_json)
        except Exception as e:
            logger.warning("[QueryCache] get 异常: %s", e)
            with self._lock:
                self._misses += 1
            return None

    def set(
        self,
        query: str,
        user_id: str,
        user_profile: Dict[str, Any],
        message: str,
        suggestions: list,
    ) -> bool:
        """
        写缓存。返 True 成功 / False 失败(非致命,不影响主路径)
        """
        key = _make_cache_key(query, user_id, user_profile)
        now = time.time()
        payload = json.dumps(
            {"message": message, "suggestions": suggestions},
            ensure_ascii=False,
        )
        try:
            with sqlite3.connect(str(self.db_path), timeout=2.0) as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO query_cache
                       (cache_key, user_id, payload, created_at, expires_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (key, user_id, payload, now, now + self.ttl),
                )
            with self._lock:
                self._sets += 1
            return True
        except Exception as e:
            logger.warning("[QueryCache] set 异常: %s", e)
            return False

    def invalidate(self, user_id: str) -> int:
        """
        清除某用户所有缓存(画像变更时调)

        返清除条数
        """
        try:
            with sqlite3.connect(str(self.db_path), timeout=2.0) as conn:
                cur = conn.execute("DELETE FROM query_cache WHERE user_id = ?", (user_id,))
                count = cur.rowcount
            with self._lock:
                self._invalidations += count
            logger.info("[QueryCache] invalidate user=%s 清 %d 条", user_id, count)
            return count
        except Exception as e:
            logger.warning("[QueryCache] invalidate 异常: %s", e)
            return 0

    def _delete_key(self, key: str) -> None:
        try:
            with sqlite3.connect(str(self.db_path), timeout=2.0) as conn:
                conn.execute("DELETE FROM query_cache WHERE cache_key = ?", (key,))
        except Exception:
            pass

    def cleanup_expired(self) -> int:
        """清理过期条目(可由 scheduler 周期调)"""
        try:
            with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
                cur = conn.execute("DELETE FROM query_cache WHERE expires_at < ?", (time.time(),))
                count = cur.rowcount
            return count
        except Exception as e:
            logger.warning("[QueryCache] cleanup 异常: %s", e)
            return 0

    def stats(self) -> Dict[str, Any]:
        """返回 metrics dict(P5-B 接入 /api/metrics)"""
        with self._lock:
            hits = self._hits
            misses = self._misses
            sets = self._sets
            invalidations = self._invalidations
        total = hits + misses
        hit_rate = (hits / total) if total > 0 else 0.0
        # 当前 size(实时查表,慢的话后续可缓存)
        try:
            with sqlite3.connect(str(self.db_path), timeout=2.0) as conn:
                size = conn.execute("SELECT COUNT(*) FROM query_cache").fetchone()[0]
        except Exception:
            size = -1
        return {
            "hits": hits,
            "misses": misses,
            "sets": sets,
            "invalidations": invalidations,
            "hit_rate": hit_rate,
            "size": size,
            "ttl_seconds": self.ttl,
        }

    def reset_metrics(self) -> None:
        """重置 hits/misses/sets/invalidations 计数(测试用)"""
        with self._lock:
            self._hits = 0
            self._misses = 0
            self._sets = 0
            self._invalidations = 0


# ========== 全局单例 ==========

_cache_instance: Optional[QueryCache] = None
_cache_lock = threading.Lock()


def get_query_cache() -> QueryCache:
    """双检锁单例"""
    global _cache_instance
    if _cache_instance is None:
        with _cache_lock:
            if _cache_instance is None:
                _cache_instance = QueryCache()
    return _cache_instance


def reset_query_cache() -> None:
    """重置(测试用)"""
    global _cache_instance
    with _cache_lock:
        _cache_instance = None
