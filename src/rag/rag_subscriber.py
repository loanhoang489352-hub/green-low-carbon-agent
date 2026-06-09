"""
知识库更新事件订阅者
收到 KNOWLEDGE_UPDATED 时通知 RAG 重建索引

P4-A:订阅者真的尝试重建(委托给 main.get_agent() 的 rag_engine)
P4-E 计划:加 RAGEngine.get_instance() 单例,直接调 rebuild_index
"""
import logging
import threading

from events import EventType, get_event_bus

logger = logging.getLogger(__name__)

# 防止重建期间阻塞事件总线
_rebuild_lock = threading.Lock()


def _reload_rag(event_type, paths=None, count=None, **kwargs) -> None:
    """收到知识库更新事件,触发 RAG 重建"""
    if not _rebuild_lock.acquire(blocking=False):
        logger.warning("[RAG Subscriber] 上一次重建仍在进行,跳过本次事件")
        return
    try:
        _do_rebuild(paths, count)
    finally:
        _rebuild_lock.release()


def _do_rebuild(paths, count) -> None:
    """实际执行重建

    路径:
    1) 优先:调 main.get_agent().rag_engine.rebuild_index()(如果 agent 已初始化)
    2) 退化:仅记录日志(P4-E 引入 RAGEngine 单例后改为路径 1)
    """
    try:
        from main import get_agent
        agent = get_agent()
        if agent is not None and getattr(agent, "rag_engine", None) is not None:
            from paths import KNOWLEDGE_BASE_DIR
            n = agent.rag_engine.rebuild_index(str(KNOWLEDGE_BASE_DIR))
            logger.info("[RAG Subscriber] 索引已重建: %d 个文档, 共 %d 路径", n, count or 0)
            return
        logger.info(
            "[RAG Subscriber] 知识库更新事件: %d 个文件, agent 未就绪, 仅记录日志",
            count or 0,
        )
    except Exception as e:
        logger.exception("[RAG Subscriber] 处理失败: %s", e)


def register_rag_subscribers() -> None:
    """注册 RAG 事件订阅者"""
    bus = get_event_bus()
    bus.subscribe(EventType.KNOWLEDGE_UPDATED, _reload_rag)
    logger.info("RAG 事件订阅者已注册")
