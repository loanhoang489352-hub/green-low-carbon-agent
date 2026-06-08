"""
验证 P0-2 修复:onboarding 步骤判断逻辑

P0-2 之前:`if step == len(questions)` 永不触发(实际只有 8 题,step 0-7,
最后一题 step=7 != 8),用户卡在"已完成但未标 completed"状态。
P0-2 之后:`if next_step >= len(questions)` 正确触发完成。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agent.core import GreenAgent


def _make_agent():
    """创建一个最小可用的 GreenAgent(关闭 RAG/LLM)"""
    return GreenAgent(
        knowledge_base_path="knowledge_base",
        enable_rag=False,
        use_llm=False,
    )


def test_onboarding_completes_on_last_step():
    """回答最后一题时,completed=True"""
    agent = _make_agent()
    user_id = "test_user_1"

    agent.profile_manager.update_profile(user_id, {"onboarding_step": 0})
    questions = agent.profile_manager.get_onboarding_questions()
    last_step = max(q["step"] for q in questions)
    print(f"  last_step = {last_step}, total questions = {len(questions)}")

    result = agent.process_onboarding_answer(user_id, last_step, "test_answer")

    assert result.get("completed") is True, f"最后一题应标 completed=True,实际 {result}"
    assert "message" in result
    print(f"✅ test_onboarding_completes_on_last_step PASSED (step={last_step} -> completed)")


def test_onboarding_not_completed_before_last():
    """回答非最后题时,completed=False 且 next_question 不为 None"""
    agent = _make_agent()
    user_id = "test_user_2"
    agent.profile_manager.update_profile(user_id, {"onboarding_step": 0})

    questions = agent.profile_manager.get_onboarding_questions()
    first_step = min(q["step"] for q in questions)
    result = agent.process_onboarding_answer(user_id, first_step, "test_answer")

    assert result.get("completed") is False
    assert result.get("next_question") is not None
    print(f"✅ test_onboarding_not_completed_before_last PASSED (step={first_step} -> next question)")


if __name__ == "__main__":
    test_onboarding_completes_on_last_step()
    test_onboarding_not_completed_before_last()
    print("\n🎉 all onboarding fix tests passed")
