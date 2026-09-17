"""
知识库更新事件订阅者
收到 KNOWLEDGE_UPDATED 时通知 RAG 重建索引

修复:事件去抖 + 后台线程重建
1) 窗口(_DEBOUNCE_SECONDS)内多次 KNOWLEDGE_UPDATED 合并为一次重建
2) 重建在后台线程执行,不在事件发布线程同步跑全量重嵌入
3) 重建期间的新事件不丢弃,标记 pending,当前重建完成后统一再重建一次
"""

import logging
import threading

from events import EventType, get_event_bus

logger = logging.getLogger(__name__)

# 去抖窗口:窗口内多次 KNOWLEDGE_UPDATED 合并为一次重建
_DEBOUNCE_SECONDS = 5.0

_lock = threading.Lock()
_pending_rebuild = False  # 有待重建事件(重建期间新事件不丢弃)
_debounce_timer = None
_worker_thread = None


def _on_knowledge_updated(event_type, paths=None, count=None, **kwargs) -> None:
    """收到知识库更新事件:去抖合并,窗口结束后由后台线程重建

    事件发布线程只做标记 + 重置定时器,绝不在发布线程同步做全量重嵌入。
    """
    global _pending_rebuild, _debounce_timer
    with _lock:
        _pending_rebuild = True
        if _debounce_timer is not None:
            _debounce_timer.cancel()
        _debounce_timer = threading.Timer(_DEBOUNCE_SECONDS, _debounce_fired)
        _debounce_timer.daemon = True
        _debounce_timer.start()
    logger.info(
        "[RAG Subscriber] 知识库更新事件(paths=%s count=%s),%ds 内合并后重建",
        paths,
        count,
        _DEBOUNCE_SECONDS,
    )


def _debounce_fired() -> None:
    """去抖窗口结束:无重建线程在跑则启动一个,否则保持 pending 等它收尾"""
    global _pending_rebuild, _worker_thread
    with _lock:
        if not _pending_rebuild:
            return
        if _worker_thread is not None and _worker_thread.is_alive():
            # 已有重建在跑:保留 pending,当前线程跑完后会再重建一次
            return
        _pending_rebuild = False
        _worker_thread = threading.Thread(
            target=_rebuild_worker, name="rag-subscriber-rebuild", daemon=True
        )
        _worker_thread.start()


def _rebuild_worker() -> None:
    """后台重建线程:重建完成后若期间又有新事件(pending),再重建一次"""
    while True:
        rebuilt = False
        try:
            from paths import KNOWLEDGE_BASE_DIR

            # 1) 优先单例(任务后 agent.rag_engine 即同一单例)
            try:
                from rag.rag_engine import get_rag_engine

                engine = get_rag_engine()
                if engine.is_enabled:
                    n = engine.rebuild_index(str(KNOWLEDGE_BASE_DIR))
                    logger.info("[RAG Subscriber] 索引已重建(单例): %d 个文档", n)
                    rebuilt = True
            except Exception as e:
                logger.warning("[RAG Subscriber] 单例方式失败, 退化: %s", e)

            if not rebuilt:
                # 2) 退化到 main.get_agent()(向后兼容)
                from main import get_agent

                agent = get_agent()
                if agent is not None and getattr(agent, "rag_engine", None) is not None:
                    n = agent.rag_engine.rebuild_index(str(KNOWLEDGE_BASE_DIR))
                    logger.info("[RAG Subscriber] 索引已重建(agent): %d 个文档", n)
                else:
                    logger.info("[RAG Subscriber] 引擎未就绪,本次事件仅记录日志")
        except Exception as e:
            logger.exception("[RAG Subscriber] 处理失败: %s", e)

        with _lock:
            if not _pending_rebuild:
                return
            _pending_rebuild = False


def register_rag_subscribers() -> None:
    """注册 RAG 事件订阅者"""
    bus = get_event_bus()
    bus.subscribe(EventType.KNOWLEDGE_UPDATED, _on_knowledge_updated)
    logger.info("RAG 事件订阅者已注册")


# 兼容别名:旧测试(test_p4e_rag_kb)直接 import _do_rebuild 并期望
# "agent 未就绪时仅记日志、不抛异常"。生产路径已改用去抖+后台线程(_rebuild_worker),
# 此处保留同名同步重建入口供测试/外部调用,行为与旧版一致。
def _do_rebuild(paths=None, count=None) -> None:
    """同步重建一次(兼容旧入口;生产事件路径请用去抖后的 _rebuild_worker)"""
    try:
        from paths import KNOWLEDGE_BASE_DIR

        try:
            from rag.rag_engine import get_rag_engine

            engine = get_rag_engine()
            if engine.is_enabled:
                n = engine.rebuild_index(str(KNOWLEDGE_BASE_DIR))
                logger.info("[RAG Subscriber] 索引已重建(单例): %d 个文档", n)
                return
        except Exception as e:
            logger.warning("[RAG Subscriber] 单例方式失败, 退化: %s", e)

        from main import get_agent

        agent = get_agent()
        if agent is not None and getattr(agent, "rag_engine", None) is not None:
            n = agent.rag_engine.rebuild_index(str(KNOWLEDGE_BASE_DIR))
            logger.info("[RAG Subscriber] 索引已重建(agent): %d 个文档", n)
            return
        logger.info(
            "[RAG Subscriber] 知识库更新事件: %d 个文件, agent 未就绪, 仅记录日志",
            count or 0,
        )
    except Exception as e:
        logger.exception("[RAG Subscriber] 处理失败: %s", e)
