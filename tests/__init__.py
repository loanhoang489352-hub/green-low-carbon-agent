"""
测试初始化脚本
用于快速验证智能体功能
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.agent.core import GreenAgent
from src.policy.updater import PolicyUpdater


def main():
    print("\n" + "=" * 60)
    print("🌱 绿色低碳智能体 - 初始化测试")
    print("=" * 60)
    
    # 初始化智能体
    print("\n[1/3] 初始化智能体...")
    agent = GreenAgent(
        knowledge_base_path=str(project_root / "knowledge_base")
    )
    print("   ✓ 智能体初始化完成")
    
    # 初始化政策更新器
    print("\n[2/3] 初始化政策更新器...")
    policy_updater = PolicyUpdater()
    policy_updater.add_sample_policies()
    print("   ✓ 政策数据加载完成")
    
    # 测试对话
    print("\n[3/3] 测试对话功能...")
    test_messages = [
        "你好",
        "什么是碳中和？",
        "我想买电动车，有什么建议吗？",
        "我每天开车上班，大概20公里"
    ]
    
    user_id = "demo_user"
    for msg in test_messages:
        print(f"\n   用户: {msg}")
        response = agent.chat(user_id, msg)
        print(f"   助手: {response.message[:100]}...")
        print(f"   意图: {response.intent}")
    
    # 打印知识库统计
    print("\n" + "=" * 60)
    print("📊 系统统计")
    print("=" * 60)
    
    kb_stats = agent.get_knowledge_stats()
    print(f"\n   知识库文档数: {kb_stats.get('total_documents', 0)}")
    print(f"   知识分类: {list(kb_stats.get('categories', {}).keys())}")
    
    policy_stats = policy_updater.get_stats()
    print(f"\n   政策条目数: {policy_stats.get('total_active_policies', 0)}")
    
    profile = agent.get_user_profile(user_id)
    print(f"\n   用户画像:")
    print(f"   - 环保认知: {profile.get('eco_knowledge_level')}")
    print(f"   - 行为阶段: {profile.get('behavior_stage')}")
    print(f"   - 对话轮次: {profile.get('conversation_count')}")
    
    print("\n" + "=" * 60)
    print("✅ 初始化测试完成！")
    print("=" * 60)
    print("\n启动Web服务: cd src && python main.py")
    print("启动CLI模式: cd src && python main.py --cli")
    print("\n")


if __name__ == "__main__":
    main()
