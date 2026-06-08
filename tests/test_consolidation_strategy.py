"""
验证 P3-余 consolidation 策略模式重构
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def test_threshold_strategy_importance_score():
    """ThresholdStrategy 应能根据 intent 算 importance"""
    from memory.consolidation import ThresholdStrategy
    s = ThresholdStrategy()
    msg = {"role": "user", "content": "我决定开始垃圾分类", "metadata": {"intent": "action_report"}}
    score = s.importance_score(msg)
    assert 0.5 <= score <= 1.0, f"action_report 重要性应在 0.5+, 实际 {score}"
    print(f"✅ threshold.importance_score(action_report) = {score:.2f}")


def test_threshold_strategy_should_consolidate_by_turns():
    """达到 10 轮应触发整合"""
    from memory.consolidation import ThresholdStrategy
    s = ThresholdStrategy()
    assert s.should_consolidate({"turn_count": 10, "message_count": 0}) is True
    assert s.should_consolidate({"turn_count": 9, "message_count": 0}) is False
    print("✅ threshold.should_consolidate(turns>=10) OK")


def test_adaptive_lowers_threshold_for_active_users():
    """活跃用户(>20 消息/日)降低轮次阈值到 5"""
    from memory.consolidation import AdaptiveStrategy
    s = AdaptiveStrategy()
    s.record_user_activity("user1")
    # 模拟 25 次活动
    for _ in range(25):
        s.record_user_activity("user1")
    # 5 轮应该触发
    state = {"user_id": "user1", "turn_count": 5, "message_count": 0}
    assert s.should_consolidate(state) is True
    # 普通用户 5 轮不应触发
    state2 = {"user_id": "user2", "turn_count": 5, "message_count": 0}
    assert s.should_consolidate(state2) is False
    print("✅ adaptive 活跃用户降低阈值 OK")


def test_memory_consolidator_uses_strategy():
    """MemoryConsolidator 委托给策略"""
    from memory.consolidation import MemoryConsolidator, ThresholdStrategy
    mc = MemoryConsolidator(strategy=ThresholdStrategy())
    assert mc.strategy.name == "threshold"
    stats = mc.get_consolidation_stats("conv1")
    assert stats["strategy"] == "threshold"
    print(f"✅ MemoryConsolidator.strategy.name = {stats['strategy']}")


def test_get_consolidator_factory():
    """工厂函数按 strategy 参数选策略"""
    from memory.consolidation import get_consolidator, reset_consolidator
    reset_consolidator()
    c1 = get_consolidator("threshold")
    assert c1.strategy.name == "threshold"
    reset_consolidator()
    c2 = get_consolidator("adaptive")
    assert c2.strategy.name == "adaptive"
    print("✅ get_consolidator(threshold|adaptive) OK")


def test_backward_compat_adaptive_consolidator():
    """AdaptiveConsolidator 旧名仍可用,内部走 AdaptiveStrategy"""
    from memory.consolidation import AdaptiveConsolidator
    ac = AdaptiveConsolidator()
    assert ac.strategy.name == "adaptive"
    ac.update_user_activity("user1")
    # 旧 API 仍工作
    state_should = ac.should_consolidate("conv1", user_id="user1")
    assert isinstance(state_should, bool)
    print("✅ AdaptiveConsolidator 兼容性 OK")


def test_consolidation_strategy_protocol():
    """自定义策略只要实现 Protocol 即可注入"""
    from memory.consolidation import MemoryConsolidator, ConsolidationStrategy

    class AlwaysStrategy:
        name = "always"
        def should_consolidate(self, state): return True
        def importance_score(self, message): return 1.0

    # 运行时 Protocol 校验
    s = AlwaysStrategy()
    assert isinstance(s, ConsolidationStrategy)

    mc = MemoryConsolidator(strategy=s)
    assert mc.should_consolidate("conv1") is True
    print("✅ ConsolidationStrategy Protocol 注入 OK")


if __name__ == "__main__":
    test_threshold_strategy_importance_score()
    test_threshold_strategy_should_consolidate_by_turns()
    test_adaptive_lowers_threshold_for_active_users()
    test_memory_consolidator_uses_strategy()
    test_get_consolidator_factory()
    test_backward_compat_adaptive_consolidator()
    test_consolidation_strategy_protocol()
    print("\n🎉 all consolidation strategy tests passed")
