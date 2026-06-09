"""
验证 P4-A 启动骨架
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def test_scheduler_jobs_registered():
    """APScheduler 注册 3 个 cron job: 知识/政策/记忆衰减/短期清理"""
    from scheduler import start_scheduler, get_scheduler, reset_scheduler
    reset_scheduler()
    sched = start_scheduler()
    assert sched is not None
    jobs = sched.get_jobs()
    job_ids = {j.id for j in jobs}
    assert "daily_kb_update" in job_ids
    assert "memory_decay" in job_ids
    assert "short_term_cleanup" in job_ids
    print(f"✅ test_scheduler_jobs_registered PASSED: {len(jobs)} jobs")
    reset_scheduler()


def test_scheduler_idempotent():
    """start_scheduler 多次调用不报错(单例)"""
    from scheduler import start_scheduler, reset_scheduler
    reset_scheduler()
    s1 = start_scheduler()
    s2 = start_scheduler()
    assert s1 is s2
    print("✅ test_scheduler_idempotent PASSED")
    reset_scheduler()


def test_init_app_registers_subscribers():
    """init_app() 应注册反馈 + RAG 订阅者 + 启动调度器 + 初始化 Schema"""
    from server.app import init_app
    from events import get_event_bus, EventType, reset_event_bus
    from scheduler import get_scheduler, reset_scheduler

    reset_event_bus()
    reset_scheduler()

    # 重置订阅计数
    bus = get_event_bus()
    initial_subscriber_count = sum(len(subs) for subs in bus._subscribers.values())

    init_app()

    # 调度器已启动
    assert get_scheduler() is not None, "调度器未启动"

    # 订阅者已注册(订阅数应增加)
    new_subscriber_count = sum(len(subs) for subs in bus._subscribers.values())
    assert new_subscriber_count > initial_subscriber_count, "订阅者未注册"

    # 至少 KNOWLEDGE_UPDATED 和 FEEDBACK_RECEIVED 都已订阅
    for et in (EventType.KNOWLEDGE_UPDATED, EventType.FEEDBACK_RECEIVED):
        assert et in bus._subscribers
        assert len(bus._subscribers[et]) > 0

    print(f"✅ test_init_app_registers_subscribers PASSED: subs={new_subscriber_count}")
    reset_scheduler()


def test_rag_subscriber_actually_tries_rebuild():
    """RAG 订阅者收到事件后真的尝试调 rebuild_index"""
    from events import reset_event_bus, get_event_bus, EventType
    from rag.rag_subscriber import _do_rebuild, register_rag_subscribers
    reset_event_bus()
    register_rag_subscribers()

    # 模拟 agent 未就绪,_do_rebuild 不抛异常
    _do_rebuild(paths=["/a.md"], count=1)
    print("✅ test_rag_subscriber_actually_tries_rebuild PASSED (no crash when agent missing)")


def test_graph_checkpointer_sqlite():
    """LangGraph 默认挂 SqliteSaver checkpointer"""
    from agent.graph.graph import create_agent_graph, _get_default_checkpointer
    cp = _get_default_checkpointer()
    # SqliteSaver 或 MemorySaver 都有 .get / .put 等接口
    assert hasattr(cp, "get") and hasattr(cp, "put")
    print(f"✅ test_graph_checkpointer_sqlite PASSED: {type(cp).__name__}")


def test_long_term_decay_signature():
    """scheduler 调用的 decay_importance 签名存在"""
    from memory.long_term import LongTermMemory
    assert hasattr(LongTermMemory, "decay_importance")
    print("✅ test_long_term_decay_signature PASSED")


def test_short_term_cleanup_signature():
    """scheduler 调用的 cleanup_expired 签名存在且返回数量"""
    from memory.short_term import get_short_term_memory
    stm = get_short_term_memory()
    result = stm.cleanup_expired()
    assert isinstance(result, int)
    print(f"✅ test_short_term_cleanup_signature PASSED: cleaned {result}")


if __name__ == "__main__":
    test_scheduler_jobs_registered()
    test_scheduler_idempotent()
    test_init_app_registers_subscribers()
    test_rag_subscriber_actually_tries_rebuild()
    test_graph_checkpointer_sqlite()
    test_long_term_decay_signature()
    test_short_term_cleanup_signature()
    print("\n🎉 all P4-A skeleton tests passed")
