"""
知识库更新事件订阅者
收到 KNOWLEDGE_UPDATED 时重建 RAG 索引
"""
import logging

from events import EventType, get_event_bus

logger = logging.getLogger(__name__)


def _reload_rag(event_type, paths=None, count=None, **kwargs) -> None:
    """收到知识库更新事件,重建 RAG 索引"""
    try:
        from rag.rag_engine import RAGEngine
        # 在没有全局实例时,无法直接重载(需要 agent 单例)
        # 这里记录日志,实际重载由 agent 启动时通过订阅完成
        logger.info(
            "[RAG Subscriber] 知识库更新事件: %d 个文件, 等待 agent 重载",
            count or 0,
        )
    except Exception as e:
        logger.exception("[RAG Subscriber] 处理失败: %s", e)


def register_rag_subscribers() -> None:
    """注册 RAG 事件订阅者"""
    bus = get_event_bus()
    bus.subscribe(EventType.KNOWLEDGE_UPDATED, _reload_rag)
    logger.info("RAG 事件订阅者已注册")
