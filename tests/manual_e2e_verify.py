"""E2E 验证脚本:直接测试 agent 各层是否打通"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from main import get_agent
from memory.long_term import LongTermMemory
from memory.short_term import get_short_term_memory
from user_profile.profile_graph import UserProfileGraph


def main():
    agent = get_agent()
    print("=" * 60)
    print("E2E 验证: 绿色低碳智能体")
    print("=" * 60)

    # 1. 基础 chat
    print("\n[1] 基础 chat()")
    r1 = agent.chat("u_verify_1", "你好")
    print(f"    message len: {len(r1.message)}, intent={r1.intent}")
    assert r1.message and len(r1.message) > 0

    # 2. 知识查询(RAG)
    print("\n[2] chat_enhanced() 知识查询 (RAG)")
    r2 = agent.chat_enhanced("u_verify_2", "北京有哪些低碳生活政策?")
    print(f"    intent={r2.intent}")
    print(f"    knowledge_refs={len(r2.knowledge_refs)}: {r2.knowledge_refs[:3]}")
    print(f"    recommendations={len(r2.recommendations)}")
    rag_ctx = getattr(r2, "rag_context", "") or (r2.metadata.get("rag_context", "") if hasattr(r2, "metadata") else "")
    print(f"    rag_context={len(rag_ctx)} chars")
    assert r2.intent in ("knowledge_query", "advice_request")
    assert len(r2.knowledge_refs) >= 1
    assert len(r2.recommendations) >= 1
    assert len(rag_ctx) > 0

    # 3. 多轮 + 画像图谱
    print("\n[3] 多轮对话 + 画像图谱更新")
    uid = "u_verify_3"
    agent.chat_enhanced(uid, "我对绿色出行很感兴趣")
    agent.chat_enhanced(uid, "我今天骑自行车上班了, 大概3公里")
    agent.chat_enhanced(uid, "请给我一些建议")
    profile = agent.profile_manager.get_profile(uid)
    g_data = profile.get("graph", {})
    nodes = g_data.get("nodes", [])
    edges = g_data.get("edges", [])
    interests = [n["properties"].get("interest_id") for n in nodes if n["node_type"] == "interest"]
    actions = [n["properties"].get("action") for n in nodes if n["node_type"] == "action"]
    print(f"    graph: {len(nodes)} nodes, {len(edges)} edges")
    print(f"    interests: {interests}")
    print(f"    actions:   {actions}")
    assert "low_carbon_travel" in interests
    assert "骑自行车" in actions

    # 4. 图谱反序列化无丢失
    print("\n[4] 画像图谱 to_dict / from_dict 往返")
    g = UserProfileGraph.from_dict(g_data)
    print(f"    从 dict 恢复后: {len(g.nodes)} nodes, {len(g.edges)} edges")
    assert len(g.nodes) == len(nodes)
    assert len(g.edges) == len(edges)

    # 5. 三层记忆
    print("\n[5] 三层记忆")
    stm = get_short_term_memory()
    ctxs = agent.conversation_store.list_user_conversations(uid)
    short_count = 0
    for ctx in ctxs:
        hist = stm.get_conversation_history(ctx.conversation_id, limit=20)
        short_count += len(hist)
    print(f"    短期: {short_count} 条消息 across {len(ctxs)} 会话")
    lt = LongTermMemory()
    recents = lt.get_recent_memories(uid, limit=5)
    print(f"    长期: {len(recents)} 条记忆")
    print(f"    画像: {len(profile.get('eco_profile', {}).get('primary_interests', []))} 个兴趣")

    # 6. RAG 软过滤(北京政策)
    print("\n[6] RAG 个性化(北京政策软过滤)")
    r6 = agent.chat_enhanced("u_verify_6", "北京垃圾分类怎么做?")
    beijing_hits = [ref for ref in r6.knowledge_refs if "beijing" in ref.lower()]
    print(f"    refs: {r6.knowledge_refs}")
    print(f"    beijing 命中: {len(beijing_hits)}")

    print("\n" + "=" * 60)
    print("✅ 所有 E2E 验证通过")
    print("=" * 60)


if __name__ == "__main__":
    main()
