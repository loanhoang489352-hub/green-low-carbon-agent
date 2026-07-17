"""
LangGraph 状态类型定义
定义智能体工作流中的共享状态结构
"""

from typing import TypedDict, Annotated, List, Dict, Any, Optional
from dataclasses import dataclass
from langgraph.graph import add_messages
from enum import Enum


class IntentType(str, Enum):
    """意图类型枚举"""

    KNOWLEDGE_QUERY = "knowledge_query"
    ADVICE_REQUEST = "advice_request"
    ACTION_REPORT = "action_report"
    FEEDBACK = "feedback"
    GREETING = "greeting"
    OTHER = "other"


@dataclass
class Message:
    """消息结构"""

    role: str
    content: str
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content, "timestamp": self.timestamp}


class AgentState(TypedDict):
    """LangGraph 智能体状态"""

    user_id: str
    conversation_id: str
    turn_count: int

    message: str
    messages: Annotated[List[Dict[str, Any]], add_messages]

    intent: str
    intent_type: str
    intent_confidence: float

    rag_context: str
    rag_results: List[Dict[str, Any]]

    profile: Dict[str, Any]
    profile_updates: Dict[str, Any]

    response_message: str
    suggestions: List[str]
    recommendations: List[Dict[str, Any]]

    knowledge_refs: List[str]
    memory_hints: List[str]

    personalization_info: Dict[str, Any]
    error: Optional[str]

    metadata: Dict[str, Any]


def initial_state(user_id: str, conversation_id: str, message: str) -> AgentState:
    """创建初始状态"""
    from datetime import datetime

    return AgentState(
        user_id=user_id,
        conversation_id=conversation_id,
        turn_count=0,
        message=message,
        messages=[{"role": "user", "content": message, "timestamp": datetime.now().isoformat()}],
        intent="",
        intent_type=IntentType.OTHER.value,
        intent_confidence=0.0,
        rag_context="",
        rag_results=[],
        profile={},
        profile_updates={},
        response_message="",
        suggestions=[],
        recommendations=[],
        knowledge_refs=[],
        memory_hints=[],
        personalization_info={},
        error=None,
        metadata={},
    )
