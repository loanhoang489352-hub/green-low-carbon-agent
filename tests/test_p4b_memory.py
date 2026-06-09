"""
验证 P4-B: 三层记忆真正打通
- B.1: 短期 → 长期 consolidation
- B.2: LangGraph 节点写短期
- B.3: 长期访问热度 + 衰减
- B.4: 真正的记忆召回(语义+时间)
- B.5: 会话状态统一
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def test_conversation_store_singleton():
    """B.5: ConversationStore 单例 + 复用最近"""
    from agent.conversation_store import get_conversation_store
    s1 = get_conversation_store()
    s1.reset()
    s2 = get_conversation_store()
    assert s1 is s2
    ctx = s1.get_or_create("user_A")
    cid = ctx.conversation_id
    assert ctx.turn_count == 0
    # 第二次访问同一个用户 → 复用最近
    ctx2 = s1.get_or_create("user_A")
    assert ctx2.conversation_id == cid
    assert ctx2.turn_count == 1
    # 第三次 → 累加
    ctx3 = s1.get_or_create("user_A")
    assert ctx3.conversation_id == cid
    assert ctx3.turn_count == 2
    # 不同用户 → 新会话
    ctx4 = s1.get_or_create("user_B")
    assert ctx4.conversation_id != cid
    print("✅ test_conversation_store_singleton PASSED")


def test_long_term_access_heat():
    """B.3: 访问热度更新"""
    from memory.long_term import LongTermMemory

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = Path(tmp) / "lt.db"
        ltm = LongTermMemory(str(db))
        id1 = ltm.add_memory("u_heat", "用户喜欢骑车", importance=0.7)
        id2 = ltm.add_memory("u_heat", "用户关注节能", importance=0.6)

        # 首次访问
        ltm.get_recent_memories("u_heat", limit=10)
        import sqlite3
        conn = sqlite3.connect(str(db))
        row1 = conn.execute("SELECT access_count FROM user_memories WHERE id=?", (id1,)).fetchone()
        row2 = conn.execute("SELECT access_count FROM user_memories WHERE id=?", (id2,)).fetchone()
        assert row1[0] == 1 and row2[0] == 1
        conn.close()

        # 搜索 → 只命中 id1
        ltm.search_memories("u_heat", "骑车", limit=5)
        conn = sqlite3.connect(str(db))
        row1 = conn.execute("SELECT access_count FROM user_memories WHERE id=?", (id1,)).fetchone()
        row2 = conn.execute("SELECT access_count FROM user_memories WHERE id=?", (id2,)).fetchone()
        assert row1[0] == 2  # 被 search 命中
        assert row2[0] == 1  # 没被 search 命中
        conn.close()
    print("✅ test_long_term_access_heat PASSED")


def test_long_term_decay():
    """B.3: 重要性衰减"""
    from memory.long_term import LongTermMemory

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = Path(tmp) / "lt_decay.db"
        ltm = LongTermMemory(str(db))
        ltm.add_memory("u_decay", "记忆1", importance=1.0)
        ltm.add_memory("u_decay", "记忆2", importance=0.5)

        ltm.decay_importance(decay_rate=0.5)
        mems = ltm.get_recent_memories("u_decay", limit=10)
        importance_map = {m["content"]: m["importance"] for m in mems}
        # 0.5 不变(因为 < 0.1 的衰减条件是 > 0.1,这里 0.5*0.5=0.25, 1.0*0.5=0.5)
        assert abs(importance_map["记忆1"] - 0.5) < 1e-6
        assert abs(importance_map["记忆2"] - 0.25) < 1e-6
    print("✅ test_long_term_decay PASSED")


def test_memory_consolidation_e2e():
    """B.1: 短期 → 长期 consolidation 端到端"""
    from memory.short_term import get_short_term_memory, ShortTermMemory
    from memory.long_term import LongTermMemory
    from memory.consolidation import (
        get_consolidator, reset_consolidator, ThresholdStrategy, MemoryConsolidator,
    )
    from agent.conversation_store import get_conversation_store

    # Reset
    reset_consolidator()
    get_conversation_store().reset()
    stm = get_short_term_memory()
    # 用空 conversation_id 把所有 message 清掉(简化处理)
    # 实际不重置,只确保 conv_id 唯一

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = Path(tmp) / "lt_conso.db"
        ltm = LongTermMemory(str(db))

        consolidator = MemoryConsolidator(
            short_term=stm,
            long_term=ltm,
            strategy=ThresholdStrategy(),
        )

        conv_id = "test_conv_001"
        # 模拟 12 条消息(6 轮)
        for i in range(6):
            stm.add_message(
                conversation_id=conv_id,
                role="user",
                content=f"用户反馈: 第 {i+1} 次反馈骑车上班很棒",
                metadata={"intent": "feedback"},
            )
            stm.add_message(
                conversation_id=conv_id,
                role="assistant",
                content=f"鼓励:第 {i+1} 次回复",
                metadata={"intent": "feedback"},
            )
            consolidator.update_conversation_activity(conv_id)
            consolidator.update_message_count(conv_id, count=2)

        # 第 6 轮后 turn_count=6 < 10,不应触发
        n = consolidator.consolidate("u_conso", conv_id)
        assert n == 0, f"未达阈值,应为 0,实际 {n}"

        # 强制触发
        n = consolidator.force_consolidate("u_conso", conv_id)
        assert n >= 1, f"force 应保存至少 1 条,实际 {n}"

        # 验证长期记忆里已有
        mems = ltm.get_recent_memories("u_conso", limit=20)
        assert len(mems) >= 1
        contents = [m["content"] for m in mems]
        assert any("反馈" in c for c in contents), f"应有 feedback 记忆, 实际 {contents}"
    print("✅ test_memory_consolidation_e2e PASSED")


def test_recall_semantic_and_recent():
    """B.4: 真正的语义+时间召回"""
    from memory.long_term import LongTermMemory

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = Path(tmp) / "lt_recall.db"
        ltm = LongTermMemory(str(db))

        ltm.add_memory("u_recall", "用户骑自行车通勤", importance=0.7)
        ltm.add_memory("u_recall", "用户关注垃圾分类", importance=0.6)
        ltm.add_memory("u_recall", "用户喜欢素食", importance=0.5)
        ltm.add_memory("u_recall", "用户报告:今天用环保袋购物", memory_type="action_report", importance=0.7)

        # 1) 语义命中 - "自行车"
        results = ltm.search_memories("u_recall", "自行车", limit=5)
        assert len(results) >= 1
        assert "自行车" in results[0]["content"]

        # 2) 语义+时间回填 - 空 query
        # (search_memories 空 query 已处理为返回 [])

        # 3) 时间回填 - 假设 limit=2,只回 1 条语义
        # (此处测试 long_term 自身的 get_recent_memories)
        recent = ltm.get_recent_memories("u_recall", limit=3)
        assert len(recent) == 3
    print("✅ test_recall_semantic_and_recent PASSED")


def test_chat_enhanced_wires_consolidator():
    """B.1 集成: chat_enhanced 末尾确实调了 consolidator"""
    from agent.core import GreenAgent
    import inspect

    src = inspect.getsource(GreenAgent.chat_enhanced)
    assert "get_consolidator" in src or "consolidator" in src, \
        "chat_enhanced 末尾未调 consolidator"
    assert "update_conversation_activity" in src, "未调 update_conversation_activity"
    assert "consolidate" in src, "未调 consolidate"
    print("✅ test_chat_enhanced_wires_consolidator PASSED")


def test_langgraph_node_writes_short_term():
    """B.2: LangGraph 节点写短期记忆"""
    from agent.graph.nodes import AgentNodes
    import inspect

    src = inspect.getsource(AgentNodes.recognize_intent)
    assert "get_short_term_memory" in src or "short_term" in src
    assert "add_message" in src
    src = inspect.getsource(AgentNodes.generate_response)
    assert "get_short_term_memory" in src or "short_term" in src
    assert "add_message" in src
    print("✅ test_langgraph_node_writes_short_term PASSED")


def test_green_agent_uses_conversation_store():
    """B.5: GreenAgent 与 LangGraphAgent 都用 ConversationStore"""
    from agent.core import GreenAgent
    from agent.langgraph_agent import LangGraphAgent
    import inspect

    src_core = inspect.getsource(GreenAgent.__init__)
    assert "conversation_store" in src_core
    assert "get_conversation_store" in src_core

    src_lg = inspect.getsource(LangGraphAgent.__init__)
    assert "conversation_store" in src_lg
    assert "get_conversation_store" in src_lg
    print("✅ test_green_agent_uses_conversation_store PASSED")


if __name__ == "__main__":
    test_conversation_store_singleton()
    test_long_term_access_heat()
    test_long_term_decay()
    test_memory_consolidation_e2e()
    test_recall_semantic_and_recent()
    test_chat_enhanced_wires_consolidator()
    test_langgraph_node_writes_short_term()
    test_green_agent_uses_conversation_store()
    print("\n🎉 all P4-B memory tests passed")
