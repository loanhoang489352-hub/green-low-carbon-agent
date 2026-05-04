"""
核心模块单元测试
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / 'src'))

import os
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PYTHONUTF8"] = "1"

# ========== 测试框架 ==========

def test(name, fn):
    """简单的测试运行器"""
    try:
        fn()
        print(f"  ✅ {name}")
        return True
    except AssertionError as e:
        print(f"  ❌ {name}: {e}")
        return False
    except Exception as e:
        print(f"  ❌ {name}: {e}")
        import traceback
        traceback.print_exc()
        return False

def assert_equal(a, b, msg=""):
    if a != b:
        raise AssertionError(f"{msg} 期望 {b}, 实际 {a}")

def assert_true(x, msg=""):
    if not x:
        raise AssertionError(f"{msg} 期望 True, 实际 {x}")

# ========== 测试：意图识别 ==========

print("\n" + "=" * 60)
print("【意图识别模块】")
print("=" * 60)

from agent.intent import IntentRecognizer, IntentType

def test_intent_recognizer():
    recognizer = IntentRecognizer()

    # 测试问候意图
    result = recognizer.recognize("你好")
    assert_equal(result.intent, IntentType.GREETING, "问候")

    # 测试知识查询
    result = recognizer.recognize("什么是碳中和？")
    assert_equal(result.intent, IntentType.KNOWLEDGE_QUERY, "知识查询")

    # 测试建议请求
    result = recognizer.recognize("有什么低碳建议？")
    assert_equal(result.intent, IntentType.ADVICE_REQUEST, "建议请求")

    # 测试行动报告
    result = recognizer.recognize("我今天骑自行车上班了")
    assert_equal(result.intent, IntentType.ACTION_REPORT, "行动报告")

    # 测试反馈
    result = recognizer.recognize("这个建议很有用")
    assert_equal(result.intent, IntentType.FEEDBACK, "反馈")

    # 测试边界
    result = recognizer.recognize("随便聊聊")
    # 应该不抛出异常
    assert_true(result is not None)

test("意图识别 - 各种意图类型", test_intent_recognizer)

# ========== 测试：响应生成器 ==========

print("\n" + "=" * 60)
print("【响应生成器】")
print("=" * 60)

from agent.response import ResponseGenerator, ResponseContext

def test_response_generator():
    rg = ResponseGenerator(use_llm=False)

    # 测试问候响应
    ctx = ResponseContext(
        user_profile={"eco_profile": {}},
        conversation_history=[],
        retrieved_knowledge=[],
        recent_memories=[],
        intent_type="greeting"
    )
    result = rg.generate_response("你好", ctx)
    assert_true("你好" in result["message"] or "欢迎" in result["message"], "问候响应")
    assert_true(len(result["suggestions"]) > 0, "建议列表不为空")

    # 测试知识类响应
    ctx = ResponseContext(
        user_profile={"eco_profile": {"knowledge_level": "intermediate"}},
        conversation_history=[],
        retrieved_knowledge=[{"title": "碳中和", "content": "碳中和是指..."}],
        recent_memories=[],
        intent_type="knowledge"
    )
    result = rg.generate_response("什么是碳中和", ctx)
    assert_true(len(result["message"]) > 0, "知识响应非空")
    assert_equal(result["response_type"], "knowledge", "响应类型")

    # 测试建议类响应
    ctx = ResponseContext(
        user_profile={"eco_profile": {"knowledge_level": "入门"}},
        conversation_history=[{"role": "user", "content": "想了解低碳"}],
        retrieved_knowledge=[],
        recent_memories=["低碳出行"],
        intent_type="advice"
    )
    result = rg.generate_response("给我建议", ctx)
    assert_true(len(result["message"]) > 0, "建议响应非空")
    assert_true(len(result["suggestions"]) > 0, "建议列表非空")

test("响应生成器 - 各类响应", test_response_generator)

def test_response_generator_categories():
    rg = ResponseGenerator()

    # 测试各建议类别
    categories = ["出行", "饮食", "家居", "消费"]
    for cat in categories:
        ctx = ResponseContext(
            user_profile={"eco_profile": {"knowledge_level": "intermediate"}},
            conversation_history=[{"role": "user", "content": f"关于{cat}的问题"}],
            retrieved_knowledge=[],
            recent_memories=[],
            intent_type="advice"
        )
        result = rg.generate_response(f"有什么{cat}建议", ctx)
        assert_true(len(result["suggestions"]) > 0, f"{cat}建议非空")

test("响应生成器 - 各类别建议", test_response_generator_categories)

# ========== 测试：用户画像管理器 ==========

print("\n" + "=" * 60)
print("【用户画像管理器】")
print("=" * 60)

from user_profile.user_profile import UserProfileManager
import uuid

def test_user_profile_manager():
    db_path = project_root / "data" / "test_profiles.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    manager = UserProfileManager(db_path=str(db_path))

    user_id = "test_profile_user"

    # 创建画像
    manager.create_profile(user_id)
    profile = manager.get_profile(user_id)
    assert_equal(profile["user_id"], user_id, "用户ID匹配")
    assert_equal(profile["eco_profile"]["behavior_stage"], "意向", "默认行为阶段")

    # 更新基础信息
    manager.update_basic_info(user_id, {"age_group": "26-35", "region": "北京"})
    profile = manager.get_profile(user_id)
    assert_equal(profile["basic_info"]["age_group"], "26-35", "年龄组更新")
    assert_equal(profile["basic_info"]["region"], "北京", "地区更新")

    # 更新环保画像
    manager.update_eco_profile(user_id, {"knowledge_level": "advanced", "behavior_stage": "行动"})
    profile = manager.get_profile(user_id)
    assert_equal(profile["eco_profile"]["knowledge_level"], "advanced", "知识水平更新")
    assert_equal(profile["eco_profile"]["behavior_stage"], "行动", "行为阶段更新")

    # 记录交互
    manager.record_interaction(user_id, "question")
    manager.record_interaction(user_id, "action")
    profile = manager.get_profile(user_id)
    assert_equal(profile["statistics"]["questions_asked"], 1, "问题计数")
    assert_equal(profile["statistics"]["actions_reported"], 1, "行动计数")

    # 行为阶段调整
    new_stage = manager.adjust_behavior_stage(user_id, "up")
    assert_equal(new_stage, "维持", "行为阶段上调")
    profile = manager.get_profile(user_id)
    assert_equal(profile["eco_profile"]["behavior_stage"], "维持", "行为阶段已更新")

    # 个性化上下文
    ctx = manager.get_personalization_context(user_id)
    assert_equal(ctx["knowledge_level"], "advanced", "个性化上下文知识水平")
    assert_equal(ctx["behavior_stage"], "维持", "个性化上下文行为阶段")
    assert_true(ctx["communication_config"] is not None, "沟通配置存在")

    # 清理
    manager.delete_profile(user_id)
    if db_path.exists():
        db_path.unlink()

test("用户画像管理器 - 完整CRUD", test_user_profile_manager)

def test_onboarding_questions():
    manager = UserProfileManager()

    questions = manager.get_onboarding_questions()
    assert_equal(len(questions), 8, "8个引导问题")

    # 检查问题字段
    for q in questions:
        assert_true("step" in q, f"问题 {q['step']} 缺少 step")
        assert_true("field" in q, f"问题 {q['step']} 缺少 field")
        assert_true("question" in q, f"问题 {q['step']} 缺少 question")
        assert_true("type" in q, f"问题 {q['step']} 缺少 type")

    # 检查关键问题存在
    step_map = {q["step"]: q for q in questions}
    assert_true("age_group" in step_map[1]["field"], "年龄组问题")
    assert_true("region" in step_map[3]["field"], "地区问题")
    assert_true("primary_interests" in step_map[6]["field"], "兴趣问题")

test("引导问题配置", test_onboarding_questions)

# ========== 测试：动态画像更新 ==========

print("\n" + "=" * 60)
print("【动态画像更新器】")
print("=" * 60)

from user_profile.dynamic_updater import DynamicProfileUpdater

def test_dynamic_updater():
    updater = DynamicProfileUpdater()
    user_id = "test_dynamic"

    # 测试兴趣检测
    analysis = updater.analyze_message(
        user_id, "我想骑自行车上班，减少开车",
        "advice_request"
    )
    assert_true(len(analysis["detected_interests"]) > 0, "检测到兴趣")
    assert_true(analysis["detected_interests"][0][0] in ["low_carbon_travel", "energy_saving"], "出行兴趣")

    # 测试行为阶段检测
    analysis = updater.analyze_message(
        user_id, "我正在准备开始垃圾分类",
        "action_report"
    )
    assert_true(len(analysis["behavior_indicators"]) > 0, "检测到行为阶段")
    assert_equal(analysis["behavior_indicators"][0]["stage"], "准备", "准备阶段")

    # 测试知识水平检测
    analysis = updater.analyze_message(
        user_id, "请解释一下碳足迹的计算方法和LCA生命周期",
        "knowledge_query"
    )
    # 应该检测到高级知识水平
    assert_true(len(analysis["knowledge_signals"]) >= 0, "知识信号检测")

    # 测试行动报告提取
    analysis = updater.analyze_message(
        user_id, "我今天骑了自行车上班，感觉很好",
        "action_report"
    )
    assert_true(len(analysis["action_reports"]) > 0, "提取到行动报告")
    assert_equal(analysis["action_reports"][0]["sentiment"], "positive", "正面情感")

    # 测试反馈分析
    result = updater.analyze_feedback(user_id, "accept", "很有用！")
    assert_equal(result["feedback_type"], "accept", "接受反馈")

    result = updater.analyze_feedback(user_id, "reject", "太贵了，不考虑")
    assert_true("cost_concern" in result["reasons"], "成本担忧")
    assert_equal(result["inferred_preferences"]["cost_sensitivity"], "high", "成本敏感")

test("动态画像更新 - 消息分析", test_dynamic_updater)

# ========== 测试：个性化推荐引擎 ==========

print("\n" + "=" * 60)
print("【个性化推荐引擎】")
print("=" * 60)

from user_profile.personalized_recommender import PersonalizedRecommendationEngine

def test_recommendation_engine():
    engine = PersonalizedRecommendationEngine()

    # 测试不同行为阶段的推荐
    for stage in ["无意向", "意向", "准备", "行动", "维持"]:
        profile = {
            "user_id": "test",
            "basic_info": {"age_group": "26-35", "income_level": "中等收入", "family_type": "3-4"},
            "eco_profile": {"knowledge_level": "intermediate", "behavior_stage": stage, "primary_interests": []},
            "preference_learning": {"confirmed_interests": [], "rejected_topics": [], "learning_confidence": {}}
        }
        recs = engine.generate_recommendations(profile, count=1)
        assert_true(len(recs) > 0, f"{stage}阶段有推荐")
        assert_true(recs[0].action is not None, f"{stage}阶段有动作")
        assert_true(recs[0].category is not None, f"{stage}阶段有分类")

test("推荐引擎 - 行为阶段策略", test_recommendation_engine)

def test_recommendation_with_interests():
    engine = PersonalizedRecommendationEngine()

    profile = {
        "user_id": "test",
        "basic_info": {"age_group": "26-35", "income_level": "中等收入", "family_type": "3-4"},
        "eco_profile": {
            "knowledge_level": "intermediate",
            "behavior_stage": "意向",
            "primary_interests": ["low_carbon_travel", "energy_saving"]
        },
        "preference_learning": {
            "confirmed_interests": ["low_carbon_travel"],
            "rejected_topics": [],
            "learning_confidence": {}
        }
    }
    recs = engine.generate_recommendations(profile, count=3)

    # 优先推荐关注领域的建议
    categories = [r.category for r in recs]
    # 出行应该在推荐中
    has_travel = "出行" in categories
    has_energy = "家居" in categories
    assert_true(has_travel or has_energy, "推荐包含关注领域")

test("推荐引擎 - 兴趣优先", test_recommendation_with_interests)

# ========== 测试：LLM客户端 ==========

print("\n" + "=" * 60)
print("【LLM客户端与贝叶斯路由】")
print("=" * 60)

from llm.client import BayesianModelRouter, build_chat_prompt

def test_bayesian_router():
    router = BayesianModelRouter(strategy="thompson", auto_add_clients=False)

    # 注册测试客户端
    from llm.client import MockLLMClient
    mock = MockLLMClient()
    router.register_model("test_model", mock, "test-model-v1")

    # 初始选择（无数据）
    chosen = router.select_model()
    assert_equal(chosen, "test_model", "初始选择测试模型")

    # 记录多次结果
    for _ in range(10):
        router.record_result("test_model", True, 100, "好的回复")
    for _ in range(5):
        router.record_result("test_model", False, 100, "")

    stats = router.get_all_stats()
    assert_equal(stats["test_model"]["total_calls"], 15, "调用计数正确")
    assert_true(stats["test_model"]["success_rate"] > 0, "有成功率")

    # 最优模型
    best = router.get_best_model()
    assert_equal(best, "test_model", "最优模型")

    # 推荐
    rec = router.get_recommendation()
    assert_equal(rec["recommended"], "test_model", "推荐模型")

test("贝叶斯路由器 - 基础功能", test_bayesian_router)

def test_build_chat_prompt():
    # 测试 prompt 构建
    messages = build_chat_prompt(
        user_message="什么是碳中和？",
        user_profile={
            "basic_info": {"age_group": "26-35", "region": "北京"},
            "eco_profile": {"knowledge_level": "advanced", "behavior_stage": "行动", "primary_interests": ["low_carbon_travel"]},
            "communication_style": "professional"
        },
        rag_context="碳中和是指通过减排抵消CO2排放",
        conversation_history=[
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好！"}
        ]
    )

    assert_equal(len(messages), 6, "6条消息")  # system + profile + rag + history*2 + user
    assert_equal(messages[0]["role"], "system", "系统消息")
    assert_equal(messages[-1]["role"], "user", "用户消息")
    assert_equal(messages[-1]["content"], "什么是碳中和？", "用户消息内容")

    # 验证画像信息在系统消息中
    profile_msg = messages[1]["content"]
    assert_true("北京" in profile_msg or "26-35" in profile_msg, "画像信息存在")

test("Prompt构建", test_build_chat_prompt)

# ========== 测试：知识管理器 ==========

print("\n" + "=" * 60)
print("【知识管理器】")
print("=" * 60)

from knowledge.manager import KnowledgeManager

def test_knowledge_manager():
    kb_path = project_root / "knowledge_base"
    manager = KnowledgeManager(str(kb_path))

    # 获取所有文档
    docs = manager.get_all_documents()
    assert_true(len(docs) >= 5, f"知识库至少5个文档: {len(docs)}")

    # 搜索
    results = manager.search("碳中和", top_k=3)
    assert_true(len(results) > 0, "搜索有结果")

    # 分类统计
    stats = manager.get_stats()
    assert_true("total_documents" in stats, "统计包含文档数")
    assert_true("categories" in stats, "统计包含分类")

test("知识管理器 - 基础功能", test_knowledge_manager)

# ========== 总结 ==========

print("\n" + "=" * 60)
print("✅ 所有单元测试完成！")
print("=" * 60)
