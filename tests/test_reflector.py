"""P16: Reflection 闭环单元测试(用 mock LLM,不依赖真实模型)"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agent.reflector import Reflector, reflect_and_revise


class MockLLM:
    def __init__(self, verdict="complete", revised="修订后的答案"):
        self.verdict = verdict
        self.revised = revised
        self.calls = []

    def chat(self, messages=None, **kw):
        self.calls.append(messages)
        # 反思调用 vs 修订调用:含"[自评]"的是修订调用
        text = ""
        if isinstance(messages, list):
            text = " ".join(str(m.get("content", "")) for m in messages if isinstance(m, dict))
        elif messages:
            text = str(messages)
        if "[自评]" in text:
            return _Resp(self.revised)
        return _Resp(json.dumps({
            "verdict": self.verdict,
            "critique": "工具失败却给了确定数字",
            "revision_hint": "改为说明数据不可用",
        }, ensure_ascii=False))


class _Resp:
    def __init__(self, content):
        self.content = content


def _tool_calls(failed=False):
    return [{
        "name": "travel_planning",
        "success": not failed,
        "output": {} if failed else {"routes": [{"type": "公交"}]},
    }]


def test_no_tool_calls_skips_reflection():
    r = Reflector(MockLLM())
    res = r.reflect("你好", "你好呀", [])
    assert res.verdict == "complete"
    assert res.needs_revision is False


def test_complete_verdict_no_revision():
    llm = MockLLM(verdict="complete")
    draft, verdict, revised = reflect_and_revise(
        llm, "从北京到国贸怎么走", "坐地铁1号线", _tool_calls(), messages=[]
    )
    assert verdict == "complete"
    assert revised is False
    assert draft == "坐地铁1号线"


def test_wrong_verdict_triggers_revision():
    llm = MockLLM(verdict="wrong", revised="数据暂时不可用,请稍后再试")
    draft, verdict, revised = reflect_and_revise(
        llm, "从北京到国贸怎么走", "骑共享单车 5 分钟", _tool_calls(failed=True), messages=[{"role": "user", "content": "q"}]
    )
    assert verdict == "wrong"
    assert revised is True
    assert draft == "数据暂时不可用,请稍后再试"


def test_incomplete_verdict_triggers_revision():
    llm = MockLLM(verdict="incomplete", revised="已补充:缺少费用对比")
    _, verdict, revised = reflect_and_revise(
        llm, "q", "draft", _tool_calls(), messages=[{"role": "user", "content": "q"}]
    )
    assert verdict == "incomplete"
    assert revised is True


def test_revision_failure_falls_back_to_draft():
    # 修订调用抛异常 → 回退原草稿,revised=False
    class BoomLLM(MockLLM):
        def chat(self, messages=None, **kw):
            text = ""
            if isinstance(messages, list):
                text = " ".join(str(m.get("content", "")) for m in messages if isinstance(m, dict))
            elif messages:
                text = str(messages)
            if "[自评]" in text:
                raise RuntimeError("boom")
            return _Resp(json.dumps({"verdict": "wrong", "critique": "c", "revision_hint": "h"}))

    draft, verdict, revised = reflect_and_revise(
        BoomLLM(verdict="wrong"), "q", "原草稿", _tool_calls(failed=True), messages=[{"role": "user", "content": "q"}]
    )
    assert verdict == "wrong"
    assert revised is False
    assert draft == "原草稿"


def test_reflector_without_llm_returns_complete():
    r = Reflector(None)
    res = r.reflect("q", "draft", _tool_calls())
    assert res.verdict == "complete"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"✅ {name} PASSED")
    print("\n🎉 All reflector tests PASSED")
