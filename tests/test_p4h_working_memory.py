"""
P4-H: 三层记忆(短+工作+长)与级联召回测试
覆盖:
- WorkingMemory 单例 + 命名空间读写
- 同名 key 覆盖检测(防任务污染)
- end_task 清空(防任务污染)
- 跨会话持久(JSON 快照)
- 容量 LRU 淘汰
- should_recall 信号词判断
- cascaded_recall 三层级联
- LLM prompt 注入(snapshot_for_prompt)
- promotion(高 importance key 晋升 LTM)
- 调度器注册 working_memory_heartbeat
"""
import sys
import os
import json
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def _uid(prefix: str = "u") -> str:
    import uuid
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def test_working_memory_singleton():
    """H.0: WorkingMemory 是单例(双检锁)"""
    from memory.working import get_working_memory, reset_working_memory
    reset_working_memory()
    w1 = get_working_memory()
    w2 = get_working_memory()
    assert w1 is w2
    print("✅ test_working_memory_singleton PASSED")


def test_workspace_basic_set_get():
    """H.1: workspace 基础读写"""
    from memory.working import get_working_memory
    wm = get_working_memory()
    uid = _uid()
    try:
        wm.set(uid, "current_focus", "绿色出行", agent_name="nlu", importance=0.8)
        wm.set(uid, "active_goal", {"title": "本周减塑", "progress": 0.3}, agent_name="planner", importance=0.9)
        assert wm.get(uid, "current_focus") == "绿色出行"
        assert wm.get(uid, "active_goal")["title"] == "本周减塑"
        assert "current_focus" in wm.keys(uid)
        assert "active_goal" in wm.keys(uid)
        print(f"   keys: {wm.keys(uid)}")
    finally:
        wm.clear_user(uid)
    print("✅ test_workspace_basic_set_get PASSED")


def test_overwrite_detection():
    """H.2: 同名 key 覆盖产生警告(防任务污染)"""
    from memory.working import get_working_memory
    wm = get_working_memory()
    uid = _uid()
    try:
        wm.set(uid, "current_focus", "绿色出行", agent_name="nlu", importance=0.8)
        # 第二次写同一 key,应触发覆盖
        wm.set(uid, "current_focus", "垃圾分类", agent_name="rag", importance=0.6)
        # 最新值应是 "垃圾分类"
        assert wm.get(uid, "current_focus") == "垃圾分类"
        # access_count 应 > 0(读取过)
        snap = wm.snapshot(uid)
        entry = snap["scope"]["current_focus"]
        assert entry["access_count"] >= 1
        assert entry["agent"] == "rag"
        print(f"   overwritten to: 垃圾分类 by agent=rag")
    finally:
        wm.clear_user(uid)
    print("✅ test_overwrite_detection PASSED")


def test_end_task_clears_scope():
    """H.3: end_task 默认清空 scope(防任务污染)"""
    from memory.working import get_working_memory
    wm = get_working_memory()
    uid = _uid()
    try:
        wm.start_task(uid, "task_1")
        wm.set(uid, "k1", "v1", agent_name="a")
        wm.set(uid, "k2", "v2", agent_name="a")
        assert len(wm.keys(uid)) == 2
        wm.end_task(uid, clear=True)
        assert len(wm.keys(uid)) == 0
        print("   after end_task: scope cleared")
    finally:
        wm.clear_user(uid)
    print("✅ test_end_task_clears_scope PASSED")


def test_end_task_keep_scope():
    """H.3.1: end_task(clear=False) 保留 scope(用于跨任务共享)"""
    from memory.working import get_working_memory
    wm = get_working_memory()
    uid = _uid()
    try:
        wm.set(uid, "shared_state", "v1", importance=0.9)
        wm.start_task(uid, "task_a")
        wm.end_task(uid, clear=False)
        assert wm.get(uid, "shared_state") == "v1"
        print("   end_task(clear=False) preserved shared state")
    finally:
        wm.clear_user(uid)
    print("✅ test_end_task_keep_scope PASSED")


def test_cross_session_persistence():
    """H.4: 跨会话持久(JSON 快照)"""
    from memory.working import get_working_memory, reset_working_memory
    uid = _uid()
    # 第一个会话
    wm1 = get_working_memory()
    wm1.set(uid, "long_term_focus", "环保", agent_name="agent_a", importance=0.9)
    wm1.end_task(uid, clear=False)  # 保留,触发快照
    # 模拟重启:重置单例
    reset_working_memory()
    # 第二个会话
    wm2 = get_working_memory()
    v = wm2.get(uid, "long_term_focus")
    assert v == "环保", f"快照应恢复,实际 {v!r}"
    print(f"   snapshot restored: {v}")
    wm2.clear_user(uid)
    print("✅ test_cross_session_persistence PASSED")


def test_lru_eviction():
    """H.5: 超过 WORKSPACE_MAX_KEYS 触发 LRU 淘汰"""
    from memory.working import get_working_memory, WORKSPACE_MAX_KEYS
    wm = get_working_memory()
    uid = _uid()
    try:
        # 灌入 WORKSPACE_MAX_KEYS + 5 个 key
        n = WORKSPACE_MAX_KEYS + 5
        for i in range(n):
            wm.set(uid, f"k_{i:03d}", f"v_{i}", importance=0.5)
        # 应被淘汰到 <= WORKSPACE_MAX_KEYS
        size = len(wm.keys(uid))
        assert size <= WORKSPACE_MAX_KEYS, f"应 <= {WORKSPACE_MAX_KEYS}, 实际 {size}"
        print(f"   {n} keys -> evicted to {size}")
    finally:
        wm.clear_user(uid)
    print("✅ test_lru_eviction PASSED")


def test_should_recall_signals():
    """H.6: should_recall 信号词判断"""
    from memory.working import should_recall
    # 明确信号:应返回 True
    assert should_recall("上次那个 RAG 方案怎么样了?")
    assert should_recall("之前我们讨论过北京垃圾分类")
    assert should_recall("继续聊聊昨天的话题")
    assert should_recall("还记得我提到的减塑目标吗?")
    # 隐式信号:应返回 True
    assert should_recall("那个方法, 换成 B 方案试试")
    assert should_recall("第二个, 我想要更激进的")
    # 无信号:应返回 False
    assert not should_recall("你好")
    assert not should_recall("今天天气怎么样")
    assert not should_recall("碳足迹怎么计算")
    print("   信号词判断正确")
    print("✅ test_should_recall_signals PASSED")


def test_snapshot_for_prompt():
    """H.7: snapshot_for_prompt 生成 LLM 友好的 prompt 片段"""
    from memory.working import get_working_memory
    wm = get_working_memory()
    uid = _uid()
    try:
        wm.set(uid, "current_focus", "环保出行", agent_name="nlu", importance=0.9)
        wm.set(uid, "active_goal", {"title": "减塑", "progress": 0.3}, agent_name="planner", importance=0.8)
        text = wm.snapshot_for_prompt(uid)
        assert "[工作记忆]" in text
        assert "current_focus" in text
        assert "环保出行" in text
        assert "active_goal" in text
        assert "nlu" in text
        assert "planner" in text
        assert "重要性" in text
        print(f"   prompt fragment:\n{text}")
    finally:
        wm.clear_user(uid)
    print("✅ test_snapshot_for_prompt PASSED")


def test_cascaded_recall_short_only():
    """H.8: 不需要 recall 时,仅返回短期(零成本)"""
    from memory.memory_agent import cascaded_recall
    r = cascaded_recall(
        user_id=_uid(),
        query="今天天气怎么样",  # 无信号
        conversation_id="conv_test_1",
    )
    assert r["should_recall"] is False
    # 短期可能为空(没 add),但不应触发长期
    assert r["long_term"] == []
    print(f"   should_recall=False, 长期未触发")
    print("✅ test_cascaded_recall_short_only PASSED")


def test_cascaded_recall_full_chain():
    """H.9: 有信号时,触发三级级联"""
    from memory.memory_agent import cascaded_recall
    from memory.working import get_working_memory
    wm = get_working_memory()
    uid = _uid()
    try:
        wm.set(uid, "current_focus", "减塑目标", agent_name="planner", importance=0.9)
        r = cascaded_recall(
            user_id=uid,
            query="上次说的减塑怎么样了?",  # 明确信号
            conversation_id="conv_test_2",
        )
        assert r["should_recall"] is True
        # 工作记忆应有 current_focus
        working_keys = [it["key"] for it in r["working"]]
        assert "current_focus" in working_keys
        # 合并 prompt 应包含工作记忆
        assert "[工作记忆" in r["merged_for_prompt"]
        print(f"   cascaded prompt:\n{r['merged_for_prompt']}")
    finally:
        wm.clear_user(uid)
    print("✅ test_cascaded_recall_full_chain PASSED")


def test_promote_working_to_long_term():
    """H.10: 高 importance key 晋升到长期记忆"""
    from memory.working import get_working_memory
    from memory.memory_agent import promote_working_to_long_term
    from memory.long_term import LongTermMemory
    wm = get_working_memory()
    lt = LongTermMemory()
    uid = _uid("u_promote")
    try:
        wm.set(uid, "important_fact", "用户住在北京", importance=0.9)
        wm.set(uid, "trivial", "临时草稿", importance=0.3)
        promoted = promote_working_to_long_term(uid, "important_fact", importance_threshold=0.7)
        assert promoted is True
        not_promoted = promote_working_to_long_term(uid, "trivial", importance_threshold=0.7)
        assert not_promoted is False
        # 长期应能搜到
        mems = lt.search_memories(uid, "北京", limit=3)
        found = any("北京" in str(m.get("content", "")) for m in mems)
        assert found, f"长期记忆应含 '北京', 实际 {mems}"
        print(f"   promoted, long-term found 北京: {found}")
    finally:
        wm.clear_user(uid)
    print("✅ test_promote_working_to_long_term PASSED")


def test_scheduler_registers_heartbeat():
    """H.11: APScheduler 注册 working_memory_heartbeat"""
    from scheduler import start_scheduler, get_scheduler
    sched = start_scheduler()
    job_ids = [j.id for j in sched.get_jobs()]
    assert "working_memory_heartbeat" in job_ids
    assert "memory_decay" in job_ids
    assert "short_term_cleanup" in job_ids
    print(f"   jobs: {job_ids}")
    print("✅ test_scheduler_registers_heartbeat PASSED")


def test_three_layers_in_memory_init():
    """H.12: memory.__init__ 导出三层 + 级联"""
    import memory
    # 短期
    assert hasattr(memory, "ShortTermMemory")
    assert hasattr(memory, "get_short_term_memory")
    # 工作
    assert hasattr(memory, "WorkingMemory")
    assert hasattr(memory, "get_working_memory")
    assert hasattr(memory, "should_recall")
    # 长期
    assert hasattr(memory, "LongTermMemory")
    # 整合
    assert hasattr(memory, "MemoryConsolidator")
    # 级联
    assert hasattr(memory, "cascaded_recall")
    assert hasattr(memory, "promote_working_to_long_term")
    print("✅ test_three_layers_in_memory_init PASSED")


def test_e2e_short_working_long_integration():
    """H.13: 端到端 - 短期→工作晋升→长期兜底"""
    from memory.short_term import get_short_term_memory
    from memory.working import get_working_memory, reset_working_memory
    from memory.consolidation import get_consolidator
    from memory.memory_agent import cascaded_recall
    import uuid
    reset_working_memory()
    uid = f"u_e2e_{uuid.uuid4().hex[:8]}"
    conv_id = f"conv_e2e_{uuid.uuid4().hex[:8]}"
    wm = get_working_memory()
    try:
        # 1) 短期:多轮对话
        stm = get_short_term_memory()
        stm.add_message(conv_id, "user", "我想开始减塑", metadata={"intent": "interest"})
        stm.add_message(conv_id, "assistant", "好的,推荐自带环保袋", metadata={})
        stm.add_message(conv_id, "user", "我打算这周都自己带饭盒", metadata={"intent": "action_report"})
        stm.add_message(conv_id, "assistant", "很好,这是积极的减塑行动", metadata={})
        # 2) 强制触发 consolidation(绕过 turn 阈值,直接调 _promote_to_working)
        consolidator = get_consolidator()
        consolidator._promote_to_working(uid, conv_id, stm.get_conversation_history(conv_id, limit=10))
        # 3) 工作记忆应有 current_focus
        focus = wm.get(uid, "current_focus")
        assert focus is not None, "工作记忆应写入 current_focus"
        print(f"   working.current_focus: {focus[:80]}")
        # 4) 级联召回
        r = cascaded_recall(uid, "上次那个减塑计划怎么样了?", conv_id)
        assert r["should_recall"] is True
        assert len(r["working"]) >= 1
        merged = r["merged_for_prompt"]
        assert "工作记忆" in merged
        print(f"   merged prompt len: {len(merged)} chars")
    finally:
        wm.clear_user(uid)
    print("✅ test_e2e_short_working_long_integration PASSED")


if __name__ == "__main__":
    test_working_memory_singleton()
    test_workspace_basic_set_get()
    test_overwrite_detection()
    test_end_task_clears_scope()
    test_end_task_keep_scope()
    test_cross_session_persistence()
    test_lru_eviction()
    test_should_recall_signals()
    test_snapshot_for_prompt()
    test_cascaded_recall_short_only()
    test_cascaded_recall_full_chain()
    test_promote_working_to_long_term()
    test_scheduler_registers_heartbeat()
    test_three_layers_in_memory_init()
    test_e2e_short_working_long_integration()
    print("\n🎉 all P4-H working memory tests passed")
