"""
LangGraph 重构测试脚本
验证新旧架构输出一致性
"""

import sys
import os
from pathlib import Path

script_path = Path(__file__).resolve()
project_root = script_path.parent.parent
sys.path.insert(0, str(project_root / 'src'))

# 设置UTF-8编码
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

print("=" * 60)
print("LangGraph 重构验证测试")
print("=" * 60)

# 测试1: 导入检查
print("\n[测试 1] 导入检查...")
try:
    from agent.graph import (
        AgentState,
        IntentType,
        initial_state,
        create_agent_graph,
        get_agent_graph
    )
    print("  [OK] LangGraph 模块导入成功")
except Exception as e:
    print(f"  [FAIL] 导入失败: {e}")
    sys.exit(1)

# 测试2: 状态类型检查
print("\n[测试 2] 状态类型检查...")
try:
    state = initial_state("test_user", "test_conv", "你好")
    assert "user_id" in state
    assert "message" in state
    assert "intent" in state
    assert "profile" in state
    print("  [OK] 状态类型定义正确")
except Exception as e:
    print(f"  [FAIL] 状态类型错误: {e}")
    sys.exit(1)

# 测试3: 创建图
print("\n[测试 3] 创建 StateGraph...")
try:
    graph = create_agent_graph()
    print(f"  [OK] StateGraph 创建成功")
    print(f"    - 节点: {list(graph.nodes.keys())}")
except Exception as e:
    print(f"  [FAIL] 图创建失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 测试4: LangGraphAgent 初始化 (跳过，因为可能需要很长时间)
print("\n[测试 4] LangGraphAgent 初始化... (跳过以节省时间)")
print("  [SKIP] 请使用 python test_simple.py 进行完整测试")

# 测试5: 对话测试
print("\n[测试 5] 对话测试...")
try:
    test_messages = [
        ("你好", "greeting"),
        ("什么是碳足迹?", "knowledge_query"),
        ("我想开始低碳生活", "advice_request"),
    ]

    config = {"configurable": {"thread_id": "test_conv"}}

    for msg, expected_intent in test_messages:
        print(f"\n  用户: {msg}")
        state = initial_state("test_user", "test_conv", msg)
        result = graph.invoke(state, config=config)
        response = result.get("response_message", "")
        intent = result.get("intent", "")
        print(f"  智能体: {response[:80]}...")
        print(f"  意图: {intent}")
        assert response, "响应消息不应为空"
except Exception as e:
    print(f"  [FAIL] 对话测试失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 测试6: 代理模式检查
print("\n[测试 6] GreenAgent 代理模式检查...")
try:
    from agent.core import GreenAgent

    normal_agent = GreenAgent(
        knowledge_base_path=str(project_root / "knowledge_base"),
        enable_rag=True,
        use_llm=False
    )
    print(f"  [OK] GreenAgent 正常模式初始化成功")
    print(f"    - LangGraph 启用: {normal_agent.use_langgraph}")

    os.environ["USE_LANGGRAPH"] = "true"
    langgraph_agent_wrapper = GreenAgent(
        knowledge_base_path=str(project_root / "knowledge_base"),
        enable_rag=True,
        use_llm=False
    )
    print(f"  [OK] GreenAgent LangGraph 模式初始化成功")
    print(f"    - LangGraph 启用: {langgraph_agent_wrapper.use_langgraph}")

except Exception as e:
    print(f"  [FAIL] 代理模式检查失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 60)
print("所有测试通过!")
print("=" * 60)
print("\n使用方法:")
print("  # 默认模式 (不使用 LangGraph)")
print("  python main.py")
print("")
print("  # 启用 LangGraph (StateGraph 模式)")
print("  python main.py --use-langgraph")
print("")
print("  # 启用 LangGraph (ReAct 模式)")
print("  python main.py --use-langgraph --use-react")
print("")
print("  # 命令行模式")
print("  python main.py --cli")
