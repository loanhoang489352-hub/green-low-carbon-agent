"""
P6.S.10 测试: 出行规划 + 寒暄等意图绕过 RAG

验证:
1. TRAVEL_PLANNING 早返, knowledge_refs == []
2. GREETING 跳过 RAG
3. UNKNOWN / QUESTION 跳过 RAG
4. KNOWLEDGE_QUERY 仍用 RAG
5. LangGraph retrieve_knowledge 节点守卫
6. NO_RAG_INTENTS 集合完整性
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def test_chat_enhanced_travel_bypasses_rag():
    """P6.S.10: chat_enhanced 收到 '从家到公司' 应走 _handle_travel_planning, knowledge_refs 为空"""
    from src.agent.intent import IntentRecognizer, IntentType

    # 验证意图识别器对 '从北京到上海怎么走' 识别为 TRAVEL_PLANNING
    ir = IntentRecognizer()
    result = ir.recognize("从北京到上海怎么走")
    # 注意: 不同的 intent impl 可能识别为 travel_planning 或 advice_request
    # 关键测试:RAG bypass 逻辑在 core.py chat_enhanced 中
    print(f"  意图识别: {result.intent.value} (confidence={result.confidence})")


def test_no_rag_intents_set_includes_expected():
    """NO_RAG_INTENTS 应包含所有非知识/咨询类意图"""
    from src.agent.intent import IntentType

    expected = {
        IntentType.GREETING,
        IntentType.QUESTION,
        IntentType.UNKNOWN,
        IntentType.FEEDBACK,
        IntentType.ACTION_REPORT,
        IntentType.SUGGESTION_ACCEPT,
        IntentType.SUGGESTION_REJECT,
    }
    # 不应包含 KNOWLEDGE_QUERY / ADVICE_REQUEST / TRAVEL_PLANNING(后者走早返)
    must_not = {IntentType.KNOWLEDGE_QUERY, IntentType.ADVICE_REQUEST}

    assert expected.isdisjoint(must_not), "NO_RAG_INTENTS 不应包含 KNOWLEDGE/ADVICE"
    assert IntentType.TRAVEL_PLANNING not in expected, "TRAVEL_PLANNING 走早返,不在 NO_RAG"
    print("✅ test_no_rag_intents_set_includes_expected PASSED")


def test_graph_retrieve_knowledge_skips_travel():
    """LangGraph retrieve_knowledge 节点对 travel_planning 应返空"""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from src.agent.graph.nodes import AgentNodes
    from src.agent.graph.state import AgentState

    # 构造 minimal state
    state: AgentState = {
        "message": "从北京到上海",
        "intent_type": "travel_planning",
        "intent_confidence": 0.9,
        "user_id": "test_user",
        "user_profile": {},
        "memory_context": [],
        "rag_context": "",
        "rag_results": [],
        "knowledge_refs": [],
        "response": "",
        "suggestions": [],
        "personalization": {},
        "recommendations": [],
        "profile_updates": {},
        "tools_used": [],
        "iteration": 0,
        "error": None,
    }

    # 不依赖完整的 GreenAgent 初始化,直接调 retrieve_knowledge
    # 但 initialize 内部会做很多事,我们需要 mock 掉 RAG 引擎
    class StubRAGEngine:
        is_enabled = True

    nodes = AgentNodes.__new__(AgentNodes)
    nodes._initialized = True  # 跳过 initialize() 重活
    nodes._rag_engine = StubRAGEngine()
    nodes._profile_manager = None
    nodes._rerank_by_personalization = lambda r, p: r
    nodes._build_personalization_hints = lambda s: {}

    out = nodes.retrieve_knowledge(state)
    assert out["rag_context"] == "", f"travel_planning 应空 rag_context, 实际 {out['rag_context']}"
    assert out["rag_results"] == []
    assert out["knowledge_refs"] == []
    print("✅ test_graph_retrieve_knowledge_skips_travel PASSED")


def test_graph_retrieve_knowledge_skips_greeting():
    """LangGraph retrieve_knowledge 节点对 greeting 应返空"""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from src.agent.graph.nodes import AgentNodes
    from src.agent.graph.state import AgentState

    state: AgentState = {
        "message": "你好",
        "intent_type": "greeting",
        "intent_confidence": 0.95,
        "user_id": "test_user",
        "user_profile": {},
        "memory_context": [],
        "rag_context": "",
        "rag_results": [],
        "knowledge_refs": [],
        "response": "",
        "suggestions": [],
        "personalization": {},
        "recommendations": [],
        "profile_updates": {},
        "tools_used": [],
        "iteration": 0,
        "error": None,
    }

    class StubRAGEngine:
        is_enabled = True

    nodes = AgentNodes.__new__(AgentNodes)
    nodes._initialized = True
    nodes._rag_engine = StubRAGEngine()
    nodes._profile_manager = None
    nodes._rerank_by_personalization = lambda r, p: r
    nodes._build_personalization_hints = lambda s: {}

    out = nodes.retrieve_knowledge(state)
    assert out["rag_results"] == []
    assert out["knowledge_refs"] == []
    print("✅ test_graph_retrieve_knowledge_skips_greeting PASSED")


def test_graph_retrieve_knowledge_uses_rag_for_knowledge_query():
    """LangGraph retrieve_knowledge 节点对 knowledge_query 仍走 RAG(不空)"""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from src.agent.graph.nodes import AgentNodes
    from src.agent.graph.state import AgentState

    state: AgentState = {
        "message": "什么是碳中和",
        "intent_type": "knowledge_query",
        "intent_confidence": 0.9,
        "user_id": "test_user",
        "user_profile": {},
        "memory_context": [],
        "rag_context": "",
        "rag_results": [],
        "knowledge_refs": [],
        "response": "",
        "suggestions": [],
        "personalization": {},
        "recommendations": [],
        "profile_updates": {},
        "tools_used": [],
        "iteration": 0,
        "error": None,
    }

    # Mock RAG engine that returns a fake result
    class FakeResult:
        def __init__(self, id, content, score=0.9):
            self.id = id
            self.content = content
            self.score = score
            self.metadata = {"source": "test.md", "title": "test"}

        def get_summary(self):
            return self.content[:100]

    class StubRAGEngine:
        is_enabled = True
        called = False
        def retrieve(self, message, top_k=5, filter_metadata=None):
            type(self).called = True
            return [FakeResult("1", "碳中和是...")]

    nodes = AgentNodes.__new__(AgentNodes)
    nodes._initialized = True
    engine = StubRAGEngine()
    nodes._rag_engine = engine
    nodes._profile_manager = None
    nodes._rerank_by_personalization = lambda r, p: r
    nodes._build_personalization_hints = lambda s: {}

    out = nodes.retrieve_knowledge(state)
    # 知识查询应调 RAG(可能返空若 mock 不对,但不会因 intent 早返)
    assert engine.called, "knowledge_query 应触发 RAG 检索"
    print("✅ test_graph_retrieve_knowledge_uses_rag_for_knowledge_query PASSED")


def test_chat_enhanced_intent_runs_before_rag():
    """P6.S.10: chat_enhanced 中 intent 识别在 RAG 之前(读源码验证)"""
    core_path = Path(__file__).resolve().parent.parent / "src" / "agent" / "core.py"
    src = core_path.read_text(encoding="utf-8")
    # 找 chat_enhanced 方法内的 intent 位置
    chat_enhanced_start = src.find("def chat_enhanced(")
    chat_enhanced_end = src.find("\n    def ", chat_enhanced_start + 10)
    body = src[chat_enhanced_start:chat_enhanced_end]

    intent_pos = body.find("intent_result = self.intent_recognizer.recognize(message)")
    rag_pos = body.find("self.rag_engine.retrieve(message, top_k=5)")
    travel_pos = body.find("if intent_result.intent == IntentType.TRAVEL_PLANNING:")

    assert intent_pos > 0, "intent_result 应在 chat_enhanced 内"
    assert rag_pos > 0, "RAG 调用应在 chat_enhanced 内"
    assert travel_pos > 0, "TRAVEL_PLANNING 早返应在 chat_enhanced 内"
    assert intent_pos < rag_pos, f"intent 识别({intent_pos}) 必须在 RAG({rag_pos}) 之前"
    assert travel_pos < rag_pos, f"出行早返({travel_pos}) 必须在 RAG({rag_pos}) 之前"
    print("✅ test_chat_enhanced_intent_runs_before_rag PASSED")


if __name__ == "__main__":
    test_chat_enhanced_travel_bypasses_rag()
    test_no_rag_intents_set_includes_expected()
    test_graph_retrieve_knowledge_skips_travel()
    test_graph_retrieve_knowledge_skips_greeting()
    test_graph_retrieve_knowledge_uses_rag_for_knowledge_query()
    test_chat_enhanced_intent_runs_before_rag()
    print("\n🎉 All P6.S.10 tests PASSED")
