"""
绿色低碳智能体 - 测试脚本
验证各模块功能
"""

import sys
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import unittest
from src.agent.intent import IntentRecognizer, IntentType
from src.agent.response import ResponseGenerator, ResponseContext
from src.knowledge.manager import KnowledgeManager
from src.memory.short_term import ShortTermMemory
from src.memory.long_term import LongTermMemory
from src.profile.user_profile import UserProfileManager
from src.policy.updater import PolicyUpdater


class TestIntentRecognizer(unittest.TestCase):
    """测试意图识别"""
    
    def setUp(self):
        self.recognizer = IntentRecognizer()
    
    def test_knowledge_query(self):
        """测试知识查询意图"""
        result = self.recognizer.recognize("什么是碳中和？")
        self.assertIn(result.intent, [IntentType.KNOWLEDGE_QUERY, IntentType.QUESTION])
    
    def test_advice_request(self):
        """测试建议请求意图"""
        result = self.recognizer.recognize("有什么低碳建议吗？")
        self.assertIn(result.intent, [IntentType.ADVICE_REQUEST, IntentType.QUESTION])
    
    def test_action_report(self):
        """测试行动报告意图"""
        result = self.recognizer.recognize("我今天骑行了5公里")
        self.assertEqual(result.intent, IntentType.ACTION_REPORT)
    
    def test_greeting(self):
        """测试问候意图"""
        result = self.recognizer.recognize("你好")
        self.assertEqual(result.intent, IntentType.GREETING)
    
    def test_entity_extraction(self):
        """测试实体提取"""
        result = self.recognizer.recognize("我想买电动车")
        self.assertTrue(len(result.entities) > 0)


class TestKnowledgeManager(unittest.TestCase):
    """测试知识库管理"""
    
    def setUp(self):
        self.knowledge_base_path = project_root / "knowledge_base"
        self.km = KnowledgeManager(str(self.knowledge_base_path))
    
    def test_load_documents(self):
        """测试文档加载"""
        docs = self.km.get_all_documents()
        self.assertGreater(len(docs), 0, "应该加载了至少一个文档")
    
    def test_search(self):
        """测试搜索功能"""
        results = self.km.search("碳中和", top_k=5)
        self.assertGreaterEqual(len(results), 0)
    
    def test_get_categories(self):
        """测试获取分类"""
        categories = self.km.get_categories()
        self.assertIn("basic", categories)


class TestShortTermMemory(unittest.TestCase):
    """测试短期记忆"""
    
    def setUp(self):
        self.stm = ShortTermMemory()
    
    def test_add_message(self):
        """测试添加消息"""
        result = self.stm.add_message(
            conversation_id="test_conv",
            role="user",
            content="你好"
        )
        self.assertTrue(result)
    
    def test_get_conversation_history(self):
        """测试获取对话历史"""
        conv_id = "test_conv_2"
        self.stm.add_message(conv_id, "user", "你好")
        self.stm.add_message(conv_id, "assistant", "你好，我是助手")
        
        history = self.stm.get_conversation_history(conv_id)
        self.assertEqual(len(history), 2)
    
    def test_working_memory(self):
        """测试工作记忆"""
        conv_id = "test_conv_3"
        for i in range(10):
            self.stm.add_message(conv_id, "user", f"消息 {i}")
        
        working = self.stm.get_working_memory(conv_id)
        self.assertLessEqual(len(working), 20)  # 应该是最近的消息


class TestLongTermMemory(unittest.TestCase):
    """测试长期记忆"""
    
    def setUp(self):
        self.ltm = LongTermMemory(db_path=str(project_root / "data" / "test_ltm.db"))
    
    def test_add_memory(self):
        """测试添加记忆"""
        memory_id = self.ltm.add_memory(
            user_id="test_user",
            content="用户关注电动车",
            memory_type="interest",
            importance=0.8
        )
        self.assertIsNotNone(memory_id)
    
    def test_get_recent_memories(self):
        """测试获取最近记忆"""
        user_id = "test_user_2"
        self.ltm.add_memory(user_id, "记忆1", "general")
        self.ltm.add_memory(user_id, "记忆2", "interest")
        
        memories = self.ltm.get_recent_memories(user_id, limit=10)
        self.assertGreaterEqual(len(memories), 2)
    
    def test_update_preference(self):
        """测试更新偏好"""
        self.ltm.update_preference(
            user_id="test_user_3",
            preference_type="communication_style",
            value="通俗",
            confidence=0.9
        )
        
        prefs = self.ltm.get_preferences("test_user_3")
        self.assertIn("communication_style", prefs)


class TestUserProfile(unittest.TestCase):
    """测试用户画像"""
    
    def setUp(self):
        self.profile_manager = UserProfileManager(
            db_path=str(project_root / "data" / "test_profile.db")
        )
    
    def test_get_profile(self):
        """测试获取画像"""
        profile = self.profile_manager.get_profile("new_user")
        self.assertIsNotNone(profile)
        self.assertEqual(profile["user_id"], "new_user")
    
    def test_update_profile(self):
        """测试更新画像"""
        user_id = "test_user_profile"
        self.profile_manager.update_profile(user_id, {
            "eco_knowledge_level": "了解",
            "behavior_stage": "行动"
        })
        
        profile = self.profile_manager.get_profile(user_id)
        self.assertEqual(profile["eco_knowledge_level"], "了解")
    
    def test_increment_stat(self):
        """测试增加统计"""
        user_id = "test_user_stat"
        self.profile_manager.increment_stat(user_id, "questions_asked")
        self.profile_manager.increment_stat(user_id, "questions_asked")
        
        profile = self.profile_manager.get_profile(user_id)
        self.assertEqual(profile["questions_asked"], 2)


class TestPolicyUpdater(unittest.TestCase):
    """测试政策更新器"""
    
    def setUp(self):
        self.policy_updater = PolicyUpdater(
            db_path=str(project_root / "data" / "test_policy.db")
        )
    
    def test_add_policy(self):
        """测试添加政策"""
        policy_id = self.policy_updater.add_policy(
            title="测试政策",
            content="这是一个测试政策",
            category="国家战略",
            source="测试来源"
        )
        self.assertIsNotNone(policy_id)
    
    def test_get_policies(self):
        """测试获取政策列表"""
        policies = self.policy_updater.get_policies(limit=10)
        self.assertIsInstance(policies, list)
    
    def test_add_sample_policies(self):
        """测试添加示例政策"""
        initial_count = len(self.policy_updater.get_policies())
        self.policy_updater.add_sample_policies()
        new_count = len(self.policy_updater.get_policies())
        self.assertGreater(new_count, initial_count)


class TestIntegration(unittest.TestCase):
    """集成测试"""
    
    def setUp(self):
        from src.agent.core import GreenAgent
        
        self.agent = GreenAgent(
            knowledge_base_path=str(project_root / "knowledge_base")
        )
    
    def test_chat(self):
        """测试完整对话流程"""
        response = self.agent.chat(
            user_id="test_user_integration",
            message="什么是碳中和？"
        )
        
        self.assertIsNotNone(response.message)
        self.assertIsNotNone(response.conversation_id)
        self.assertIsNotNone(response.intent)
    
    def test_conversation_context(self):
        """测试对话上下文"""
        user_id = "test_user_context"
        
        # 第一轮对话
        response1 = self.agent.chat(user_id, "你好")
        self.assertIsNotNone(response1.conversation_id)
        
        # 第二轮对话，使用相同的conversation_id
        response2 = self.agent.chat(
            user_id,
            "我想了解低碳出行",
            conversation_id=response1.conversation_id
        )
        
        self.assertEqual(response1.conversation_id, response2.conversation_id)
    
    def test_user_profile_update(self):
        """测试用户画像更新"""
        user_id = "test_user_profile_update"
        
        self.agent.chat(user_id, "我想买电动车")
        self.agent.chat(user_id, "我今天骑行了10公里")
        
        profile = self.agent.get_user_profile(user_id)
        self.assertGreater(profile["conversation_count"], 0)


def run_tests():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("🧪 运行绿色低碳智能体测试套件")
    print("=" * 60 + "\n")
    
    # 创建测试套件
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # 添加测试类
    suite.addTests(loader.loadTestsFromTestCase(TestIntentRecognizer))
    suite.addTests(loader.loadTestsFromTestCase(TestKnowledgeManager))
    suite.addTests(loader.loadTestsFromTestCase(TestShortTermMemory))
    suite.addTests(loader.loadTestsFromTestCase(TestLongTermMemory))
    suite.addTests(loader.loadTestsFromTestCase(TestUserProfile))
    suite.addTests(loader.loadTestsFromTestCase(TestPolicyUpdater))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegration))
    
    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # 打印结果摘要
    print("\n" + "=" * 60)
    if result.wasSuccessful():
        print("✅ 所有测试通过！")
    else:
        print("❌ 部分测试失败")
    print("=" * 60 + "\n")
    
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
