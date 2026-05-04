"""贝叶斯路由器独立测试"""
import sys
import os
import random

out_lines = []

def log(msg):
    out_lines.append(str(msg))
    print(msg, flush=True)

try:
    sys.path.insert(0, r"d:\绿色低碳智能体\src")

    # 避免自动初始化所有LLM客户端（会有网络请求）
    os.environ["OPENAI_API_KEY"] = "sk-fake"
    os.environ["ZHIPU_API_KEY"] = "fake"
    os.environ["BAIDU_API_KEY"] = "fake"
    os.environ["BAIDU_SECRET_KEY"] = "fake"
    os.environ["ALI_API_KEY"] = "fake"
    os.environ["MINIMAX_API_KEY"] = "fake"
    os.environ["DEEPSEEK_API_KEY"] = "fake"

    log("=" * 60)
    log("Step 1: BetaDistribution 测试")
    log("=" * 60)

    from llm.client import BetaDistribution

    bd1 = BetaDistribution(3.0, 1.0)
    bd2 = BetaDistribution(1.0, 3.0)
    bd3 = BetaDistribution(1.0, 1.0)

    log(f"Beta(3,1) 均值: {bd1.mean():.4f}")
    log(f"Beta(1,3) 均值: {bd2.mean():.4f}")
    log(f"Beta(1,1) 均值: {bd3.mean():.4f}")

    p = bd1.probability_of_beating(bd2)
    log(f"P(Beta(3,1) > Beta(1,3)): {p:.4f}  (期望 > 0.9)")
    assert p > 0.8, f"概率测试失败: {p}"

    log("\n--- 后验更新 ---")
    bd = BetaDistribution(1.0, 1.0)
    log(f"初始: alpha={bd.alpha:.1f}, beta={bd.beta:.1f}, mean={bd.mean():.4f}")
    for _ in range(10):
        bd.update(success=True)
    log(f"10次成功: alpha={bd.alpha:.1f}, beta={bd.beta:.1f}, mean={bd.mean():.4f}")
    assert abs(bd.mean() - 11.0/12.0) < 0.01, "Beta更新失败"
    for _ in range(10):
        bd.update(success=False)
    log(f"10次失败: alpha={bd.alpha:.1f}, beta={bd.beta:.1f}, mean={bd.mean():.4f}")
    assert bd.mean() < 0.55, "Beta更新失败"
    log("BetaDistribution 测试通过!")

    log("\n" + "=" * 60)
    log("Step 2: ModelStats 测试")
    log("=" * 60)

    from llm.client import ModelStats, MockLLMClient

    stats = ModelStats("test-model", "test")
    for i in range(5):
        stats.record_call(success=True, latency_ms=100.0, response=f"第{i+1}次成功")
    for _ in range(3):
        stats.record_call(success=False, latency_ms=200.0, response="")
    for i in range(2):
        stats.record_call(success=True, latency_ms=150.0, response="[Mock]好的")

    log(f"总调用: {stats.total_calls} | 成功: {stats.success_calls} | 失败: {stats.failed_calls}")
    log(f"成功率: {stats.success_rate():.1%}")
    log(f"Beta: alpha={stats.success_dist.alpha:.2f}, beta={stats.success_dist.beta:.2f}")
    assert stats.total_calls == 10
    assert stats.success_calls == 7
    assert stats.failed_calls == 3
    log("ModelStats 测试通过!")

    log("\n" + "=" * 60)
    log("Step 3: BayesianModelRouter 测试 (不依赖真实API)")
    log("=" * 60)

    from llm.client import BayesianModelRouter, BayesianModelRouter as BMR

    router = BayesianModelRouter(strategy=BMR.STRATEGY_THOMPSON, auto_add_clients=False)
    router.register_model("mock-a", MockLLMClient(), "Mock-A")
    router.register_model("mock-b", MockLLMClient(), "Mock-B")
    router.register_model("mock-c", MockLLMClient(), "Mock-C")

    log(f"注册模型: {list(router._models.keys())}")
    assert len(router._models) == 3

    log("\n--- 50轮Thompson Sampling（带质量差异的Mock） ---")

    class NoisyMockClient(MockLLMClient):
        """返回质量有差异的Mock客户端（用于测试探索）"""
        def __init__(self, quality_bias: float = 0.5):
            super().__init__()
            self.quality_bias = quality_bias  # 0.3 ~ 0.8 的质量偏向

        def chat(self, messages, **kwargs):
            resp = super().chat(messages, **kwargs)
            # 注入不同内容使质量评估产生差异
            suffix = f"[质量:{self.quality_bias:.1f}][响应ID:{random.randint(1000,9999)}]"
            return resp + suffix

    # 重新注册，让每个模型有不同的质量偏向
    router.register_model("mock-a", NoisyMockClient(0.8), "Mock-A-High")
    router.register_model("mock-b", NoisyMockClient(0.5), "Mock-B-Med")
    router.register_model("mock-c", NoisyMockClient(0.3), "Mock-C-Low")

    counts = {"mock-a": 0, "mock-b": 0, "mock-c": 0}
    for i in range(50):
        selected = router.select_model()
        counts[selected] += 1
        resp = router._clients[selected].chat([{"role": "user", "content": f"test{i}"}])
        router.record_result(selected, True, 100.0, resp)

    log(f"选择分布: {counts}")
    success_rates = {k: round(v.success_rate(), 3) for k, v in router._models.items()}
    log(f"成功率: {success_rates}")
    log(f"主导模型: {max(counts, key=counts.get)}（质量高的模型应被更多选择）")

    log("\n--- 策略切换 ---")
    for strat in [BMR.STRATEGY_THOMPSON, BMR.STRATEGY_UCB, BMR.STRATEGY_GREEDY, BMR.STRATEGY_RANDOM]:
        router.set_strategy(strat)
        selected = router.select_model()
        log(f"  {strat:10s} -> {selected}")
        assert selected in router._models

    log("\n--- 摘要 ---")
    summary = router.summary()
    log(summary)
    assert "BayesianRouter" in summary

    log("\n--- 推荐 ---")
    rec = router.get_recommendation()
    log(f"推荐: {rec['recommended']}, 理由: {rec['reason']}")
    log("BayesianModelRouter 测试通过!")

    log("\n" + "=" * 60)
    log("Step 4: BayesianLLMClient 独立测试（不自动初始化）")
    log("=" * 60)

    from llm.client import BayesianLLMClient, BayesianModelRouter as BMR2

    # 直接创建路由器，不走 auto_add
    bayes_router = BayesianModelRouter(strategy=BMR2.STRATEGY_THOMPSON, auto_add_clients=False)
    bayes_router.register_model("m1", MockLLMClient(), "Model-1")
    bayes_router.register_model("m2", NoisyMockClient(0.7), "Model-2")
    bayes_router.register_model("m3", NoisyMockClient(0.4), "Model-3")

    bayes_client = BayesianLLMClient(strategy=BMR2.STRATEGY_THOMPSON)
    bayes_client.router = bayes_router  # 替换为测试路由器

    log(f"类型: {type(bayes_client).__name__}")
    log(f"策略: {bayes_client.router.strategy}")
    log(f"注册模型: {list(bayes_client.router._models.keys())}")

    # chat调用
    resp = bayes_client.chat([{"role": "user", "content": "什么是碳中和？"}])
    log(f"响应: {resp[:80]}")
    assert len(resp) > 0

    log("\n--- 策略动态切换 ---")
    bayes_client.set_strategy("ucb")
    assert bayes_client.router.strategy == "ucb"
    log("策略切换测试通过!")

    log("\n--- 统计信息 ---")
    all_stats = bayes_client.get_stats()
    for mid, s in all_stats.items():
        log(f"  {mid}: 调用{s['total_calls']}次, 成功率{s['success_rate']:.1%}")

    log("\n" + "=" * 60)
    log("Step 5: 快速集成测试 (模拟并发 + 边缘情况)")
    log("=" * 60)

    import threading

    router2 = BayesianModelRouter(strategy=BMR.STRATEGY_THOMPSON, auto_add_clients=False)
    router2.register_model("m1", MockLLMClient(), "Model1")
    router2.register_model("m2", MockLLMClient(), "Model2")

    def worker():
        for _ in range(10):
            m = router2.select_model()
            r = router2._clients[m].chat([{"role": "user", "content": "hi"}])
            router2.record_result(m, "错误" not in r, 50.0, r)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    log(f"并发测试完成: 总调用{sum(m.total_calls for m in router2._models.values())}")
    assert all(m.total_calls == 10 for m in router2._models.values())
    log("并发测试通过!")

    log("\n--- 边缘情况 ---")
    router3 = BayesianModelRouter(strategy=BMR.STRATEGY_THOMPSON, auto_add_clients=False)
    router3.register_model("only", MockLLMClient(), "Only")
    sel = router3.select_model()
    log(f"单模型选择: {sel}")
    assert sel == "only"
    log("边缘情况测试通过!")

    log("\n" + "=" * 60)
    log("所有测试通过!")
    log("=" * 60)

    status = "OK"

except Exception as e:
    import traceback
    out_lines.append(f"\n[ERROR] {e}")
    out_lines.append(traceback.format_exc())
    status = f"FAIL: {e}"

with open(r"d:\绿色低碳智能体\test_bayesian_output.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out_lines))

sys.exit(0 if status == "OK" else 1)
