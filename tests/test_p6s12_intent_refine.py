"""
P6.S.12 测试: 修 P6.S.3 出行规划过激 + 建议请求补强

P6.S.3 加的 TRAVEL_PLANNING 关键词过广("去/到/出发/碳排放/公司/家"都触发),
误伤 advice_request / knowledge_query / action_report 路径。
P6.S.12 拆为 STRONG_TRAVEL(单命中)/WEAK_TRAVEL(需 ≥2)/删除通用词。

验证:
1. STRONG_TRAVEL 单命中即覆盖
2. WEAK_TRAVEL 需 ≥2 才覆盖
3. 通用词("碳排放"/"公司"/"家")不再单触发
4. advice_request 显式信号("建议/推荐/有什么好/怎么办"等)优先
5. knowledge_query 移除"什么"(过泛)
6. 兴趣表达("感兴趣")归 knowledge_query
"""
import sys
sys.path.insert(0, str(__file__.replace("\\", "/").replace("tests/test_p6s12_intent_refine.py", "src")))


def test_strong_travel_single_hit_overrides():
    """STRONG_TRAVEL 单命中应识别为 travel_planning"""
    from agent.intent import IntentRecognizer

    ir = IntentRecognizer()
    for q in [
        "怎么去机场",
        "从北京到上海怎么走",
        "查一下公交路线",
        "出行规划",
    ]:
        r = ir.recognize(q)
        assert r.intent.value == "travel_planning", f"{q!r} -> {r.intent.value} (期望 travel_planning)"


def test_weak_travel_requires_two_hits():
    """WEAK_TRAVEL 单命中不应覆盖(避免"碳排放"误伤)"""
    from agent.intent import IntentRecognizer

    ir = IntentRecognizer()
    for q in [
        "我应该怎么减少碳排放",  # 含"碳排放", 1 weak
        "今天去办事",            # 含"去"(已删),可能 0 weak
    ]:
        r = ir.recognize(q)
        assert r.intent.value != "travel_planning", f"{q!r} 不应被误识为 travel, 实际 {r.intent.value}"


def test_weak_travel_two_hits_overrides():
    """WEAK_TRAVEL ≥2 命中应识别为 travel"""
    from agent.intent import IntentRecognizer

    ir = IntentRecognizer()
    for q in [
        "从家到公司",         # 从 + 到 = 2 weak
        "查一下北京到天津的路线",  # 到 + 路线 = 2 weak
    ]:
        r = ir.recognize(q)
        assert r.intent.value == "travel_planning", f"{q!r} -> {r.intent.value} (期望 travel_planning)"


def test_advice_request_explicit_signals():
    """'建议/推荐/有什么好/怎么办' 显式信号应优先 advice_request"""
    from agent.intent import IntentRecognizer

    ir = IntentRecognizer()
    for q in [
        "有什么低碳出行建议吗",
        "请给我推荐一些方法",
        "我想买电动车, 有什么好推荐的",
    ]:
        r = ir.recognize(q)
        assert r.intent.value == "advice_request", f"{q!r} -> {r.intent.value} (期望 advice_request)"


def test_interest_expression_known_as_knowledge():
    """'感兴趣/想了解/想知道/想学习' 应归 knowledge_query"""
    from agent.intent import IntentRecognizer

    ir = IntentRecognizer()
    for q in [
        "我对垃圾分类很感兴趣",
        "我想了解碳中和",
    ]:
        r = ir.recognize(q)
        assert r.intent.value == "knowledge_query", f"{q!r} -> {r.intent.value} (期望 knowledge_query)"


def test_action_report_still_works():
    """'我今天...' 行动报告仍可识别"""
    from agent.intent import IntentRecognizer

    ir = IntentRecognizer()
    for q in [
        "我今天骑自行车上班了",
        "我今天骑自行车上班了, 大概3公里",
    ]:
        r = ir.recognize(q)
        assert r.intent.value == "action_report", f"{q!r} -> {r.intent.value} (期望 action_report)"


def test_generic_words_dont_overclassify():
    """通用词'碳排放/碳排/公司/家'单独出现不应触发 travel"""
    from agent.intent import IntentRecognizer

    ir = IntentRecognizer()
    for q in [
        "我想知道什么是碳排放",  # 含"碳排放", 1 weak(已删) → 0 weak
        "今天公司的空调很费电",   # "公司"是常用位置词,不应触发 travel
    ]:
        r = ir.recognize(q)
        assert r.intent.value != "travel_planning", f"{q!r} 不应被误识为 travel, 实际 {r.intent.value}"


def test_greeting_still_greeting():
    """寒暄仍识别为 greeting"""
    from agent.intent import IntentRecognizer

    ir = IntentRecognizer()
    for q in ["你好", "嗨", "hi", "hello"]:
        r = ir.recognize(q)
        assert r.intent.value == "greeting", f"{q!r} -> {r.intent.value} (期望 greeting)"


def test_knowledge_query_still_works():
    """知识查询仍识别为 knowledge_query"""
    from agent.intent import IntentRecognizer

    ir = IntentRecognizer()
    for q in [
        "什么是碳中和",
        "碳达峰是什么意思",
        "北京有哪些低碳生活政策?",
        "我想了解碳中和",
    ]:
        r = ir.recognize(q)
        assert r.intent.value == "knowledge_query", f"{q!r} -> {r.intent.value} (期望 knowledge_query)"


def test_strong_travel_and_weak_travel_lists_exist():
    """P6.S.12: STRONG_TRAVEL / WEAK_TRAVEL 列表应存在"""
    from agent.intent import IntentRecognizer

    ir = IntentRecognizer()
    assert hasattr(ir, "STRONG_TRAVEL"), "IntentRecognizer 应有 STRONG_TRAVEL 列表"
    assert hasattr(ir, "WEAK_TRAVEL"), "IntentRecognizer 应有 WEAK_TRAVEL 列表"
    assert "怎么去" in ir.STRONG_TRAVEL, "STRONG_TRAVEL 应含 '怎么去'"
    assert "碳排放" not in ir.WEAK_TRAVEL, "WEAK_TRAVEL 不应含 '碳排放'(太泛)"
    assert "公司" not in ir.WEAK_TRAVEL, "WEAK_TRAVEL 不应含 '公司'(通用位置词)"
    assert "家" not in ir.WEAK_TRAVEL, "WEAK_TRAVEL 不应含 '家'(通用位置词)"


if __name__ == "__main__":
    test_strong_travel_single_hit_overrides()
    test_weak_travel_requires_two_hits()
    test_weak_travel_two_hits_overrides()
    test_advice_request_explicit_signals()
    test_interest_expression_known_as_knowledge()
    test_action_report_still_works()
    test_generic_words_dont_overclassify()
    test_greeting_still_greeting()
    test_knowledge_query_still_works()
    test_strong_travel_and_weak_travel_lists_exist()
    print("\n🎉 All P6.S.12 tests PASSED")
