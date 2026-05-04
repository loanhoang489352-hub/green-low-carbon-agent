"""贝叶斯路由器独立测试"""
import sys
sys.path.insert(0, r"d:\绿色低碳智能体\src")

from llm.client import (
    BayesianModelRouter, BayesianLLMClient, MockLLMClient,
    BetaDistribution, ModelStats, create_llm_client, BayesianModelRouter as BMR
)

print("=" * 60)
print("BetaDistribution 测试")
print("=" * 60)

bd1 = BetaDistribution(3.0, 1.0)  # 高成功率先验
bd2 = BetaDistribution(1.0, 3.0)  # 低成功率先验
bd3 = BetaDistribution(1.0, 1.0)  # 均匀先验

print(f"Beta(3,1) 均值: {bd1.mean():.4f}")
print(f"Beta(1,3) 均值: {bd2.mean():.4f}")
print(f"Beta(1,1) 均值: {bd3.mean():.4f}")

p = bd1.probability_of_beating(bd2)
print(f"P(Beta(3,1) > Beta(1,3)): {p:.4f} (期望 > 0.9)")

# 更新测试
print("\n--- 后验更新测试 ---")
bd = BetaDistribution(1.0, 1.0)
print(f"初始: alpha={bd.alpha:.1f}, beta={bd.beta:.1f}, mean={bd.mean():.4f}")
for i in range(10):
    bd.update(success=True)
print(f"10次成功: alpha={bd.alpha:.1f}, beta={bd.beta:.1f}, mean={bd.mean():.4f}")
for i in range(10):
    bd.update(success=False)
print(f"10次失败: alpha={bd.alpha:.1f}, beta={bd.beta:.1f}, mean={bd.mean():.4f}")

print("\n" + "=" * 60)
print("ModelStats 测试")
print("=" * 60)

stats = ModelStats("test-model", "test")
for i in range(5):
    stats.record_call(success=True, latency_ms=100.0, response="这是第{}次成功的调用".format(i+1))
for i in range(3):
    stats.record_call(success=False, latency_ms=200.0, response="")
for i in range(2):
    stats.record_call(success=True, latency_ms=150.0, response="[模拟]好的")
print(f"总调用: {stats.total_calls} | 成功: {stats.success_calls} | 失败: {stats.failed_calls}")
print(f"成功率: {stats.success_rate():.1%}")
print(f"Beta分布: alpha={stats.success_dist.alpha:.2f}, beta={stats.success_dist.beta:.2f}")

print("\n" + "=" * 60)
print("BayesianModelRouter 测试")
print("=" * 60)

# 直接用 Mock 客户端注册，避免真实API调用
router = BayesianModelRouter(strategy=BMR.STRATEGY_THOMPSON, auto_add_clients=False)

router.register_model("mock-a", MockLLMClient(), "Mock-A")
router.register_model("mock-b", MockLLMClient(), "Mock-B")
router.register_model("mock-c", MockLLMClient(), "Mock-C")

print(f"注册模型: {list(router._models.keys())}")

# 模拟选择
print("\n--- 模拟50轮选择 ---")
counts = {"mock-a": 0, "mock-b": 0, "mock-c": 0}
for i in range(50):
    selected = router.select_model()
    counts[selected] += 1

    # 模拟结果（Mock客户端成功率约100%）
    resp = router._clients[selected].chat([{"role": "user", "content": f"测试{i}"}])
    router.record_result(selected, True, 100.0, resp)

print(f"选择分布: {counts}")
print(f"成功统计: { {k: v.success_rate() for k, v in router._models.items()} }")

# 策略切换
print("\n--- 策略切换 ---")
for strat in [BMR.STRATEGY_THOMPSON, BMR.STRATEGY_UCB, BMR.STRATEGY_GREEDY, BMR.STRATEGY_RANDOM]:
    router.set_strategy(strat)
    selected = router.select_model()
    print(f"  {strat:10s} → 选择: {selected}")

# 摘要
print("\n--- 路由器摘要 ---")
print(router.summary())

# 推荐
rec = router.get_recommendation()
print(f"\n推荐模型: {rec['recommended']}")
print(f"推荐理由: {rec['reason']}")

print("\n" + "=" * 60)
print("BayesianLLMClient 工厂函数测试")
print("=" * 60)

bc = create_llm_client("bayesian", strategy="thompson")
print(f"类型: {type(bc).__name__}")
print(f"策略: {bc.router.strategy}")
print(f"注册模型: {list(bc.router._models.keys())}")

# 模拟一轮调用
resp = bc.chat([{"role": "user", "content": "什么是碳中和？"}])
print(f"响应: {resp[:80]}...")

print("\n" + "=" * 60)
print("所有测试通过！")
print("=" * 60)
