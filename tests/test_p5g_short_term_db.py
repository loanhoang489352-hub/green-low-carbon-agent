"""
P5-G: STM SQLite 持久化测试

覆盖:
1. add_message 后,新建实例从同一 DB 读到消息
2. self.metadata 跨实例保持(公共属性,scheduler 依赖)
3. delete_conversation 同步删 DB
4. search_conversations 跨实例可用
5. 单例 get_short_term_memory() 共享 DB
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

import pytest


@pytest.fixture
def stm_instance(tmp_path, monkeypatch):
    """每个测试一个临时 DB,单例重置干净"""
    from paths import SHORT_TERM_DB
    db = tmp_path / "stm.db"
    monkeypatch.setattr("paths.SHORT_TERM_DB", db)
    monkeypatch.setattr("memory.short_term.SHORT_TERM_DB", db, raising=False)
    from memory.short_term import (
        ShortTermMemory,
        get_short_term_memory,
        reset_short_term_memory,
    )
    reset_short_term_memory()
    yield ShortTermMemory(db_path=str(db))
    reset_short_term_memory()


def test_messages_persist_across_instances(stm_instance, tmp_path):
    """add_message → 删实例 → 新建实例 → 消息仍在"""
    stm_instance.add_message("c1", "user", "你好")
    stm_instance.add_message("c1", "assistant", "你好,我是绿色低碳助手")

    from memory.short_term import ShortTermMemory
    s2 = ShortTermMemory(db_path=str(tmp_path / "stm.db"))
    history = s2.get_conversation_history("c1")
    assert len(history) == 2
    assert history[0]["content"] == "你好"
    assert history[1]["role"] == "assistant"


def test_metadata_dict_preserved(stm_instance):
    """self.metadata 公共属性正确,scheduler 读不报错"""
    stm_instance.add_message("c1", "user", "测试")
    assert "c1" in stm_instance.metadata
    assert stm_instance.metadata["c1"]["message_count"] == 1
    assert stm_instance.metadata["c1"].get("user_id") is None
    assert "last_activity" in stm_instance.metadata["c1"]
    assert "created_at" in stm_instance.metadata["c1"]


def test_delete_conversation_removes_from_db(stm_instance, tmp_path):
    """delete_conversation 后,DB 行被删,新实例读不到"""
    stm_instance.add_message("c1", "user", "A")
    stm_instance.add_message("c2", "user", "B")
    stm_instance.delete_conversation("c1")

    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "stm.db"))
    n1 = conn.execute(
        "SELECT COUNT(*) FROM conversations WHERE conversation_id='c1'"
    ).fetchone()[0]
    n2 = conn.execute(
        "SELECT COUNT(*) FROM conversation_meta WHERE conversation_id='c1'"
    ).fetchone()[0]
    conn.close()
    assert n1 == 0, "conversations 行未删"
    assert n2 == 0, "conversation_meta 行未删"

    # c2 仍在
    from memory.short_term import ShortTermMemory
    s2 = ShortTermMemory(db_path=str(tmp_path / "stm.db"))
    assert len(s2.get_conversation_history("c2")) == 1


def test_search_conversations_after_persist(stm_instance, tmp_path):
    """search_conversations(keyword=...) 跨实例可用"""
    stm_instance.add_message("c1", "user", "我想了解碳交易")
    stm_instance.add_message("c2", "user", "今天天气真好")

    from memory.short_term import ShortTermMemory
    s2 = ShortTermMemory(db_path=str(tmp_path / "stm.db"))
    results = s2.search_conversations(keyword="碳交易", limit=5)
    assert len(results) == 1
    assert results[0]["conversation_id"] == "c1"


def test_singleton_uses_persistent_db(monkeypatch, tmp_path):
    """get_short_term_memory() 多次调返回同一实例,数据落 DB"""
    from paths import SHORT_TERM_DB
    db = tmp_path / "singleton.db"
    monkeypatch.setattr("paths.SHORT_TERM_DB", db)
    from memory.short_term import get_short_term_memory, reset_short_term_memory
    reset_short_term_memory()
    s1 = get_short_term_memory()
    s1.add_message("c1", "user", "持久化测试")
    s2 = get_short_term_memory()
    assert s1 is s2
    assert len(s2.get_conversation_history("c1")) == 1
    reset_short_term_memory()


def test_max_conversation_length_cap(stm_instance):
    """超过 MAX_CONVERSATION_LENGTH 触发截断"""
    from memory.short_term import ShortTermMemory
    for i in range(ShortTermMemory.MAX_CONVERSATION_LENGTH + 10):
        stm_instance.add_message("c1", "user", f"msg-{i}")
    history = stm_instance.get_conversation_history("c1")
    assert len(history) == ShortTermMemory.MAX_CONVERSATION_LENGTH
    # 最新消息应是 msg-N+N-1
    assert history[-1]["content"].startswith("msg-")
