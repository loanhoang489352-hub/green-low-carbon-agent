"""P17: per-user LLM key 存储 + 解析单元测试"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest


@pytest.fixture
def key_db(tmp_path, monkeypatch):
    """把 user_keys 的 ACCOUNTS_DB 指到临时库,避免污染真实 accounts.db"""
    import llm.user_keys as uk

    db = tmp_path / "accounts_test.db"
    monkeypatch.setattr(uk, "ACCOUNTS_DB", db)
    monkeypatch.setattr(uk, "DATA_DIR", tmp_path)
    uk.reset_fernet()
    return uk, db


def test_save_and_get_roundtrip(key_db):
    uk, db = key_db
    uk.save_key("alice", "sk-test-123", "openai", "gpt-4o-mini")
    info = uk.get_key("alice")
    assert info is not None
    api_key, provider, model = info
    assert api_key == "sk-test-123"
    assert provider == "openai"
    assert model == "gpt-4o-mini"


def test_get_key_unknown_user_returns_none(key_db):
    uk, db = key_db
    assert uk.get_key("nobody") is None
    assert uk.has_key("nobody") is False


def test_key_stored_encrypted_not_plaintext(key_db):
    uk, db = key_db
    uk.save_key("bob", "sk-super-secret-key", "deepseek", None)
    raw = db.read_bytes()
    assert b"sk-super-secret-key" not in raw, "明文 key 不应出现在 DB 文件中"


def test_delete_key(key_db):
    uk, db = key_db
    uk.save_key("carol", "sk-abc", "openai", None)
    assert uk.has_key("carol")
    uk.delete_key("carol")
    assert not uk.has_key("carol")


def test_upsert_overwrites(key_db):
    uk, db = key_db
    uk.save_key("dave", "sk-old", "openai", None)
    uk.save_key("dave", "sk-new", "minimax", "abab6.5s")
    api_key, provider, _ = uk.get_key("dave")
    assert api_key == "sk-new"
    assert provider == "minimax"


def test_get_llm_client_returns_none_for_user_without_key(key_db, monkeypatch):
    """get_llm_client(user_id) 无 key → None(严格阻断,不 fallback owner)"""
    from llm.client import get_llm_client

    client = get_llm_client("user_without_key_xyz")
    assert client is None


def test_get_llm_client_resolves_user_key(key_db, monkeypatch):
    """有 key 的用户 → 返回用其 key 构造的客户端"""
    uk, db = key_db
    uk.save_key("alice", "sk-test-123", "openai", "gpt-4o-mini")
    monkeypatch.setattr("llm.client._user_llm_clients", {})
    from llm.client import get_llm_client, reset_user_llm_client

    reset_user_llm_client("alice")
    client = get_llm_client("alice")
    assert client is not None
    # 客户端持有的是用户自己的 key
    assert getattr(client, "api_key", None) == "sk-test-123"


if __name__ == "__main__":
    import tempfile
    from pathlib import Path as P
    import llm.user_keys as uk

    tmp = P(tempfile.mkdtemp())
    db = tmp / "accounts.db"
    uk.ACCOUNTS_DB = db
    uk.DATA_DIR = tmp
    uk.reset_fernet()
    test_save_and_get_roundtrip((uk, db))
    test_get_key_unknown_user_returns_none((uk, db))
    test_key_stored_encrypted_not_plaintext((uk, db))
    test_delete_key((uk, db))
    test_upsert_overwrites((uk, db))
    print("✅ user_llm_keys tests PASSED")
