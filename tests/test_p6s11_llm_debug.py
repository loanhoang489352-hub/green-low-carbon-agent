"""
P6.S.11 测试: LLM 真实路径 + 意图感知 mock

验证:
1. MockLLMClient._create_response 对低碳主题返意图感知回复(非字面)
2. 对"你是什么模型"返"测试模式"
3. 碳中和 query 返"低碳"相关
4. 没 system_prompt 时返字面量(向后兼容)
5. get_llm_client() 在 LLM_MOCK=true 时返 mock
6. core.py 加了 LLM_MOCK 状态变更检测
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def test_mock_returns_intent_aware_for_low_carbon_system():
    """P6.S.11: 有低碳主题 system_prompt 时, mock 返意图感知回复"""
    from llm import MockLLMClient

    client = MockLLMClient()
    resp = client._create_response("碳中和是什么", system_prompt="你是绿宝,专注低碳生活")
    assert "低碳" in resp.content, f"应含'低碳', 实际 {resp.content!r}"
    assert "[Mock模式] 收到了:" not in resp.content, f"不应含字面量, 实际 {resp.content!r}"
    print("✅ test_mock_returns_intent_aware_for_low_carbon_system PASSED")


def test_mock_handles_model_question():
    """P6.S.11: 问'你是什么模型'应自然回答"""
    from llm import MockLLMClient

    client = MockLLMClient()
    resp = client._create_response("你是什么模型", system_prompt="你是绿宝,专注低碳")
    assert "测试模式" in resp.content, f"应说明是测试模式, 实际 {resp.content!r}"
    assert "绿宝" in resp.content, f"应自报家门为绿宝, 实际 {resp.content!r}"
    print("✅ test_mock_handles_model_question PASSED")


def test_mock_handles_policy_question():
    """P6.S.11: 问政策应引导到政策 tab"""
    from llm import MockLLMClient

    client = MockLLMClient()
    resp = client._create_response("有哪些低碳补贴政策?", system_prompt="你是绿宝,专注低碳")
    assert "政策" in resp.content, f"应提政策, 实际 {resp.content!r}"
    print("✅ test_mock_handles_policy_question PASSED")


def test_mock_handles_greeting():
    """P6.S.11: 寒暄应自然"""
    from llm import MockLLMClient

    client = MockLLMClient()
    resp = client._create_response("你好", system_prompt="你是绿宝,专注低碳")
    assert "你好" in resp.content
    assert "绿宝" in resp.content or "低碳" in resp.content
    print("✅ test_mock_handles_greeting PASSED")


def test_mock_handles_empty_input():
    """P6.S.11: 空 query 应友好提示"""
    from llm import MockLLMClient

    client = MockLLMClient()
    resp = client._create_response("", system_prompt="你是绿宝,专注低碳")
    assert "绿宝" in resp.content
    print("✅ test_mock_handles_empty_input PASSED")


def test_mock_no_system_prompt_falls_back_to_literal():
    """P6.S.11: 无 system_prompt 时仍返字面量(向后兼容)"""
    from llm import MockLLMClient

    client = MockLLMClient()
    resp = client._create_response("碳中和")
    assert "[Mock模式] 收到了:" in resp.content
    print("✅ test_mock_no_system_prompt_falls_back_to_literal PASSED")


def test_get_llm_client_falls_back_to_mock():
    """P6.S.11: LLM_MOCK=true 时 get_llm_client 返 MockLLMClient"""
    import os
    os.environ["LLM_MOCK"] = "true"
    # 重置 client 单例
    from llm import reset_llm_client, get_llm_client
    reset_llm_client()
    client = get_llm_client()
    assert client.__class__.__name__ == "MockLLMClient", f"应返 MockLLMClient, 实际 {client.__class__.__name__}"
    # 清理
    del os.environ["LLM_MOCK"]
    reset_llm_client()
    print("✅ test_get_llm_client_falls_back_to_mock PASSED")


def test_core_has_llm_mock_state_detection():
    """P6.S.11: core.py chat_enhanced 应有 LLM_MOCK 状态变更检测"""
    core_path = Path(__file__).resolve().parent.parent / "src" / "agent" / "core.py"
    src = core_path.read_text(encoding="utf-8")
    assert "_last_llm_mock_state" in src, "core.py 应有 _last_llm_mock_state 实例属性"
    assert "LLM_MOCK" in src and "状态变更" in src, "core.py 应检测 LLM_MOCK 状态变更"
    print("✅ test_core_has_llm_mock_state_detection PASSED")


def test_mock_response_is_string_and_llmresponse():
    """P6.S.11: _create_response 仍返 LLMResponse dataclass"""
    from llm import MockLLMClient
    from llm import LLMResponse

    client = MockLLMClient()
    resp = client._create_response("碳中和", system_prompt="你是绿宝")
    assert isinstance(resp, LLMResponse)
    assert isinstance(resp.content, str)
    assert resp.model == "mock"
    assert resp.finish_reason == "stop"
    print("✅ test_mock_response_is_string_and_llmresponse PASSED")


if __name__ == "__main__":
    test_mock_returns_intent_aware_for_low_carbon_system()
    test_mock_handles_model_question()
    test_mock_handles_policy_question()
    test_mock_handles_greeting()
    test_mock_handles_empty_input()
    test_mock_no_system_prompt_falls_back_to_literal()
    test_get_llm_client_falls_back_to_mock()
    test_core_has_llm_mock_state_detection()
    test_mock_response_is_string_and_llmresponse()
    print("\n🎉 All P6.S.11 tests PASSED")
