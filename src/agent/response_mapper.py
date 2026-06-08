"""
意图 → 响应类型 映射
core.py 和 graph.py 共用,避免重复定义
"""

INTENT_TO_RESPONSE_TYPE = {
    "knowledge_query": "knowledge",
    "advice_request": "advice",
    "action_report": "encouragement",
    "feedback": "acknowledgment",
    "greeting": "greeting",
    "suggestion_accept": "positive",
    "suggestion_reject": "alternative",
    "question": "knowledge",
    "unknown": "clarification",
}

DEFAULT_RESPONSE_TYPE = "general"


def map_intent_to_response_type(intent) -> str:
    """将 IntentType/字符串映射到响应类型,失败时返回 general"""
    if intent is None:
        return DEFAULT_RESPONSE_TYPE
    if isinstance(intent, str):
        return INTENT_TO_RESPONSE_TYPE.get(intent, DEFAULT_RESPONSE_TYPE)
    value = getattr(intent, "value", None)
    if isinstance(value, str):
        return INTENT_TO_RESPONSE_TYPE.get(value, DEFAULT_RESPONSE_TYPE)
    return DEFAULT_RESPONSE_TYPE
