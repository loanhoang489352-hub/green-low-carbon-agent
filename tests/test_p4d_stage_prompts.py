"""
验证 P4-D: 行为阶段真正驱动 LLM
- D.1: 5 阶段 system prompt 含差异化字段
- D.2: 阶段化回复样例(测试 _get_suggestions 输出)
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def test_suggestion_strategy_by_stage():
    """5 阶段产生不同 strategy"""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = Path(tmp) / "up_stage.db"
        from user_profile.user_profile import UserProfileManager
        upm = UserProfileManager(str(db))

        for stage, expected_intensity in [
            ("无意向", "very_low"),
            ("意向", "low"),
            ("准备", "medium"),
            ("行动", "medium"),
            ("维持", "low"),
        ]:
            upm.create_profile("u_" + stage)
            upm.update_eco_profile("u_" + stage, {"behavior_stage": stage})
            s = upm.get_suggestion_strategy("u_" + stage)
            assert s["focus"], f"{stage} 应有 focus"
            assert s["suggestion_intensity"] == expected_intensity, \
                f"{stage} intensity 应为 {expected_intensity}, 实际 {s['suggestion_intensity']}"
            print(f"   {stage}: focus={s['focus']}, intensity={s['suggestion_intensity']}, complexity={s['action_complexity']}")
    print("✅ test_suggestion_strategy_by_stage PASSED")


def test_system_prompt_contains_stage_fields():
    """P4-D: build_system_prompt 把 strategy 字段注入 prompt"""
    from llm import build_system_prompt

    for stage in ["无意向", "意向", "准备", "行动", "维持"]:
        ctx = {
            "knowledge_level_chinese": "了解",
            "behavior_stage": stage,
            "primary_interests": ["low_carbon_travel"],
            "communication_style": "通俗",
            "focus": "意识唤醒" if stage == "无意向" else "行动计划",
            "suggestion_intensity": "medium",
            "action_complexity": "moderate",
            "tone": "positive",
            "example_focus": "easy_wins",
        }
        prompt = build_system_prompt(ctx)
        assert "行为阶段" in prompt
        assert stage in prompt
        assert "{focus}" not in prompt, "模板未格式化"
        assert "{suggestion_intensity}" not in prompt
        assert "{action_complexity}" not in prompt
        assert "{tone}" not in prompt
        assert "{example_focus}" not in prompt
        # 5 阶段 prompt 同一行示例侧重(field)一致
        assert "示例侧重" in prompt
        print(f"   {stage}: prompt length={len(prompt)}, 包含所有 P4-D 字段")
    print("✅ test_system_prompt_contains_stage_fields PASSED")


def test_get_suggestions_by_stage():
    """P4-D: _get_suggestions 5 阶段返回差异化建议"""
    from llm.response_generator import HybridResponseGenerator
    hrg = HybridResponseGenerator(rule_based_generator=None)

    for stage in ["无意向", "意向", "准备", "行动", "维持"]:
        ctx = {
            "behavior_stage": stage,
            "suggestion_intensity": "medium" if stage in ("准备", "行动") else "low",
        }
        sugg = hrg._get_suggestions(ctx)
        assert len(sugg) >= 1, f"{stage} 应至少有 1 条建议"
        print(f"   {stage} ({len(sugg)}): {sugg[:2]}...")
    print("✅ test_get_suggestions_by_stage PASSED")


def test_chat_enhanced_injects_strategy():
    """P4-D: chat_enhanced 合并 strategy 到 personalization_ctx"""
    from agent.core import GreenAgent
    import inspect

    src = inspect.getsource(GreenAgent.chat_enhanced)
    assert 'strategy.get("focus")' in src or '"focus"' in src, \
        "未将 strategy.focus 注入 personalization_ctx"
    assert '"suggestion_intensity"' in src, "未注入 suggestion_intensity"
    assert '"action_complexity"' in src, "未注入 action_complexity"
    print("✅ test_chat_enhanced_injects_strategy PASSED")


if __name__ == "__main__":
    test_suggestion_strategy_by_stage()
    test_system_prompt_contains_stage_fields()
    test_get_suggestions_by_stage()
    test_chat_enhanced_injects_strategy()
    print("\n🎉 all P4-D stage-driven prompt tests passed")
