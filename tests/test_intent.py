"""
意图识别模块测试
"""

import pytest
from agent.intent import IntentRecognizer, IntentType


class TestIntentRecognizer:
    """意图识别器测试"""

    @pytest.fixture
    def recognizer(self):
        return IntentRecognizer()

    def test_knowledge_query(self, recognizer):
        """知识问答意图识别"""
        result = recognizer.recognize("什么是碳排放?")
        assert result.intent == IntentType.KNOWLEDGE_QUERY

    def test_advice_request(self, recognizer):
        """建议请求意图识别"""
        result = recognizer.recognize("有什么低碳出行建议吗?")
        assert result.intent == IntentType.ADVICE_REQUEST

    def test_action_report(self, recognizer):
        """行动报告意图识别"""
        result = recognizer.recognize("我今天骑自行车上班了")
        assert result.intent == IntentType.ACTION_REPORT

    def test_greeting(self, recognizer):
        """问候意图识别"""
        result = recognizer.recognize("你好")
        assert result.intent == IntentType.GREETING

    def test_feedback(self, recognizer):
        """反馈意图识别"""
        result = recognizer.recognize("这个回答很好")
        assert result.intent == IntentType.FEEDBACK

    def test_unknown_intent(self, recognizer):
        """未知意图"""
        result = recognizer.recognize("asdfghjkl")
        assert result.intent == IntentType.OTHER
