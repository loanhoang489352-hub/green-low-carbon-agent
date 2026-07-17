"""
健康检查模块 (P5-E)

提供两类探针:
- readiness_probe(): K8s readiness,只查 DB(轻量级,必须 always succeed 才放行)
- health_probe(): 真探活,查 DB + ChromaDB + Scheduler + Metrics

任何组件 DOWN → 整体 503
"""

import sqlite3
import time
from typing import Any, Dict

from .errors import HealthStatus


def _check_accounts_db() -> Dict[str, Any]:
    """accounts.db SELECT 1"""
    try:
        from paths import DATA_DIR

        db_path = DATA_DIR / "accounts.db"
        if not db_path.exists():
            return {"status": HealthStatus.DOWN, "detail": f"DB not found: {db_path}"}
        conn = sqlite3.connect(str(db_path), timeout=2.0)
        try:
            cursor = conn.execute("SELECT 1")
            cursor.fetchone()
        finally:
            conn.close()
        return {"status": HealthStatus.OK, "detail": "SELECT 1 ok"}
    except Exception as e:
        return {"status": HealthStatus.DOWN, "detail": f"{type(e).__name__}: {e}"}


def _check_user_profiles_db() -> Dict[str, Any]:
    """user_profiles.db SELECT 1(辅助)"""
    try:
        from paths import DATA_DIR

        db_path = DATA_DIR / "user_profiles.db"
        if not db_path.exists():
            # 还没初始化,不算 DOWN
            return {"status": HealthStatus.OK, "detail": "not yet initialized"}
        conn = sqlite3.connect(str(db_path), timeout=2.0)
        try:
            conn.execute("SELECT 1").fetchone()
        finally:
            conn.close()
        return {"status": HealthStatus.OK, "detail": "SELECT 1 ok"}
    except Exception as e:
        return {"status": HealthStatus.DEGRADED, "detail": f"{type(e).__name__}: {e}"}


def _check_vector_store() -> Dict[str, Any]:
    """ChromaDB / FAISS / InMemory 探活"""
    try:
        # 延迟导入,避免未启用 RAG 时拖慢启动
        from rag.rag_engine import get_rag_engine

        engine = get_rag_engine()
        if engine is None or engine.vector_store is None:
            return {"status": HealthStatus.OK, "detail": "vector store not configured"}

        store = engine.vector_store
        # store 类型:ChromaVectorStore / FAISSVectorStore / InMemoryVectorStore
        store_type = type(store).__name__
        # 优先用 count(),失败就退到 len(_collection._collection.get()['ids'])
        try:
            count = store.count() if hasattr(store, "count") else None
            if count is None:
                count = (
                    len(store._collection.get()["ids"]) if hasattr(store, "_collection") else "?"
                )
        except Exception:
            count = "?"

        return {
            "status": HealthStatus.OK,
            "detail": f"vector store ok, type={store_type}, count={count}",
        }
    except Exception as e:
        return {"status": HealthStatus.DEGRADED, "detail": f"{type(e).__name__}: {e}"}


def _check_scheduler() -> Dict[str, Any]:
    """APScheduler 状态"""
    try:
        from scheduler import _scheduler

        if _scheduler is None:
            return {"status": HealthStatus.OK, "detail": "scheduler not started"}
        running = _scheduler.running
        if not running:
            return {"status": HealthStatus.DOWN, "detail": "scheduler stopped"}
        job_count = len(_scheduler.get_jobs())
        return {
            "status": HealthStatus.OK,
            "detail": f"scheduler running, jobs={job_count}",
        }
    except Exception as e:
        return {"status": HealthStatus.DEGRADED, "detail": f"{type(e).__name__}: {e}"}


def _check_metrics() -> Dict[str, Any]:
    """MetricsCollector 状态(最后延迟 + 错误率)"""
    try:
        from observability import get_metrics_collector

        m = get_metrics_collector()
        s = m.summary()
        return {
            "status": HealthStatus.OK,
            "detail": {
                "total_calls": s.get("total_calls", 0),
                "error_rate": s.get("error_rate", 0.0),
                "p50_latency_ms": s.get("p50_latency_ms", 0.0),
                "p95_latency_ms": s.get("p95_latency_ms", 0.0),
            },
        }
    except Exception as e:
        return {"status": HealthStatus.DEGRADED, "detail": f"{type(e).__name__}: {e}"}


def _check_disk_space() -> Dict[str, Any]:
    """data/ 目录所在磁盘剩余空间"""
    try:
        from paths import DATA_DIR

        if not DATA_DIR.exists():
            return {"status": HealthStatus.OK, "detail": "data dir not yet created"}
        # 简单 statvfs(Windows 不完全支持,但能拿到 free)
        import shutil

        usage = shutil.disk_usage(str(DATA_DIR))
        free_mb = usage.free / (1024 * 1024)
        if free_mb < 100:  # < 100MB → DOWN
            return {"status": HealthStatus.DOWN, "detail": f"only {free_mb:.1f}MB free"}
        return {
            "status": HealthStatus.OK,
            "detail": f"{free_mb:.1f}MB free",
        }
    except Exception as e:
        return {"status": HealthStatus.DEGRADED, "detail": f"{type(e).__name__}: {e}"}


# ========== P6.B.0: health_probe 缓存 ==========
# 基线测试显示 100 并发 /api/health 8.5 req/s、p50=2s。
# 7 项子探活每次新建 sqlite3 连接 + 7 次 IO = 主要瓶颈。
# 5s TTL 缓存整体结果:K8s 探活(默认 10s interval)+ LB 探活完全无感知。
# 真有故障最迟 5s 内反映,DOWN 状态不缓存(立即上报)。

import threading as _threading

_HEALTH_CACHE: Dict[str, Any] = {}
_HEALTH_CACHE_LOCK = _threading.Lock()
_HEALTH_CACHE_TTL = 5.0  # 秒


def _health_cache_get() -> Dict[str, Any] | None:
    """读缓存,过期或无返 None"""
    with _HEALTH_CACHE_LOCK:
        if not _HEALTH_CACHE:
            return None
        if time.time() - _HEALTH_CACHE.get("_ts", 0) > _HEALTH_CACHE_TTL:
            return None
        return {k: v for k, v in _HEALTH_CACHE.items() if k != "_ts"}


def _health_cache_set(payload: Dict[str, Any]) -> None:
    """写缓存 + 时间戳"""
    with _HEALTH_CACHE_LOCK:
        _HEALTH_CACHE.clear()
        _HEALTH_CACHE.update(payload)
        _HEALTH_CACHE["_ts"] = time.time()


def health_probe(force_refresh: bool = False) -> Dict[str, Any]:
    """
    完整健康检查:返回 checks + 整体 status

    P6.B.0: 5s TTL 缓存,force_refresh=True 跳过缓存。
    DOWN 状态不缓存(下次请求立即重跑,故障快速反映)。

    返回结构:
    {
        "status": "ok" | "degraded" | "down",
        "checks": {
            "accounts_db": {...},
            "user_profiles_db": {...},
            "vector_store": {...},
            "scheduler": {...},
            "metrics": {...},
            "disk_space": {...},
        }
    }
    """
    from .errors import health_check_payload

    # 1) 缓存命中
    if not force_refresh:
        cached = _health_cache_get()
        if cached is not None:
            return cached

    # 2) 真探活
    checks = {
        "accounts_db": _check_accounts_db(),
        "user_profiles_db": _check_user_profiles_db(),
        "vector_store": _check_vector_store(),
        "scheduler": _check_scheduler(),
        "metrics": _check_metrics(),
        "disk_space": _check_disk_space(),
    }
    payload = health_check_payload(checks)

    # 3) DOWN 状态不缓存(快速反映);OK/DEGRADED 缓存
    if payload.get("status") != HealthStatus.DOWN:
        _health_cache_set(payload)

    return payload


def readiness_probe() -> Dict[str, Any]:
    """
    K8s readiness:只查 accounts.db,确认服务能接流量

    返回 {ready: bool, detail: ...}
    """
    db_check = _check_accounts_db()
    if db_check["status"] == HealthStatus.DOWN:
        return {"ready": False, "detail": db_check["detail"]}
    return {"ready": True, "detail": "accounts.db reachable"}
