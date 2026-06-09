"""
LangGraph 工作流定义
构建智能体状态图

P4-A:默认挂 SqliteSaver checkpointer,LangGraph 状态跨重启持久化
"""
import sys
from pathlib import Path
from typing import Literal, Optional

script_path = Path(__file__).resolve()
sys.path.insert(0, str(script_path.parent.parent.parent / 'src'))

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from .state import AgentState
from .nodes import (
    recognize_intent,
    retrieve_knowledge,
    get_user_profile,
    update_profile,
    generate_recommendations,
    generate_response,
    handle_error,
    get_nodes
)


_CHECKPOINTER = None
_CHECKPOINTER_CONN = None  # 必须保持长连接,SqliteSaver 依赖 conn


def _get_default_checkpointer():
    """默认 SqliteSaver(P4-A 引入),失败回退 MemorySaver

    注:SqliteSaver 接受一个 sqlite3.Connection 实例,需要在模块级保持引用
    """
    global _CHECKPOINTER, _CHECKPOINTER_CONN
    if _CHECKPOINTER is not None:
        return _CHECKPOINTER
    try:
        import sqlite3
        from langgraph.checkpoint.sqlite import SqliteSaver
        from paths import DATA_DIR
        ckpt_path = str(DATA_DIR / "langgraph_checkpoints.db")
        _CHECKPOINTER_CONN = sqlite3.connect(ckpt_path, check_same_thread=False)
        _CHECKPOINTER_CONN.execute("PRAGMA journal_mode=WAL")
        _CHECKPOINTER_CONN.execute("PRAGMA busy_timeout=5000")
        _CHECKPOINTER = SqliteSaver(_CHECKPOINTER_CONN)
        return _CHECKPOINTER
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            "[Graph] SqliteSaver 不可用,回退 MemorySaver: %s", e,
        )
        _CHECKPOINTER = MemorySaver()
        return _CHECKPOINTER


def create_agent_graph(checkpointer=None) -> StateGraph:
    """
    创建智能体工作流图

    Args:
        checkpointer: 检查点保存器(默认 SqliteSaver → MemorySaver)

    Returns:
        编译后的状态图
    """
    graph = StateGraph(AgentState)

    graph.add_node("recognize_intent", recognize_intent, name="意图识别")
    graph.add_node("get_user_profile", get_user_profile, name="获取画像")
    graph.add_node("retrieve_knowledge", retrieve_knowledge, name="知识检索")
    graph.add_node("update_profile", update_profile, name="更新画像")
    graph.add_node("generate_recommendations", generate_recommendations, name="生成推荐")
    graph.add_node("generate_response", generate_response, name="生成响应")
    graph.add_node("handle_error", handle_error, name="错误处理")

    graph.add_edge(START, "recognize_intent")

    graph.add_edge("recognize_intent", "get_user_profile")

    graph.add_conditional_edges(
        "get_user_profile",
        _route_after_profile,
        {
            "use_rag": "retrieve_knowledge",
            "update_profile": "update_profile",
            "skip": "generate_response"
        }
    )

    graph.add_conditional_edges(
        "retrieve_knowledge",
        _route_after_retrieval,
        {
            "update_profile": "update_profile",
            "skip": "generate_recommendations"
        }
    )

    graph.add_edge("update_profile", "generate_recommendations")

    graph.add_conditional_edges(
        "generate_recommendations",
        _route_after_recommendations,
        {
            "generate_response": "generate_response",
            "skip": "generate_response"
        }
    )

    graph.add_edge("generate_response", END)

    cp = checkpointer if checkpointer is not None else _get_default_checkpointer()
    return graph.compile(checkpointer=cp)


def _route_after_profile(state: AgentState) -> str:
    """获取画像后的路由决策"""
    intent_type = state.get("intent_type", "")

    if intent_type in ["knowledge_query", "advice_request"]:
        return "use_rag"
    elif intent_type in ["action_report", "feedback"]:
        return "update_profile"
    return "skip"


def _route_after_retrieval(state: AgentState) -> str:
    """知识检索后的路由决策"""
    rag_context = state.get("rag_context", "")
    intent_type = state.get("intent_type", "")

    if rag_context or intent_type == "knowledge_query":
        return "update_profile"
    return "skip"


def _route_after_recommendations(state: AgentState) -> str:
    """推荐生成后的路由决策"""
    recommendations = state.get("recommendations", [])
    intent_type = state.get("intent_type", "")

    if recommendations or intent_type in ["advice_request", "greeting"]:
        return "generate_response"
    return "skip"


_agent_graph = None

def get_agent_graph() -> StateGraph:
    """获取智能体图实例（单例）"""
    global _agent_graph
    if _agent_graph is None:
        _agent_graph = create_agent_graph()
    return _agent_graph


class ReActAgentGraph:
    """ReAct 模式的智能体图"""

    def __init__(self):
        self._graph = None

    def create_react_graph(self, checkpointer=None):
        """创建 ReAct 循环图"""
        graph = StateGraph(AgentState)

        graph.add_node("think", self._think_node, name="思考")
        graph.add_node("act", self._act_node, name="行动")
        graph.add_node("observe", self._observe_node, name="观察")
        graph.add_node("generate_final_response", self._final_response_node, name="最终响应")

        graph.add_edge(START, "think")
        graph.add_edge("think", "act")
        graph.add_edge("act", "observe")

        graph.add_conditional_edges(
            "observe",
            _check_continue_react,
            {
                "continue": "think",
                "finish": "generate_final_response"
            }
        )

        graph.add_edge("generate_final_response", END)

        compiled = graph.compile()

        if checkpointer is not None:
            return compiled.with_checkpointer(checkpointer)

        return compiled

    def _think_node(self, state: AgentState) -> AgentState:
        """思考节点: 分析当前状态，决定下一步行动"""
        nodes = get_nodes()
        metadata = state.get("metadata", {})
        # 递增 step_count 用于 ReAct 循环终止判断
        step_count = metadata.get("step_count", 0) + 1

        return {
            "metadata": {
                **metadata,
                "step": "think",
                "step_count": step_count,
                "thought": f"分析意图: {state.get('intent_type', 'unknown')}"
            }
        }

    def _act_node(self, state: AgentState) -> AgentState:
        """行动节点: 执行决定的动作"""
        intent_type = state.get("intent_type", "")
        metadata = state.get("metadata", {})
        step = metadata.get("step", "")

        nodes = get_nodes()

        if step == "think":
            if intent_type in ["knowledge_query", "advice_request"]:
                return nodes.retrieve_knowledge(state)
            elif intent_type in ["action_report", "feedback"]:
                return nodes.update_profile(state)
            elif intent_type == "advice_request":
                return nodes.generate_recommendations(state)

        return state

    def _observe_node(self, state: AgentState) -> AgentState:
        """观察节点: 获取行动结果"""
        return {
            "metadata": {
                **state.get("metadata", {}),
                "step": "observe",
                "observation": "动作执行完成"
            }
        }

    def _final_response_node(self, state: AgentState) -> AgentState:
        """最终响应节点"""
        nodes = get_nodes()
        return nodes.generate_response(state)


def _check_continue_react(state: AgentState) -> str:
    """检查是否继续 ReAct 循环"""
    metadata = state.get("metadata", {})
    step_count = metadata.get("step_count", 0)

    if step_count >= 3:
        return "finish"
    return "continue"


_react_graph = None

def get_react_graph() -> StateGraph:
    """获取 ReAct 图实例（单例）"""
    global _react_graph
    if _react_graph is None:
        react_agent = ReActAgentGraph()
        _react_graph = react_agent.create_react_graph()
    return _react_graph
