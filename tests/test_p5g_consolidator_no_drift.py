"""
P5-G: 验证 scheduler 用 set_message_count 不会让 message_count 漂移

背景:
- 原 _consolidate_short_to_long() 用 update_message_count(cid, count=N)
- update_message_count 是累加(md.get("message_count", 0) + count)
- 持久 STM 后,scheduler 每小时重跑会把同一个 N 重复加,counter 无限增长
- P5-G 修复:改用 set_message_count(cid, N)(覆盖式)
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

import pytest


def test_set_message_count_is_overwrite():
    """set_message_count(cid, N) 应设置不累加"""
    from memory.consolidation import MemoryConsolidator, ThresholdStrategy
    c = MemoryConsolidator(strategy=ThresholdStrategy())
    c.set_message_count("c1", 10)
    c.set_message_count("c1", 10)
    c.set_message_count("c1", 10)
    stats = c.get_consolidation_stats("c1")
    assert stats["message_count"] == 10, \
        f"应保持 10,实际 {stats['message_count']}"


def test_set_message_count_clamps_negative_to_zero():
    """负数应夹紧到 0"""
    from memory.consolidation import MemoryConsolidator, ThresholdStrategy
    c = MemoryConsolidator(strategy=ThresholdStrategy())
    c.set_message_count("c1", -5)
    assert c.get_consolidation_stats("c1")["message_count"] == 0


def test_scheduler_loop_does_not_drift(tmp_path, monkeypatch):
    """模拟 5 轮 scheduler 跑,message_count 不应无限增长

    用 tmp_path 隔离 STM DB,避免与默认 data/short_term.db 串扰
    """
    db = tmp_path / "stm.db"
    monkeypatch.setattr("paths.SHORT_TERM_DB", db)
    monkeypatch.setattr("memory.short_term.SHORT_TERM_DB", db, raising=False)
    from memory.short_term import ShortTermMemory
    from memory.consolidation import MemoryConsolidator, ThresholdStrategy

    stm = ShortTermMemory(db_path=str(db))
    consolidator = MemoryConsolidator(strategy=ThresholdStrategy())

    # 加 5 条消息
    for i in range(5):
        stm.add_message("c1", "user", f"msg {i}")

    # 模拟 5 轮 scheduler 用 set_message_count 覆盖
    for _ in range(5):
        meta = stm.metadata["c1"]
        consolidator.set_message_count("c1", count=meta.get("message_count", 0))

    stats = consolidator.get_consolidation_stats("c1")
    assert stats["message_count"] == 5, \
        f"P5-G 修复后应保持 5,实际 {stats['message_count']}"


def test_update_message_count_still_adds_for_backward_compat():
    """update_message_count(累加)仍可用,core.py / nodes.py 还在用"""
    from memory.consolidation import MemoryConsolidator, ThresholdStrategy
    c = MemoryConsolidator(strategy=ThresholdStrategy())
    c.update_message_count("c1", count=3)
    c.update_message_count("c1", count=2)
    assert c.get_consolidation_stats("c1")["message_count"] == 5
