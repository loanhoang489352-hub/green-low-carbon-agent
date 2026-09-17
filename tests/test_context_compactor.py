"""P16: Context 压缩 + token 预算单元测试"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agent.context_compactor import (
    estimate_tokens,
    ContextBudget,
    compact_history,
    compact_rag,
)


def _msgs(n, chars=40):
    return [{"role": "user" if i % 2 == 0 else "assistant", "content": "测" * chars} for i in range(n)]


def test_estimate_tokens_cjk_heavy():
    # 全中文:每字约 1 token
    assert estimate_tokens("你好世界") == 5  # 4 字 + 1
    # 英文:每 4 字符约 1 token
    assert estimate_tokens("hello") == 2  # 5 字符 // 4 + 1


def test_budget_sums():
    b = ContextBudget()
    assert b.allocated == b.history + b.rag + b.profile + b.tools + b.system
    assert b.allocated + b.reserve <= b.total


def test_compact_short_history_keeps_all():
    h = _msgs(4)
    c = compact_history(h, budget_tokens=10000)
    assert len(c.kept) == 4
    assert c.dropped_turns == 0
    assert c.needs_summary is False


def test_compact_long_history_drops_oldest_and_marks_summary():
    # 40 字符/条 → 每条约 44 token(40 CJK + 4 开销)
    h = _msgs(100, chars=40)
    c = compact_history(h, budget_tokens=500, keep_last_n=6)
    # 保留了最近 6 条(keep_last_n),头部填到预算满,其余折叠
    assert len(c.kept) >= 6
    assert len(c.kept) < 100
    assert c.dropped_turns == 100 - len(c.kept)
    assert c.needs_summary is True
    # 保留的都是最新的(顺序不变)
    assert c.kept[-1] == h[-1]
    # token 不超预算
    assert c.tokens() <= 500 + estimate_tokens("") + 10


def test_compact_with_existing_summary_no_needs_summary():
    h = _msgs(50, chars=40)
    c = compact_history(h, budget_tokens=300, summary="之前的对话在讨论家庭节能。")
    assert c.needs_summary is False
    assert "家庭节能" in c.summary


def test_compact_tail_exceeds_budget_still_keeps_recent():
    # 单条很长,预算很小:仍只保留最近能塞下的
    h = [{"role": "user", "content": "长" * 500}] * 10
    c = compact_history(h, budget_tokens=100, keep_last_n=6)
    assert len(c.kept) >= 1
    assert c.dropped_turns > 0


def test_compact_empty_history():
    c = compact_history([], budget_tokens=1000)
    assert c.kept == []
    assert c.dropped_turns == 0
    assert c.needs_summary is False


def test_compact_rag_truncates_content():
    docs = [{"title": "t1", "content": "长" * 2000}, {"title": "t2", "content": "短"}]
    out = compact_rag(docs, budget_tokens=100, max_content_chars=500)
    assert len(out) >= 1
    # 单条 content 不超过 500 字符
    assert all(len(d["content"]) <= 500 for d in out)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"✅ {name} PASSED")
    print("\n🎉 All context compactor tests PASSED")
