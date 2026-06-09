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


def _working_memory_heartbeat() -> None:
    """P4-H:每 4 小时:工作记忆 heartbeat(OpenClaw 风格)

    1) 清理过期 key(超过 24h 未访问且 importance < 0.8)
    2) 把高 importance (≥0.7) 的 key 晋升到长期记忆
    3) 写盘 JSON 快照
    """
    try:
        from memory.working import get_working_memory, WORKSPACE_TTL_HOURS
        from memory.memory_agent import promote_working_to_long_term
        wm = get_working_memory()
        # 1) 清理过期
        removed = wm.cleanup_expired(ttl_hours=WORKSPACE_TTL_HOURS)
        # 2) 晋升:遍历每个用户,挑高 importance 的 key
        promoted = 0
        for uid in wm.list_users():
            for k in wm.keys(uid):
                if promote_working_to_long_term(uid, k, importance_threshold=0.7):
                    promoted += 1
                    wm.delete(uid, k, agent_name="heartbeat")
        # 3) 写盘
        for uid in wm.list_users():
            wm._save_snapshot(uid)
        logger.info(
            "[Scheduler] 工作记忆 heartbeat 完成, 清理 %d 过期, 晋升 %d 长期",
            removed, promoted,
        )
    except Exception as e:
        logger.exception("[Scheduler] 工作记忆 heartbeat 失败: %s", e)


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

        # P4-H: 每 4 小时 — 工作记忆 heartbeat(OpenClaw 风格:清理过期 + 晋升)
        sched.add_job(
            _working_memory_heartbeat,
            CronTrigger.from_crontab("0 */4 * * *"),
            id="working_memory_heartbeat",
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
