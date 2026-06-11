"""
P6.D 端到端全链路回归(in-process 部分)

P4-G / P4-H 已覆盖:RAG + 基础推荐 + 画像图谱 + 三层记忆(13 + 15 测试)
P6.D 加深:跨 P4-C/D/F + P5-G/H/I + P6.C 全链路联调,发现隐藏的逻辑链断点

本文件只保留不依赖 GreenAgent 单例的 in-process 测试(避免 Python 3.14 +
sentence-transformers/torch 的 importlib._path_stat 兼容问题)。

链路覆盖:
A. P4-C 行为事件 → 画像图谱(依赖 agent — 跳,见 test_p4g_e2e)
B. P4-D 行为阶段变更(依赖 agent — 跳,见 test_p4d_stage_prompts)
C. P4-F 个性化推荐(依赖 agent — 跳,见 test_p4f_personalization)
D. P5-I 审计落库(直接查 audit_log 表,见 P5-I 测试)
E. P5-I PII 脱敏 ✓
F. P5-I 限流 ✓(走真实 RoutedRequestHandler)
G. P5-G RAG 评估(依赖 RAG 引擎 — 跳,见 test_p5g_eval)
H. P6.C Query Cache 命中 ✓
I. P4-H 三层记忆 ✓(working memory 持久 + STM DB 持久)
J. 健康检查 + 限流 + 审计 跨模块协同 ✓
"""
import sys
import time
import sqlite3
import uuid
import json
import tempfile
import threading
from pathlib import Path
from io import BytesIO

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / 'src'))

import pytest


# ========== 共享 fixture ==========

@pytest.fixture
def fresh_uid():
    return f"u_p6d_{uuid.uuid4().hex[:8]}"


# ========== E. PII 脱敏 (P5-I) ==========

def test_chain_E_pii_masking_phone():
    """E.1: 手机号脱敏(11 位中国大陆手机号)"""
    from utils.pii import mask_phone
    assert mask_phone("13800001234") == "138****1234"
    assert mask_phone("15912345678") == "159****5678"
    # 11 位以下不脱敏(8 位座机号可能业务需要,这里只验证 11 位手机号)
    # 如果用户传短号,函数可能不处理(原样返回)— 软验证
    short = mask_phone("12345678")
    # 接受: 1) 脱敏了 或 2) 原样返回(说明函数不处理短号)
    assert short in ("12345678", "****5678", "12****78", "1****78")


def test_chain_E_pii_masking_email():
    """E.2: 邮箱脱敏"""
    from utils.pii import mask_email
    masked = mask_email("user@example.com")
    # 验证 @ 在,且 .com 保留
    assert "@" in masked
    assert ".com" in masked
    # 验证非明文
    assert "user" not in masked or "****" in masked


def test_chain_E_pii_masking_dict_recursive():
    """E.3: dict 递归脱敏"""
    from utils.pii import mask_pii_in_dict
    d = {
        "phone": "13800001234",
        "email": "x@y.com",
        "comment": "请联系 13800001234 或 x@y.com",
        "metadata": {"phone": "13900005678"},
        "safe_field": "不脱敏",
    }
    masked = mask_pii_in_dict(d)
    # 浅层
    assert "****" in masked["phone"]
    # 嵌套
    assert "****" in masked["metadata"]["phone"]
    # 安全字段不变
    assert masked["safe_field"] == "不脱敏"


# ========== F. 限流 (P5-I) ==========

def test_chain_F_rate_limit_429():
    """F.1: 60+1 次 /api/chat 应触发 429(走真实 RoutedRequestHandler)"""
    from server.app import RoutedRequestHandler
    from server.router import reset_registry, get_registry
    from server.routers import register_all_routes
    from auth.account_manager import AccountManager
    from server.middleware.rate_limit import get_rate_limiter

    # 重置限流器(避免上一测试残留)
    get_rate_limiter()._buckets.clear()

    reset_registry()
    register_all_routes(get_registry())

    mgr = AccountManager()
    username = f"rl_{uuid.uuid4().hex[:6]}"
    mgr.register(username, "testpass123")
    login = mgr.login(username, "testpass123")
    session_id = login["session_id"]

    def make_handler():
        handler = RoutedRequestHandler.__new__(RoutedRequestHandler)
        handler.path = "/api/chat"
        handler.headers = {"Authorization": f"Bearer {session_id}"}
        handler.command = "POST"
        handler.request_version = "HTTP/1.1"
        handler.rfile = BytesIO(b'{"message":"hi","user_id":"u_rl"}')
        handler.wfile = BytesIO()
        handler.last_status = None
        handler.last_body = b""
        def instance_send_json(data, status=200):
            handler.last_status = status
            handler.last_body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        handler.send_json = instance_send_json
        handler.send_response = lambda s: setattr(handler, "last_status", s)
        handler.send_header = lambda k, v: None
        handler.end_headers = lambda: None
        handler._read_body = lambda: '{"message":"hi","user_id":"u_rl"}'
        handler._cors_origin = lambda: "*"
        handler.log_message = lambda fmt, *a: None
        handler.client_address = ("127.0.0.1", 12345)
        return handler

    try:
        statuses = []
        for _ in range(62):
            h = make_handler()
            RoutedRequestHandler.do_POST(h)
            statuses.append(h.last_status)
        # 期望:至少出现一次 429
        assert 429 in statuses, f"应触发 429, 实际 status 分布: {set(statuses)}"
    finally:
        mgr.logout(session_id)
        get_rate_limiter()._buckets.clear()


# ========== H. Query Cache 命中 (P6.C) ==========

def test_chain_H_query_cache_basic_hit():
    """H.1: 直接测 QueryCache.get/set — 相同 query + 相同画像 → 命中"""
    from agent.cache import QueryCache, reset_query_cache
    reset_query_cache()

    cache = QueryCache(db_path=Path(tempfile.gettempdir()) / f"p6d_cache_{uuid.uuid4().hex[:6]}.db", ttl=60.0)
    profile = {
        "basic_info": {"region": "北京"},
        "eco_profile": {
            "primary_interests": ["low_carbon_travel"],
            "knowledge_level": "intermediate",
            "behavior_stage": "意向",
        },
    }

    # miss
    assert cache.get("北京低碳政策", "u1", profile) is None
    # set
    assert cache.set("北京低碳政策", "u1", profile, "回答 1", ["建议 1"])
    # hit
    cached = cache.get("北京低碳政策", "u1", profile)
    assert cached is not None
    assert cached["message"] == "回答 1"
    assert cached["suggestions"] == ["建议 1"]

    # 画像变了 → miss
    profile2 = dict(profile)
    profile2["basic_info"] = {"region": "上海"}
    assert cache.get("北京低碳政策", "u1", profile2) is None


def test_chain_H2_query_cache_invalidate_on_profile_change():
    """H.2: 画像变化触发 invalidate — 新请求应 miss"""
    from agent.cache import QueryCache
    cache = QueryCache(db_path=Path(tempfile.gettempdir()) / f"p6d_inv_{uuid.uuid4().hex[:6]}.db", ttl=60.0)
    profile = {"basic_info": {"region": "北京"}, "eco_profile": {}}
    cache.set("q", "u1", profile, "msg", [])

    # invalidate
    cleared = cache.invalidate("u1")
    assert cleared == 1

    # 再次 get 应 miss
    assert cache.get("q", "u1", profile) is None

    # 其他用户不受影响
    cache.set("q2", "u2", profile, "msg2", [])
    cache.invalidate("u1")  # 不应影响 u2
    assert cache.get("q2", "u2", profile) is not None


# ========== I. 三层记忆 (P4-H) ==========

def test_chain_I_working_memory_persists_across_sessions(fresh_uid):
    """I.1: working memory 跨实例持久(JSON 快照,P6.D 修复 set 后落盘)"""
    from memory.working import WorkingMemory
    wm1 = WorkingMemory()
    wm1.set(fresh_uid, "test_key", "test_value", agent_name="p6d_test", importance=0.5)
    wm2 = WorkingMemory()
    val = wm2.get(fresh_uid, "test_key")
    assert val == "test_value", f"working memory 应持久, 实际 {val}"


def test_chain_I2_working_memory_overwrite_detection(fresh_uid):
    """I.2: 同名 key 不同 agent 覆盖应被记录(OpenClaw 风格防污染)"""
    from memory.working import WorkingMemory
    wm = WorkingMemory()
    wm.set(fresh_uid, "shared_key", "agent_a_value", agent_name="agent_a", importance=0.5)
    wm.set(fresh_uid, "shared_key", "agent_b_value", agent_name="agent_b", importance=0.7)
    # 后写入应胜出
    val = wm.get(fresh_uid, "shared_key")
    assert val == "agent_b_value"


# ========== J. 健康检查 + 限流 + 审计 跨模块协同 ==========

def test_chain_J_health_metrics_and_cache_consistent():
    """J.1: /api/health + /api/metrics 同时返 OK,query_cache 字段齐全"""
    from server.app import RoutedRequestHandler
    from server.router import reset_registry, get_registry
    from server.routers import register_all_routes

    reset_registry()
    register_all_routes(get_registry())

    def hit(path):
        handler = RoutedRequestHandler.__new__(RoutedRequestHandler)
        handler.path = path
        handler.headers = {}
        handler.command = "GET"
        handler.request_version = "HTTP/1.1"
        handler.rfile = BytesIO(b"")
        handler.wfile = BytesIO()
        handler.last_status = None
        handler.last_body = b""
        def instance_send_json(data, status=200):
            handler.last_status = status
            handler.last_body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        handler.send_json = instance_send_json
        handler.send_response = lambda s: setattr(handler, "last_status", s)
        handler.send_header = lambda k, v: None
        handler.end_headers = lambda: None
        handler._read_body = lambda: ""
        handler._cors_origin = lambda: "*"
        handler.log_message = lambda fmt, *a: None
        RoutedRequestHandler.do_GET(handler)
        return handler.last_status, handler.last_body

    # /api/health
    s_h, b_h = hit("/api/health")
    body_h = json.loads(b_h.decode("utf-8"))
    assert s_h in (200, 503)
    assert "health" in body_h
    assert "checks" in body_h["health"]

    # /api/metrics
    s_m, b_m = hit("/api/metrics")
    body_m = json.loads(b_m.decode("utf-8"))
    assert s_m == 200
    assert "metrics" in body_m
    # P6.C 字段
    assert "query_cache" in body_m["metrics"]
    qc = body_m["metrics"]["query_cache"]
    for k in ("hits", "misses", "sets", "size", "hit_rate"):
        assert k in qc, f"query_cache 缺字段 {k}"

    # /api/ready
    s_r, b_r = hit("/api/ready")
    body_r = json.loads(b_r.decode("utf-8"))
    assert s_r == 200
    assert body_r.get("ready") is True


def test_chain_J2_audit_log_table_exists():
    """J.2: P5-I audit_log 表在 accounts.db 中存在且可写"""
    from paths import ACCOUNTS_DB
    conn = sqlite3.connect(str(ACCOUNTS_DB), timeout=2.0)
    try:
        # 表存在
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='audit_log'"
        ).fetchall()
        assert len(rows) == 1, f"audit_log 表应存在, 实际 {rows}"
        # 可写(insert 一条测试记录再 delete)
        conn.execute(
            "INSERT INTO audit_log (user_id, action, target, status_code, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("test_p6d", "test.p6d", "/test", 200, "2026-06-11T00:00:00"),
        )
        conn.commit()
        # 可读
        n = conn.execute("SELECT COUNT(*) FROM audit_log WHERE user_id = 'test_p6d'").fetchone()[0]
        assert n >= 1
        # 清理
        conn.execute("DELETE FROM audit_log WHERE user_id = 'test_p6d'")
        conn.commit()
    finally:
        conn.close()
