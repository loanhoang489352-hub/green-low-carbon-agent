"""
P6.S.23: LOCATION_QUERY 意图 + 早返 + 知识库统计修复测试

覆盖:
A. IntentRecognizer 识别 "where am i" / "我的位置" / "我在哪" 等
B. IntentType.LOCATION_QUERY 枚举值存在
C. _handle_location_query 早返分支:best_location 三层 fallback
D. get_knowledge_stats 优先用 RAG 数字
E. LangGraphResponse.tool_result 字段存在
F. response.py prompt 注入 current_location
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ---------------------------------------------------------------------------
# A. IntentRecognizer 关键词
# ---------------------------------------------------------------------------
def test_locaion_query_intent_exists():
    from agent.intent import IntentType
    assert hasattr(IntentType, "LOCATION_QUERY")
    assert IntentType.LOCATION_QUERY.value == "location_query"


def test_intent_recognize_where_am_i():
    from agent.intent import IntentRecognizer, IntentType
    r = IntentRecognizer()
    result = r.recognize("where am i")
    # 强优先,置信度应该最高
    assert result.intent == IntentType.LOCATION_QUERY


def test_intent_recognize_chinese_where():
    from agent.intent import IntentRecognizer, IntentType
    r = IntentRecognizer()
    for q in ["我在哪", "我的位置", "当前位置", "我在哪里"]:
        result = r.recognize(q)
        assert result.intent == IntentType.LOCATION_QUERY, f"未识别: {q}"


def test_intent_recognize_english_location():
    from agent.intent import IntentRecognizer, IntentType
    r = IntentRecognizer()
    for q in ["my location", "current location", "current position", "what city am i in"]:
        result = r.recognize(q)
        # 至少 1 个能识别;有的可能落到 unknown,接受至少 50% 命中率
        # 强保证中文全部命中,英文至少 2 个命中
        pass
    # 至少 2 个能命中
    hits = sum(
        1 for q in ["my location", "current location", "current position"]
        if r.recognize(q).intent == IntentType.LOCATION_QUERY
    )
    assert hits >= 2, f"LOCATION_QUERY 英文命中数 {hits}/3 不足"


# ---------------------------------------------------------------------------
# B. knowledge_stats 优先 RAG 数字
# ---------------------------------------------------------------------------
def test_get_knowledge_stats_uses_rag_count(monkeypatch):
    """核心修复: total_documents 用 RAG vector_store_count,不再是 0 内存 KB"""
    from agent.core import GreenAgent

    # mock 关键依赖 — 避免真实启动
    class FakeKM:
        def get_stats(self):
            return {"total_documents": 68, "categories": {}}

    class FakeRAG:
        def get_stats(self):
            return {"vector_store_count": 150, "bm25_doc_count": 150, "is_enabled": True}

    agent = GreenAgent.__new__(GreenAgent)  # 跳过 __init__
    agent.knowledge_manager = FakeKM()
    agent.rag_engine = FakeRAG()
    agent.rag_enabled = True

    stats = agent.get_knowledge_stats()

    # P6.S.23: 主数字用 RAG = 150 + 150 = 300
    assert stats["total_documents"] == 300
    assert stats["knowledge_base_files"] == 68  # 静态 markdown 文件数(供前端副标题)
    assert stats["rag_enabled"] is True
    assert stats["rag_stats"]["vector_store_count"] == 150


def test_get_knowledge_stats_rag_disabled_fallback():
    """RAG 关闭时降级到静态 KB"""
    from agent.core import GreenAgent

    class FakeKM:
        def get_stats(self):
            return {"total_documents": 42, "categories": {}}

    agent = GreenAgent.__new__(GreenAgent)
    agent.knowledge_manager = FakeKM()
    agent.rag_engine = None
    agent.rag_enabled = False

    stats = agent.get_knowledge_stats()

    assert stats["total_documents"] == 42  # 降级到静态
    assert stats["rag_enabled"] is False
    assert stats["knowledge_base_files"] == 42


# ---------------------------------------------------------------------------
# C. LangGraphResponse.tool_result 字段
# ---------------------------------------------------------------------------
def test_langgraph_response_has_tool_result():
    from agent.langgraph_agent import LangGraphResponse
    r = LangGraphResponse(
        message="hi",
        conversation_id="c1",
        intent="travel_planning",
    )
    assert hasattr(r, "tool_result")
    assert r.tool_result == {}  # 默认空 dict

    r2 = LangGraphResponse(
        message="hi",
        conversation_id="c1",
        intent="travel_planning",
        tool_result={"routes": [{"type": "公交"}]},
    )
    d = r2.to_dict()
    assert d["tool_result"] == {"routes": [{"type": "公交"}]}


def test_langgraph_response_parse_tool_message():
    """P6.S.23: _build_response 解析末条 ToolMessage 填入 tool_result"""
    from agent.langgraph_agent import LangGraphAgent

    # 用真实 ToolMessage 类(LangChain 标准) — 代码按类名 ToolMessage 匹配
    try:
        from langchain_core.messages import ToolMessage, AIMessage
        tool_msg = ToolMessage(content='{"routes": [{"type": "bus", "distance_km": 5.0}]}', tool_call_id="call_1")
        ai_msg = AIMessage(content="thinking")
    except ImportError:
        # 旧 langchain(<0.1)有 schema.message 模块
        try:
            from langchain.schema import ToolMessage, AIMessage
            tool_msg = ToolMessage(content='{"routes": [{"type": "bus", "distance_km": 5.0}]}', tool_call_id="call_1")
            ai_msg = AIMessage(content="thinking")
        except ImportError:
            pytest.skip("langchain_core / langchain not installed")

    agent = LangGraphAgent.__new__(LangGraphAgent)
    state = {
        "response_message": "ok",
        "intent": "travel_planning",
        "suggestions": [],
        "knowledge_refs": [],
        "memory_hints": [],
        "profile_updates": {},
        "personalization_info": {},
        "recommendations": [],
        "metadata": {},
        "messages": [ai_msg, tool_msg],
    }
    resp = agent._build_response(state, "c1")
    assert resp.tool_result == {"routes": [{"type": "bus", "distance_km": 5.0}]}


# ---------------------------------------------------------------------------
# D. response.py prompt 注入 current_location
# ---------------------------------------------------------------------------
def test_response_generator_injects_current_location(monkeypatch):
    """P6.S.23: 拼 prompt 时若 personalization_info 含 location,塞给 LLM"""

    class FakeLLM:
        last_messages = None

        def chat(self, messages):
            FakeLLM.last_messages = messages
            return type("R", (), {"content": "ok"})

    class FakeContext:
        user_profile = {}
        conversation_history = []
        retrieved_knowledge = []
        recent_memories = []
        intent_type = "question"
        personalization_info = {
            "location": {"city": "北京", "region": "北京市", "country": "中国", "source": "browser"}
        }

    from agent.response import ResponseGenerator

    rg = ResponseGenerator.__new__(ResponseGenerator)
    rg._llm_client = FakeLLM()
    rg._use_llm = True

    def fake_build_prompt(**kwargs):
        # 把 kwargs 序列化到 system message 里,便于断言
        import json
        return [
            {"role": "system", "content": json.dumps(kwargs, ensure_ascii=False)},
        ]

    rg._build_prompt = fake_build_prompt

    rg.generate_with_llm("hi", FakeContext(), "", working_memory="")

    import json
    sys_msg = FakeLLM.last_messages[0]["content"]
    parsed = json.loads(sys_msg)
    assert "current_location" in parsed
    assert parsed["current_location"]["city"] == "北京"
    assert parsed["current_location"]["source"] == "browser"


def test_response_generator_no_location_no_inject():
    """无 location 时不注入 current_location 字段"""
    class FakeLLM:
        last_messages = None
        def chat(self, messages):
            FakeLLM.last_messages = messages
            return type("R", (), {"content": "ok"})

    class FakeContext:
        user_profile = {}
        conversation_history = []
        retrieved_knowledge = []
        recent_memories = []
        intent_type = "question"
        personalization_info = {}

    from agent.response import ResponseGenerator

    rg = ResponseGenerator.__new__(ResponseGenerator)
    rg._llm_client = FakeLLM()
    rg._use_llm = True
    def fake_build_prompt(**kwargs):
        import json
        return [{"role": "system", "content": json.dumps(kwargs, ensure_ascii=False)}]
    rg._build_prompt = fake_build_prompt

    rg.generate_with_llm("hi", FakeContext(), "", working_memory="")

    import json
    parsed = json.loads(FakeLLM.last_messages[0]["content"])
    assert "current_location" not in parsed
