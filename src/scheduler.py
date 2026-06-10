"""
APScheduler 集成
启动后台调度器,管理每日定时任务:
- 02:00 全量增量知识/政策
- 03:00 长期记忆衰减
- 每小时 短→长 整合 (P5-F)
- 每 6 小时 短期记忆 TTL 清理
- 每 4 小时 工作记忆 heartbeat (P4-H)
- 启动时 后台异步 RAG 重建 (P5-F,避免阻塞)
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


def _consolidate_short_to_long() -> None:
    """P5-F:每小时 短→长 整合

    遍历短期记忆中所有 conversation,触发 Consolidator.consolidate
    (内部走策略模式:阈值策略 / 自适应策略)
    """
    try:
        from memory.short_term import get_short_term_memory
        from memory.consolidation import get_consolidator
        stm = get_short_term_memory()
        consolidator = get_consolidator()
        total = 0
        # 遍历所有活跃 conversation
        for cid, meta in list(stm.metadata.items()):
            uid = meta.get("user_id") if isinstance(meta, dict) else None
            if not uid:
                continue
            consolidator.update_conversation_activity(cid)
            consolidator.update_message_count(cid, count=meta.get("message_count", 0))
            n = consolidator.consolidate(uid, cid)
            total += n
        logger.info("[Scheduler] 短→长整合完成,共晋升 %d 条", total)
    except Exception as e:
        logger.exception("[Scheduler] 短→长整合失败: %s", e)


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


def _async_rag_rebuild_on_startup() -> None:
    """P5-F:启动时后台异步 RAG 重建(避免阻塞主进程)"""
    try:
        from rag.rag_engine import get_rag_engine
        from paths import KNOWLEDGE_BASE_DIR
        engine = get_rag_engine()
        if engine is None:
            logger.info("[Scheduler] RAG 引擎未启用,跳过异步重建")
            return
        # 防御性:某些 mock/test 场景下 _initialized 属性可能不存在
        if not getattr(engine, "_initialized", False):
            if hasattr(engine, "initialize"):
                try:
                    engine.initialize(knowledge_base_path=str(KNOWLEDGE_BASE_DIR))
                except Exception as e:
                    logger.warning("[Scheduler] RAG 引擎 initialize 失败: %s", e)
        if hasattr(engine, "rebuild_index"):
            count = engine.rebuild_index(str(KNOWLEDGE_BASE_DIR))
            logger.info("[Scheduler] 启动时 RAG 重建完成, 共 %d 个文档块", count)
        else:
            logger.info("[Scheduler] RAG 引擎无 rebuild_index 方法,跳过")
    except Exception as e:
        logger.exception("[Scheduler] 启动时 RAG 重建异常: %s", e)


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

        # P5-F: 每小时 短→长 整合
        sched.add_job(
            _consolidate_short_to_long,
            CronTrigger.from_crontab("17 * * * *"),  # 17 分每小时(避开 :00 / :30 高峰)
            id="consolidate_short_to_long",
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

        # P5-F: 启动时后台异步触发 RAG 重建(不阻塞主进程)
        try:
            rebuild_thread = threading.Thread(
                target=_async_rag_rebuild_on_startup,
                name="startup-rag-rebuild",
                daemon=True,
            )
            rebuild_thread.start()
        except Exception as e:
            logger.warning("[Scheduler] 启动后台 RAG 重建线程失败: %s", e)
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
