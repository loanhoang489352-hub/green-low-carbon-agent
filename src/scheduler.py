"""
APScheduler 集成
启动后台调度器,管理每日定时任务:
- 02:00 全量增量知识/政策
- 03:00 长期记忆衰减
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

_scheduler: Optional[BackgroundScheduler] = None
_lock = threading.Lock()


def _daily_kb_update() -> None:
    """每日 02:00:全量增量知识/政策更新,触发 KNOWLEDGE_UPDATED 事件 → RAG 重建"""
    try:
        from knowledge.updater import KnowledgeUpdater
        updater = KnowledgeUpdater()
        count = updater.process_updates()
        logger.info("[Scheduler] 每日知识更新完成,新增 %d 项", count)
    except Exception as e:
        logger.exception("[Scheduler] 每日知识更新失败: %s", e)


def _memory_decay() -> None:
    """每日 03:00:长期记忆 importance 衰减(半衰期 30 天)"""
    try:
        from memory.long_term import LongTermMemory
        ltm = LongTermMemory()
        affected = ltm.decay_importance(half_life_days=30)
        logger.info("[Scheduler] 记忆衰减完成,影响 %d 条", affected)
    except Exception as e:
        logger.exception("[Scheduler] 记忆衰减失败: %s", e)


def _short_term_cleanup() -> None:
    """每 6 小时:短期记忆 TTL 清理"""
    try:
        from memory.short_term import get_short_term_memory
        stm = get_short_term_memory()
        removed = stm.cleanup_expired()
        logger.info("[Scheduler] 短期记忆清理完成,删除 %d 条会话", removed)
    except Exception as e:
        logger.exception("[Scheduler] 短期记忆清理失败: %s", e)


def start_scheduler() -> BackgroundScheduler:
    """启动调度器(单例)"""
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    with _lock:
        if _scheduler is not None:
            return _scheduler
        sched = BackgroundScheduler(daemon=True)

        # 每日 02:00 — 知识/政策增量更新
        sched.add_job(
            _daily_kb_update,
            CronTrigger.from_crontab("0 2 * * *"),
            id="daily_kb_update",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        # 每日 03:00 — 长期记忆衰减
        sched.add_job(
            _memory_decay,
            CronTrigger.from_crontab("0 3 * * *"),
            id="memory_decay",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        # 每 6 小时 — 短期记忆清理
        sched.add_job(
            _short_term_cleanup,
            CronTrigger.from_crontab("0 */6 * * *"),
            id="short_term_cleanup",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        sched.start()
        _scheduler = sched
        logger.info("[Scheduler] 启动完成,已注册 %d 个 cron job", len(sched.get_jobs()))
    return _scheduler


def get_scheduler() -> Optional[BackgroundScheduler]:
    """获取当前调度器(未启动时返回 None)"""
    return _scheduler


def stop_scheduler(wait: bool = False) -> None:
    """停止调度器"""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=wait)
        _scheduler = None
        logger.info("[Scheduler] 已停止")


def reset_scheduler() -> None:
    """重置(测试用)"""
    stop_scheduler(wait=False)
