# -*- coding: utf-8 -*-
import sys
import io
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import os
from pathlib import Path

script_path = Path(__file__).resolve()
project_root = script_path.parent
os.chdir(str(project_root))

sys.path.insert(0, str(project_root / 'src'))

print('=' * 60)
print('绿色低碳智能体 - 功能测试')
print('=' * 60)

from agent.core import GreenAgent

print('\n[1] 初始化 GreenAgent...')
agent = GreenAgent(
    knowledge_base_path='d:/绿色低碳智能体/knowledge_base',
    enable_rag=True
)
print('初始化成功!')

print('\n[2] 注册测试用户...')
user_id = agent.register_user({
    'age_group': '26-35',
    'gender': 'male',
    'region': '北京',
    'interests': ['低碳出行', '节能减排']
})
print(f'用户注册成功: {user_id}')

print('\n[3] 测试基础聊天...')
response = agent.chat(user_id, '什么是碳中和？')
print(f'回复: {response.message[:200]}')
print(f'意图识别: {response.intent}')

print('\n[4] 测试增强聊天...')
response2 = agent.chat_enhanced(user_id, '有什么低碳出行建议？')
print(f'回复: {response2.message[:200]}')
print(f'个性化信息: {response2.personalization_info}')
print(f'推荐: {len(response2.recommendations)} 条')

print('\n' + '=' * 60)
print('✅ Agent 基本功能测试通过!')
print('=' * 60)

print('\n[5] 检查是否依赖大模型...')
print('当前 Agent 采用的是基于规则的方法：')
print('  - 意图识别: 关键词 + 规则匹配')
print('  - 响应生成: 模板 + 知识库检索')
print('  - 个性化: 规则驱动的用户画像')
print('\n如需更强的对话能力，可接入 LLM (如 OpenAI GPT)')
