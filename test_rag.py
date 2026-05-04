# UTF-8编码设置
import sys
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import os
from pathlib import Path

# 设置工作目录
script_path = Path(__file__).resolve()
project_root = script_path.parent
os.chdir(str(project_root))

print("=" * 60)
print("绿色低碳智能体 - 测试脚本")
print("=" * 60)

# 导入
from src.agent.core import GreenAgent

print("\n[1] 初始化 GreenAgent...")
agent = GreenAgent(
    knowledge_base_path='d:/绿色低碳智能体/knowledge_base',
    enable_rag=True
)

print(f"\n[2] RAG状态检查:")
print(f'   RAG启用: {agent.rag_enabled}')
if agent.rag_enabled and agent.rag_engine:
    stats = agent.rag_engine.get_stats()
    print(f'   RAG统计: {stats}')
else:
    print(f'   RAG统计: N/A')

# 测试注册
print("\n[3] 测试用户注册...")
user_info = {
    'age': '30',
    'gender': 'male',
    'region': '华东',
    'interests': ['低碳出行', '节能减排']
}
user_id = agent.register_user(user_info)
print(f'   注册成功: {user_id}')

# 测试增强版聊天
print("\n[4] 测试增强版聊天...")
try:
    response = agent.chat_enhanced(user_id, '什么是碳中和？')
    print(f'   回复: {response.message[:100]}...')
    print(f'   个性化信息: {response.personalization_info}')
    print(f'   知识引用: {response.knowledge_refs}')
    print(f'   RAG上下文: {"有" if response.rag_context else "无"}')
except Exception as e:
    print(f'   聊天失败: {e}')
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("测试完成!")
print("=" * 60)
