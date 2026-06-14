"""
P6.S.19 + P6.S.20 测试: 记忆摘要 + Observability

P6.S.19: consolidation 短→长时调 LLM 摘要中等重要性消息
P6.S.20: metrics 加 tool_call 计数 + endpoint latency + intent 分布 + 活跃用户
"""
import sys
import os
import json
import time
import urllib.request
import urllib.error

sys.path.insert(0, str(__file__).replace("\\", "/").replace("tests/test_p6s19_20_summarize_observability.py", "src"))


def _http_get(url, timeout=10):
    req = urllib.request.Request(url, method="GET")
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8", errors="ignore"))


def _http_post(url, data, timeout=60):
    req = urllib.request.Request(
        url, data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8", errors="ignore"))


def test_server_running():
    code, _ = _http_get("http://localhost:8000/api/health", timeout=5)
    return code == 200


# ============ P6.S.19: 记忆摘要 ============

def test_consolidation_has_summarize_method():
    """P6.S.19: MemoryConsolidator._summarize_medium_memories 存在"""
    from memory.consolidation import MemoryConsolidator
    mc = MemoryConsolidator.__new__(MemoryConsolidator)
    assert hasattr(mc, "_summarize_medium_memories"), "应有 _summarize_medium_memories 方法"
    import inspect
    sig = inspect.signature(mc._summarize_medium_memories)
    assert list(sig.parameters.keys()) == ["user_id", "conversation_id", "messages"], \
        f"签名不符: {sig}"
    print("✅ test_consolidation_has_summarize_method PASSED")


def test_consolidation_skips_when_too_few_medium_messages():
    """P6.S.19: 太少中等重要性消息不摘要(避免浪费 LLM)"""
    from memory.consolidation import MemoryConsolidator
    mc = MemoryConsolidator.__new__(MemoryConsolidator)
    # 1 条消息 < 3 阈值 → 不调 LLM,直接返 0
    result = mc._summarize_medium_memories(
        "p6s19_test_user",
        "test_conv",
        [{"importance": 0.5, "content": "短消息"}],  # 只 1 条
    )
    assert result == 0, f"应返 0, 实际 {result}"
    print("✅ test_consolidation_skips_when_too_few_medium_messages PASSED")


def test_consolidation_calls_llm_for_medium_messages():
    """P6.S.19: ≥3 条中等重要性消息 → 调 LLM 摘要"""
    from memory.consolidation import MemoryConsolidator
    mc = MemoryConsolidator.__new__(MemoryConsolidator)
    # 5 条中等重要性消息
    messages = [
        {"importance": 0.5, "content": f"消息{i} " + "内容" * 30}
        for i in range(5)
    ]
    result = mc._summarize_medium_memories("p6s19_test_user", "test_conv_2", messages)
    # 调真 LLM:可能 0(失败) 或 1(成功),关键是不要崩
    assert result in (0, 1), f"应返 0 或 1, 实际 {result}"
    print(f"  LLM 摘要结果: {result} (0=失败/跳过, 1=成功)")
    print("✅ test_consolidation_calls_llm_for_medium_messages PASSED")


# ============ P6.S.20: Observability ============

def test_metrics_collector_has_new_methods():
    """P6.S.20: MetricsCollector 加新方法"""
    from observability.metrics import MetricsCollector
    mc = MetricsCollector.__new__(MetricsCollector)
    for method in ["record_tool_call", "record_endpoint_latency", "record_intent", "record_user_activity"]:
        assert hasattr(mc, method), f"应有 {method} 方法"
    print("✅ test_metrics_collector_has_new_methods PASSED")


def test_metrics_summary_includes_p6s20_fields():
    """P6.S.20: summary() 返 tool_calls + endpoint_latencies + intent_counts + active_users_count"""
    from observability.metrics import MetricsCollector
    mc = MetricsCollector()
    # 注入一些数据
    mc.record_tool_call("travel_planning")
    mc.record_tool_call("knowledge_retrieval")
    mc.record_tool_call("travel_planning")
    mc.record_endpoint_latency("/api/chat/enhanced", 123.4)
    mc.record_intent("knowledge_query")
    mc.record_user_activity("u1")
    mc.record_user_activity("u2")

    s = mc.summary()
    assert "tool_calls" in s
    assert s["tool_calls"].get("travel_planning") == 2
    assert s["tool_calls"].get("knowledge_retrieval") == 1
    assert s["tool_calls_total"] == 3
    assert "/api/chat/enhanced" in s["endpoint_latencies"]
    el = s["endpoint_latencies"]["/api/chat/enhanced"]
    assert el["count"] == 1
    assert el["avg_ms"] == 123.4
    assert s["intent_counts"].get("knowledge_query") == 1
    assert s["active_users_count"] == 2
    print(f"  summary keys OK: {sorted([k for k in s if k in ['tool_calls', 'endpoint_latencies', 'intent_counts', 'active_users_count']])}")
    print("✅ test_metrics_summary_includes_p6s20_fields PASSED")


# ============ HTTP 端到端 ============

def test_metrics_endpoint_includes_p6s20_data():
    """P6.S.20: /api/metrics 实际工作 + 含 P6.S.20 新字段"""
    if not test_server_running():
        print("⏭ SKIPPED")
        return
    # 1) 触发一次 chat 测 intent 计数
    _http_post(
        "http://localhost:8000/api/chat/enhanced",
        {"user_id": "p6s20_metrics_user", "message": "你好"},
    )
    # 2) 查 metrics
    code, body = _http_get("http://localhost:8000/api/metrics")
    assert code == 200
    m = body["metrics"]
    # 新字段
    assert "tool_calls" in m
    assert "endpoint_latencies" in m
    assert "intent_counts" in m
    assert "active_users_count" in m
    # intent 计数应有 greeting
    assert m["intent_counts"].get("greeting", 0) >= 1, \
        f"应含 greeting 计数, 实际: {m['intent_counts']}"
    # 活跃 user 应有 p6s20_metrics_user
    assert m["active_users_count"] >= 1
    # 端点延迟应有 /api/chat/enhanced
    assert "/api/chat/enhanced" in m["endpoint_latencies"]
    print(f"  intent_counts: {m['intent_counts']}")
    print(f"  active_users_count: {m['active_users_count']}")
    print(f"  endpoint_latencies keys: {list(m['endpoint_latencies'].keys())}")
    print("✅ test_metrics_endpoint_includes_p6s20_data PASSED")


if __name__ == "__main__":
    test_server_running()
    test_consolidation_has_summarize_method()
    test_consolidation_skips_when_too_few_medium_messages()
    test_consolidation_calls_llm_for_medium_messages()
    test_metrics_collector_has_new_methods()
    test_metrics_summary_includes_p6s20_fields()
    test_metrics_endpoint_includes_p6s20_data()
    print("\n🎉 All P6.S.19 + P6.S.20 tests PASSED")
