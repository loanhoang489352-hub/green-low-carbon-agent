"""
验证 P2 修复:response_mapper 统一映射

P2 之前:response.py 和 graph.py 各有重复的 type_mapping 字典。
P2 之后:统一在 response_mapper.py,通过 map_intent_to_response_type 调用。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agent.response_mapper import map_intent_to_response_type


EXPECTED = {
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


def test_string_intent():
    for intent, expected in EXPECTED.items():
        result = map_intent_to_response_type(intent)
        assert result == expected, f"{intent} -> {result}, expected {expected}"
    print(f"✅ test_string_intent PASSED ({len(EXPECTED)} cases)")


def test_unknown_string():
    assert map_intent_to_response_type("garbage") == "general"
    assert map_intent_to_response_type(None) == "general"
    print("✅ test_unknown_string PASSED")


def test_intenttype_enum():
    """支持 IntentType 枚举对象(.value)"""
    from agent.intent import IntentType
    for enum_val in IntentType:
        result = map_intent_to_response_type(enum_val)
        expected = EXPECTED.get(enum_val.value, "general")
        assert result == expected, f"{enum_val.name} -> {result}, expected {expected}"
    print(f"✅ test_intenttype_enum PASSED ({len(list(IntentType))} enum values)")


if __name__ == "__main__":
    test_string_intent()
    test_unknown_string()
    test_intenttype_enum()
    print("\n🎉 all response_mapper tests passed")
