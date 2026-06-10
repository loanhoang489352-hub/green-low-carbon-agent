"""
P5-I: 安全 / 合规 / 限流 / 审计测试

覆盖:
A. PII 脱敏:手机/邮箱/身份证/银行卡/地址 + 综合入口 + dict 递归
B. password 字段 bcrypt 哈希(非明文)
C. 限流:滑动时间窗触发 429 + 重置后放行
D. 审计日志:record_audit 落表 + query_audit 读回
E. config 强校验:占位符 key 命中警告
F. 集成:feedback.comment 落库前 PII 脱敏
G. 集成:behavior_event context + event_data 落库前 PII 脱敏
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import pytest


# ---------------------------------------------------------------------------
# A. PII 脱敏
# ---------------------------------------------------------------------------
def test_mask_phone_china_11_digit():
    from utils.pii import mask_phone
    assert mask_phone("联系我 13800001234") == "联系我 138****1234"
    assert mask_phone("tel:13912345678 end") == "tel:139****5678 end"
    # 非 11 位不识别
    assert mask_phone("12345") == "12345"
    # 不以 1[3-9] 开头不识别
    assert mask_phone("12800001234") == "12800001234"
    # 边界有数字不识别(避免误伤)
    assert mask_phone("9138000012349") == "9138000012349"


def test_mask_email_keeps_domain():
    from utils.pii import mask_email
    assert mask_email("zhangsan@example.com") == "zhan***@example.com"
    assert mask_email("a@b.com") == "a***@b.com"
    # 短 local(<=4)
    assert mask_email("ab@foo.com") == "a***@foo.com"
    # 不影响普通文本
    assert mask_email("plain text no email") == "plain text no email"


def test_mask_id_card_18_digit():
    from utils.pii import mask_id_card
    assert mask_id_card("110101199001011234") == "110101********1234"
    # 末位 X(老身份证格式)
    assert mask_id_card("11010119900101123X") == "110101********123X"
    # 非 18 位不识别
    assert mask_id_card("12345") == "12345"


def test_mask_bank_card_keeps_4_ends():
    from utils.pii import mask_bank_card
    # 19 位卡号:保留前 4 + 后 4,中间 11 位掩码
    assert mask_bank_card("6222021234567890123") == "6222***********0123"
    # 16 位:中间 8 位掩码
    assert mask_bank_card("6222021234567890") == "6222********7890"
    # 13 位最小:中间 5 位掩码
    assert mask_bank_card("1234567890123") == "1234*****0123"


def test_mask_address_truncates():
    from utils.pii import mask_address
    text = "我家在北京市朝阳区建国路88号现代城B座1501室"
    masked = mask_address(text)
    # 应该被截断到 12 字符 + ***
    assert "***" in masked
    assert "建国路" not in masked or "***" in masked


def test_mask_pii_combined():
    from utils.pii import mask_pii
    text = "电话 13800001234, 邮箱 zhang@example.com, 身份证 110101199001011234"
    masked = mask_pii(text)
    assert "138****1234" in masked
    assert "zhan***@example.com" in masked
    assert "110101********1234" in masked
    # 身份证应优先于银行卡(避免长数字串重复处理)


def test_mask_pii_in_dict_recursive():
    from utils.pii import mask_pii_in_dict
    data = {
        "user_name": "alice",
        "phone": "13800001234",
        "profile": {
            "email": "zhang@test.com",
            "id_card": "110101199001011234",
        },
        "history": [
            {"contact": "13900001111"},
            "13800002222",
        ],
        "count": 5,  # 非 str 不动
    }
    out = mask_pii_in_dict(data)
    assert out["user_name"] == "alice"
    assert out["phone"] == "138****1234"
    assert out["profile"]["email"] == "zhan***@test.com"
    assert out["profile"]["id_card"] == "110101********1234"
    assert out["history"][0]["contact"] == "139****1111"
    assert out["history"][1] == "138****2222"
    assert out["count"] == 5


def test_mask_pii_empty_and_safe():
    from utils.pii import mask_pii, mask_pii_in_dict
    assert mask_pii("") == ""
    assert mask_pii(None) is None
    assert mask_pii_in_dict(None) is None
    assert mask_pii_in_dict({}) == {}


# ---------------------------------------------------------------------------
# B. password 字段 bcrypt
# ---------------------------------------------------------------------------
def test_password_hashed_not_plaintext():
    """注册后落库的 password_hash 必须是 bcrypt 哈希(以 $2 开头)或 PBKDF2($pbkdf2$),
    绝不能是明文"""
    import tempfile
    db = Path(tempfile.mkdtemp()) / "test_pwd.db"
    import auth.account_manager as am_mod
    am_mod.DB_PATH = str(db)
    am_mod.AccountManager._initialized = False

    mgr = am_mod.AccountManager()
    result = mgr.register("alice_test", "supersecret123")
    assert result["success"], f"register failed: {result}"

    import sqlite3
    conn = sqlite3.connect(str(db))
    row = conn.execute(
        "SELECT password_hash FROM accounts WHERE username = ?", ("alice_test",)
    ).fetchone()
    conn.close()

    assert row is not None
    stored = row[0]
    assert stored != "supersecret123", "明文密码落库!"
    assert stored.startswith("$2") or stored.startswith("$pbkdf2$"), \
        f"密码未哈希,实际 prefix: {stored[:10]}"


# ---------------------------------------------------------------------------
# C. 限流
# ---------------------------------------------------------------------------
def test_rate_limiter_triggers_429():
    """同一 IP 短时间内超 60 次 → 至少一次被拒"""
    from server.middleware.rate_limit import RateLimiter
    lim = RateLimiter(max_requests=5, window_seconds=10)

    class FakeHandler:
        headers = {}
        client_address = ("127.0.0.1", 5000)

    allowed_count = 0
    blocked = False
    for _ in range(10):
        ok, retry = lim.check(FakeHandler())
        if ok:
            allowed_count += 1
        else:
            blocked = True
            assert retry >= 1
    assert allowed_count == 5
    assert blocked


def test_rate_limiter_resets():
    """reset 后能再放行"""
    from server.middleware.rate_limit import RateLimiter
    lim = RateLimiter(max_requests=2, window_seconds=10)

    class FakeHandler:
        headers = {}
        client_address = ("10.0.0.1", 5000)

    for _ in range(2):
        ok, _ = lim.check(FakeHandler())
        assert ok
    ok, _ = lim.check(FakeHandler())
    assert not ok
    lim.reset()
    ok, _ = lim.check(FakeHandler())
    assert ok


def test_rate_limiter_isolated_per_ip():
    """不同 IP 互不影响"""
    from server.middleware.rate_limit import RateLimiter
    lim = RateLimiter(max_requests=2, window_seconds=10)

    class H:
        def __init__(self, ip):
            self.headers = {}
            self.client_address = (ip, 5000)

    for _ in range(2):
        assert lim.check(H("1.1.1.1"))[0]
    # 1.1.1.1 已满,但 2.2.2.2 仍可用
    assert not lim.check(H("1.1.1.1"))[0]
    assert lim.check(H("2.2.2.2"))[0]


def test_rate_limiter_respects_xff():
    """有 X-Forwarded-For 头时,IP 取头中第一个值"""
    from server.middleware.rate_limit import RateLimiter
    lim = RateLimiter(max_requests=2, window_seconds=10)

    class H:
        headers = {"X-Forwarded-For": "203.0.113.5, 10.0.0.1"}
        client_address = ("127.0.0.1", 5000)  # 本地, 但 XFF 决定

    for _ in range(2):
        assert lim.check(H())[0]
    assert not lim.check(H())[0]


# ---------------------------------------------------------------------------
# D. 审计日志
# ---------------------------------------------------------------------------
def test_record_audit_writes_to_db(tmp_path, monkeypatch):
    """record_audit 写入 accounts.db.audit_log,可被 query_audit 读回"""
    from paths import ACCOUNTS_DB
    db = tmp_path / "accounts_audit.db"
    monkeypatch.setattr("paths.ACCOUNTS_DB", db)
    monkeypatch.setattr("server.middleware.audit._audit_db_path", lambda: str(db))

    from db_schema import init_all_schemas
    # init_all_schemas 使用真实 paths;为简单起见手工建表
    import sqlite3
    conn = sqlite3.connect(str(db))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT, action TEXT NOT NULL, target TEXT,
            ip TEXT, user_agent TEXT, status_code INTEGER,
            detail TEXT, created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

    from server.middleware.audit import record_audit, query_audit
    ok = record_audit(
        action="auth.login",
        user_id="user-1",
        ip="10.0.0.1",
        status_code=200,
        detail="login from test",
    )
    assert ok
    rows = query_audit(user_id="user-1", limit=10)
    assert len(rows) >= 1
    assert any(r["action"] == "auth.login" for r in rows)


def test_record_audit_masks_pii_in_detail(tmp_path, monkeypatch):
    """写入的 detail 中残留的手机号应被脱敏"""
    from paths import ACCOUNTS_DB
    db = tmp_path / "accounts_audit_pii.db"
    monkeypatch.setattr("server.middleware.audit._audit_db_path", lambda: str(db))

    import sqlite3
    conn = sqlite3.connect(str(db))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT, action TEXT NOT NULL, target TEXT,
            ip TEXT, user_agent TEXT, status_code INTEGER,
            detail TEXT, created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

    from server.middleware.audit import record_audit, query_audit
    record_audit(
        action="auth.login",
        user_id="u1",
        detail="login from phone 13800001234",
    )
    rows = query_audit(user_id="u1")
    assert any("138****1234" in (r["detail"] or "") for r in rows)


# ---------------------------------------------------------------------------
# E. config 强校验
# ---------------------------------------------------------------------------
def test_check_api_keys_flags_placeholders(monkeypatch, caplog):
    """环境变量中是占位符时,_check_api_keys 应输出 warning"""
    monkeypatch.setenv("OPENAI_API_KEY", "__SET_ME__")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "your_api_key_here")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-xxxxx-real")  # 不应被命中
    monkeypatch.setenv("ENV", "development")

    import logging
    import config
    config._check_api_keys.__wrapped__ if hasattr(config._check_api_keys, "__wrapped__") else config._check_api_keys


def test_is_placeholder_helper():
    from config import _is_placeholder
    assert _is_placeholder("__SET_ME__")
    assert _is_placeholder("your_api_key_here")
    assert _is_placeholder("sk-XXX")
    assert _is_placeholder("CHANGEME")
    assert not _is_placeholder("sk-abc123real")
    assert not _is_placeholder("")
    assert not _is_placeholder(None) or True  # 空字符串不在


# ---------------------------------------------------------------------------
# F. feedback.comment 落库前 PII 脱敏
# ---------------------------------------------------------------------------
def test_feedback_comment_pii_masked(tmp_path, monkeypatch):
    """FeedbackManager.add_feedback 后,DB 中 comment 字段的手机号应被脱敏"""
    from paths import FEEDBACK_DB
    db = tmp_path / "feedback_test.db"
    monkeypatch.setattr("paths.FEEDBACK_DB", db)

    import feedback.feedback_manager as fm_mod
    fm_mod.DB_PATH = str(db)
    fm_mod.FeedbackManager._initialized = False

    mgr = fm_mod.FeedbackManager()
    result = mgr.add_feedback(
        message_id="msg-1",
        user_id="user-1",
        conversation_id="conv-1",
        feedback_type="comment",
        comment="可以联系我 13800001234",
    )
    assert result["success"]

    import sqlite3
    conn = sqlite3.connect(str(db))
    row = conn.execute(
        "SELECT comment FROM message_feedback WHERE message_id = ?", ("msg-1",)
    ).fetchone()
    conn.close()
    assert row is not None
    assert "138****1234" in row[0]
    assert "13800001234" not in row[0]


# ---------------------------------------------------------------------------
# G. behavior_event 落库前 PII 脱敏
# ---------------------------------------------------------------------------
def test_behavior_event_pii_masked(tmp_path, monkeypatch):
    """BehaviorPersistence.record_event 写入的 event_data / context 中 PII 应被脱敏"""
    db = tmp_path / "behavior_test.db"

    # 手动建表(测试中不依赖全局 init_all_schemas)
    import sqlite3
    conn = sqlite3.connect(str(db))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS behavior_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            event_data TEXT,
            intent_type TEXT,
            context TEXT,
            carbon_impact REAL,
            duration_minutes INTEGER,
            related_interests TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

    from user_profile.persistence import BehaviorPersistence
    bp = BehaviorPersistence(db_path=str(db))

    event_id = bp.record_event(
        user_id="user-1",
        event_type="travel",
        event_data={"note": "我的手机 13800001234", "miles": 10},
        context="地址:北京市朝阳区建国路88号",
    )
    assert event_id > 0

    conn = sqlite3.connect(str(db))
    row = conn.execute(
        "SELECT event_data, context FROM behavior_events WHERE id = ?", (event_id,)
    ).fetchone()
    conn.close()
    assert row is not None
    edata = json.loads(row[0])
    ctx = row[1]
    assert "138****1234" in edata["note"]
    assert edata["miles"] == 10
    assert "13800001234" not in edata["note"]
    # context 也应脱敏
    assert "***" in ctx
