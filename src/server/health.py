"""
健康检查模块 (P5-E)

提供两类探针:
- readiness_probe(): K8s readiness,只查 DB(轻量级,必须 always succeed 才放行)
- health_probe(): 真探活,查 DB + ChromaDB + Scheduler + Metrics

任何组件 DOWN → 整体 503
"""
import os
import sqlite3
import time
import traceback
from pathlib import Path
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
        from rag.vector_store import _DEFAULT_VECTOR_STORE
        from rag.rag_engine import get_rag_engine

        engine = get_rag_engine()
        if engine is None or engine.vector_store is None:
            return {"status": HealthStatus.OK, "detail": "vector store not configured"}

        store = engine.vector_store
        # 优先用 count(),失败就退到 len(_collection._collection.get()['ids'])
        try:
            count = store.count() if hasattr(store, "count") else None
            if count is None:
                count = len(store._collection.get()["ids"]) if hasattr(store, "_collection") else "?"
        except Exception:
            count = "?"

        return {
            "status": HealthStatus.OK,
            "detail": f"vector store ok, type={_DEFAULT_VECTOR_STORE}, count={count}",
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


def health_probe() -> Dict[str, Any]:
    """
    完整健康检查:返回 checks + 整体 status

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

    checks = {
        "accounts_db": _check_accounts_db(),
        "user_profiles_db": _check_user_profiles_db(),
        "vector_store": _check_vector_store(),
        "scheduler": _check_scheduler(),
        "metrics": _check_metrics(),
        "disk_space": _check_disk_space(),
    }
    payload = health_check_payload(checks)
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
