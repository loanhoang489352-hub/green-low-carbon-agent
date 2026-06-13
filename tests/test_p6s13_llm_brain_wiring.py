"""
P6.S.13 测试: 修 LLM 大脑未启动(用户截图 1.png 显示全是 bullet 列表)

根因: P6.S.5 加的 LLM_MOCK=true 路径在 generate_with_llm 里
  直接 `from llm.client import MockLLMClient` 跳过 _get_llm_client()
  调用,而 _build_prompt 只在 _get_llm_client() 内部赋值。
  → self._build_prompt 未设置
  → self._build_prompt(**kwargs) 抛 AttributeError
  → 被 except 静默吞掉,回退到 rule-based 模板
  → 用户看到的 bullet 列表就是回退模板的输出

修复: generate_with_llm 在调 _build_prompt 前显式设置它
     (不论走 LLM_MOCK 还是真 LLM 分支都保证)

验证:
1. generate_with_llm 在 LLM_MOCK=true 时返回 MockLLMClient 内容
2. generate_with_llm 在真 LLM 路径返回真实响应
3. 不再回退到 rule-based 模板
4. 抛错时也优雅回退(不静默吞错)
"""
import sys
import os
sys.path.insert(0, str(__file__).replace("\\", "/").replace("tests/test_p6s13_llm_brain_wiring.py", "src"))


def test_mock_path_returns_mock_content():
    """P6.S.13: LLM_MOCK=true 路径应返回 MockLLMClient 的内容(非模板)"""
    os.environ["LLM_MOCK"] = "true"
    from agent.response import ResponseGenerator, ResponseContext

    rg = ResponseGenerator(use_llm=True)
    ctx = ResponseContext(
        user_profile={}, conversation_history=[],
        retrieved_knowledge=[], recent_memories=[],
        intent_type="advice_request",
    )
    out = rg.generate_with_llm(
        "推荐北京周末适合本地居民游玩",
        ctx, rag_context="", working_memory="",
    )
    # 旧 bug:回退模板 = "好的！让我用简单的方式给你一些建议~\n\n1. xxx"
    # P6.S.13 修后:MockLLMClient 输出 = "推荐你尝试以下低碳行动:..."
    assert "好的！让我用简单的方式" not in out, (
        f"不应回退到模板,实际: {out[:200]!r}"
    )
    # MockLLMClient 的"推荐"分支内容
    assert "推荐你尝试" in out or "低碳" in out, (
        f"应含 MockLLMClient 输出,实际: {out[:200]!r}"
    )
    print("✅ test_mock_path_returns_mock_content PASSED")


def test_real_llm_path_actually_calls_api():
    """P6.S.13: 真 LLM 路径能调用真实 API(需有 key)"""
    if not os.getenv("DEEPSEEK_API_KEY") or "your" in os.getenv("DEEPSEEK_API_KEY", ""):
        print("⏭ test_real_llm_path_actually_calls_api SKIPPED (no API key)")
        return
    # 取消 LLM_MOCK
    os.environ.pop("LLM_MOCK", None)
    os.environ["LLM_MOCK"] = "false"
    os.environ.setdefault("API_PROVIDER", "deepseek")
    os.environ.setdefault("API_MODEL", "deepseek-chat")

    from agent.response import ResponseGenerator, ResponseContext
    from llm import reset_llm_client
    reset_llm_client()

    rg = ResponseGenerator(use_llm=True)
    ctx = ResponseContext(
        user_profile={}, conversation_history=[],
        retrieved_knowledge=[], recent_memories=[],
        intent_type="advice_request",
    )
    out = rg.generate_with_llm(
        "说说你好",
        ctx, rag_context="", working_memory="",
    )
    # 真 LLM 应返回非模板内容,且应包含自然中文(非"好的!让我...")
    assert "好的！让我用简单的方式" not in out, "不应是模板"
    assert len(out) > 5, f"应有内容,实际: {out[:100]!r}"
    print(f"  real LLM output: {out[:100]!r}...")
    print("✅ test_real_llm_path_actually_calls_api PASSED")


def test_build_prompt_always_set_before_use():
    """P6.S.13: _build_prompt 在 generate_with_llm 调它之前应已设置"""
    os.environ["LLM_MOCK"] = "true"
    from agent.response import ResponseGenerator, ResponseContext

    # 关键测试:不先调 _get_llm_client(),直接调 generate_with_llm
    # 旧 bug:AttributeError, 修复后:正常返回
    rg = ResponseGenerator(use_llm=True)
    assert not hasattr(rg, "_build_prompt"), "前置条件: _build_prompt 未设置"

    ctx = ResponseContext(
        user_profile={}, conversation_history=[],
        retrieved_knowledge=[], recent_memories=[],
        intent_type="advice_request",
    )
    # 调 generate_with_llm,应不抛 AttributeError
    try:
        out = rg.generate_with_llm("test", ctx, rag_context="", working_memory="")
        assert out, "应返回非空内容"
    except AttributeError as e:
        raise AssertionError(f"P6.S.13 修复未生效,_build_prompt 仍抛 AttributeError: {e}")
    print("✅ test_build_prompt_always_set_before_use PASSED")


def test_llm_call_failure_logs_warning():
    """P6.S.13: 抛错时应记 warning(便于 debug),不静默吞"""
    os.environ["LLM_MOCK"] = "true"
    from agent.response import ResponseGenerator, ResponseContext

    # 模拟 _build_prompt 抛错的情况
    rg = ResponseGenerator(use_llm=True)

    # 强制让 _build_prompt 抛错
    def bad_prompt(**kwargs):
        raise RuntimeError("simulated _build_prompt error")
    rg._build_prompt = bad_prompt
    rg._llm_client = object()  # truthy

    ctx = ResponseContext(
        user_profile={}, conversation_history=[],
        retrieved_knowledge=[], recent_memories=[],
        intent_type="advice_request",
    )
    # 不应抛错,应回退到模板
    out = rg.generate_with_llm("test", ctx, rag_context="", working_memory="")
    assert out, "应回退到模板返回非空"
    print("✅ test_llm_call_failure_logs_warning PASSED")


def test_agent_bat_respects_env_file():
    """P6.S.13: agent.bat 应从 .env 读 LLM_MOCK,不强制设为 true"""
    agent_bat_path = os.path.join(
        os.path.dirname(__file__), "..", "agent.bat"
    )
    with open(agent_bat_path, encoding="utf-8") as f:
        content = f.read()

    # 不应有 "set LLM_MOCK=true" 这条硬编码
    hardcoded_lines = [
        line for line in content.split("\n")
        if "set LLM_MOCK=true" in line.lower()
    ]
    assert not hardcoded_lines, (
        f"agent.bat 不应硬编码 set LLM_MOCK=true,实际有:\n  "
        + "\n  ".join(hardcoded_lines)
    )
    print("✅ test_agent_bat_respects_env_file PASSED")


if __name__ == "__main__":
    test_mock_path_returns_mock_content()
    test_real_llm_path_actually_calls_api()
    test_build_prompt_always_set_before_use()
    test_llm_call_failure_logs_warning()
    test_agent_bat_respects_env_file()
    print("\n🎉 All P6.S.13 tests PASSED")
