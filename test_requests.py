# -*- coding: utf-8 -*-
import json
import requests

# 测试注册
print("测试 /api/user/register:")
r = requests.post('http://localhost:8000/api/user/register', json={'user_info': {'age_group': '25-35'}})
print(f"状态: {r.status_code}")
try:
    data = r.json()
    print(f"响应: user_id={data.get('user_id')}, status={data.get('status')}")
except:
    print(f"响应: {r.text[:200]}")

print()

# 测试聊天
print("测试 /api/chat:")
r = requests.post('http://localhost:8000/api/chat', json={'user_id': 'test', 'message': 'hello'})
print(f"状态: {r.status_code}")
print(f"响应: 成功" if r.status_code == 200 else f"响应: {r.text[:100]}")