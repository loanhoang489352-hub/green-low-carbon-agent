"""
P4-G: 端到端集成测试
验证 agent 端到端工作:RAG + 3-tier memory + 画像图谱 + 推荐
"""
import sys
import os
import tempfile
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def test_agent_startup_smoke():
    """G.0: agent 启动 + 基础 API 不抛异常"""
    import main
    agent = main.get_agent()
    assert agent is not None
    assert hasattr(agent, "chat")
    assert hasattr(agent, "chat_enhanced")
    print("✅ test_agent_startup_smoke PASSED")


def test_chat_basic_returns_response():
    """G.1: 基础 chat 返回字符串响应"""
    import main
    agent = main.get_agent()
    result = agent.chat("u_e2e_g1", "你好")
    # result 可能是 dataclass 或 dict
    if hasattr(result, "message"):
        msg = result.message
    elif isinstance(result, dict):
        msg = result.get("message", "")
    else:
        msg = str(result)
    assert isinstance(msg, str)
    assert len(msg) > 0
    print(f"   message len: {len(msg)}")
    print("✅ test_chat_basic_returns_response PASSED")


def test_chat_enhanced_knowledge_query():
    """G.2: 知识查询走 RAG,返回 knowledge_refs + recommendations"""
    import main
    agent = main.get_agent()
    result = agent.chat_enhanced("u_e2e_g2", "北京有哪些低碳生活政策?")
    if hasattr(result, "knowledge_refs"):
        refs = result.knowledge_refs
        recs = result.recommendations
        intent = result.intent
    else:
        refs = result.get("knowledge_refs", [])
        recs = result.get("recommendations", [])
        intent = result.get("intent", "")
    assert intent in ("knowledge_query", "advice_request")
    assert len(refs) >= 1, f"期望至少 1 个知识引用, 实际 {len(refs)}"
    assert len(recs) >= 1, f"期望至少 1 个推荐, 实际 {len(recs)}"
    print(f"   refs: {len(refs)}, recs: {len(recs)}")
    print("✅ test_chat_enhanced_knowledge_query PASSED")


def test_chat_enhanced_advice_request():
    """G.3: advice_request 也走 RAG 路径"""
    import main
    agent = main.get_agent()
    result = agent.chat_enhanced("u_e2e_g3", "我应该怎么减少碳排放?")
    if hasattr(result, "recommendations"):
        recs = result.recommendations
    else:
        recs = result.get("recommendations", [])
    assert len(recs) >= 1
    print(f"   recs: {len(recs)}")
    print("✅ test_chat_enhanced_advice_request PASSED")


def test_chat_enhanced_greeting():
    """G.4: greeting 也有推荐(基于画像)"""
    import main
    agent = main.get_agent()
    result = agent.chat_enhanced("u_e2e_g4", "你好")
    if hasattr(result, "recommendations"):
        recs = result.recommendations
    else:
        recs = result.get("recommendations", [])
    assert len(recs) >= 1, f"greeting 期望至少 1 个推荐, 实际 {len(recs)}"
    print(f"   greeting recs: {len(recs)}")
    print("✅ test_chat_enhanced_greeting PASSED")


def test_multi_turn_profile_update():
    """G.5: 多轮对话后,画像图谱被正确更新"""
    import main
    agent = main.get_agent()
    uid = "u_e2e_g5"
    # 第 1 轮:表达兴趣
    r1 = agent.chat_enhanced(uid, "我对垃圾分类和绿色出行很感兴趣")
    # 第 2 轮:报告行为
    r2 = agent.chat_enhanced(uid, "我今天骑自行车上班了, 大概3公里")
    # 验证画像图谱
    profile = agent.profile_manager.get_profile(uid)
    assert "graph" in profile
    from user_profile.profile_graph import UserProfileGraph
    g = UserProfileGraph.from_dict(profile["graph"])
    interests = [i[0] for i in g.get_interests()]
    actions = g.get_actions()
    # 至少 low_carbon_travel 应在兴趣中,骑自行车应在行为中
    assert "low_carbon_travel" in interests, f"应含 low_carbon_travel, 实际 {interests}"
    assert "骑自行车" in actions, f"应含骑自行车, 实际 {actions}"
    print(f"   interests: {interests}, actions: {actions}")
    print("✅ test_multi_turn_profile_update PASSED")


def test_multi_turn_recommendations_evolve():
    """G.6: 多轮后,推荐随画像变化"""
    import main
    agent = main.get_agent()
    # 已有 low_carbon_travel 兴趣的用户
    uid = "u_e2e_g6"
    agent.chat_enhanced(uid, "我对绿色出行很感兴趣")
    r = agent.chat_enhanced(uid, "请给我一些建议")
    recs = r.recommendations if hasattr(r, "recommendations") else r.get("recommendations", [])
    # 至少应有 1 个推荐
    assert len(recs) >= 1
    print(f"   recs: {len(recs)}")
    print("✅ test_multi_turn_recommendations_evolve PASSED")


def test_rag_retrieval_includes_beijing_policy():
    """G.7: 知识库检索应能命中北京地区政策"""
    from agent.graph.nodes import get_nodes
    nodes = get_nodes()
    nodes.initialize()
    results = nodes._rag_engine.retrieve(
        "北京有哪些低碳生活政策?", top_k=5,
    )
    assert len(results) >= 1
    sources = [r.metadata.get("source", "") for r in results]
    # 至少 1 个应是北京相关
    has_beijing = any("beijing" in s.lower() for s in sources)
    assert has_beijing, f"应至少含 beijing 源, 实际 {sources}"
    print(f"   sources: {sources}")
    print("✅ test_rag_retrieval_includes_beijing_policy PASSED")


def test_short_term_memory_writes():
    """G.8: 短期记忆:对话后短期记忆有消息"""
    from memory.short_term import get_short_term_memory
    stm = get_short_term_memory()
    conv_id = "conv_e2e_g8"
    stm.add_message(conv_id, "user", "测试消息1", metadata={})
    stm.add_message(conv_id, "assistant", "回复1", metadata={})
    history = stm.get_conversation_history(conv_id)
    assert len(history) >= 2
    print(f"   history len: {len(history)}")
    print("✅ test_short_term_memory_writes PASSED")


def test_no_runtime_errors_during_e2e():
    """G.9: 完整 e2e 流程无 RuntimeError"""
    import main
    agent = main.get_agent()
    uid = "u_e2e_g9"
    # 模拟一个真实用户的 3 轮对话
    msgs = [
        "你好, 我想了解环保",
        "我经常骑自行车上班",
        "推荐一些节能的家电",
    ]
    for m in msgs:
        try:
            r = agent.chat_enhanced(uid, m)
            assert r is not None
        except RuntimeError as e:
            raise AssertionError(f"RuntimeError on msg '{m}': {e}")
    print("✅ test_no_runtime_errors_during_e2e PASSED")


if __name__ == "__main__":
    test_agent_startup_smoke()
    test_chat_basic_returns_response()
    test_chat_enhanced_knowledge_query()
    test_chat_enhanced_advice_request()
    test_chat_enhanced_greeting()
    test_multi_turn_profile_update()
    test_multi_turn_recommendations_evolve()
    test_rag_retrieval_includes_beijing_policy()
    test_short_term_memory_writes()
    test_no_runtime_errors_during_e2e()
    print("\n🎉 all P4-G E2E tests passed")
