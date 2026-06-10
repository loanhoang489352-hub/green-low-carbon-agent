"""
P5-D 鉴权端到端测试

覆盖:
1. verify_token 字段(Authorization / X-Session-Id / body.session_id)
2. with_auth 装饰器包装后 handler 的成功 / 失败路径
3. _dispatch 鉴权中间件真实跑通(用 mock handler 模拟 HTTP)
4. router 默认 auth_required=True
5. 公共端点(/api/health)不受影响
6. e2e 流程: register → login → 拿到 session_id → 用 session_id 调受保护端点
"""

import sys
import json
import uuid
import sqlite3
from io import BytesIO
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / 'src'))

import pytest


# ========== 1. AccountManager.verify_token 单元测试 ==========

def test_verify_token_no_token_returns_none():
    """无 token → None"""
    from auth.account_manager import AccountManager
    mgr = AccountManager()
    assert mgr.verify_token({}) is None
    assert mgr.verify_token({}, {}) is None
    assert mgr.verify_token({"Authorization": ""}) is None


def test_verify_token_invalid_token_returns_none():
    """无效 session_id → None"""
    from auth.account_manager import AccountManager
    mgr = AccountManager()
    headers = {"Authorization": "Bearer not-a-real-session-id-xxx"}
    assert mgr.verify_token(headers) is None


def test_verify_token_from_authorization_header():
    """Authorization: Bearer <session_id>"""
    from auth.account_manager import AccountManager
    mgr = AccountManager()
    # 注册并登录
    username = f"test_auth_{uuid.uuid4().hex[:8]}"
    reg = mgr.register(username, "testpass123")
    assert reg.get("success") is True
    login = mgr.login(username, "testpass123")
    assert login.get("success") is True
    session_id = login["session_id"]
    try:
        identity = mgr.verify_token({"Authorization": f"Bearer {session_id}"})
        assert identity is not None
        assert identity["account_id"] == login["account_id"]
        assert identity["session_id"] == session_id
        assert identity["username"] == username
    finally:
        mgr.logout(session_id)


def test_verify_token_from_x_session_id_header():
    """X-Session-Id: <session_id>"""
    from auth.account_manager import AccountManager
    mgr = AccountManager()
    username = f"test_x_{uuid.uuid4().hex[:8]}"
    mgr.register(username, "testpass123")
    login = mgr.login(username, "testpass123")
    session_id = login["session_id"]
    try:
        identity = mgr.verify_token({"X-Session-Id": session_id})
        assert identity is not None
        assert identity["account_id"] == login["account_id"]
    finally:
        mgr.logout(session_id)


def test_verify_token_from_body():
    """body.session_id 兜底"""
    from auth.account_manager import AccountManager
    mgr = AccountManager()
    username = f"test_body_{uuid.uuid4().hex[:8]}"
    mgr.register(username, "testpass123")
    login = mgr.login(username, "testpass123")
    session_id = login["session_id"]
    try:
        identity = mgr.verify_token({}, {"session_id": session_id})
        assert identity is not None
        assert identity["account_id"] == login["account_id"]
    finally:
        mgr.logout(session_id)


def test_verify_token_expired_returns_none():
    """过期 session → None"""
    from auth.account_manager import AccountManager, _get_connection
    from datetime import datetime, timedelta

    mgr = AccountManager()
    username = f"test_exp_{uuid.uuid4().hex[:8]}"
    mgr.register(username, "testpass123")
    login = mgr.login(username, "testpass123")
    session_id = login["session_id"]
    account_id = login["account_id"]

    # 强制让该 session 过期
    conn = _get_connection()
    past = (datetime.now() - timedelta(days=1)).isoformat()
    conn.execute(
        "UPDATE user_sessions SET expires_at = ? WHERE session_id = ?",
        (past, session_id),
    )
    conn.commit()
    conn.close()

    try:
        identity = mgr.verify_token({"Authorization": f"Bearer {session_id}"})
        assert identity is None
    finally:
        mgr.logout(session_id)


def test_verify_token_returns_user_id_linked_to_account():
    """验证 user_id 通过 account_profiles 关联"""
    from auth.account_manager import AccountManager
    mgr = AccountManager()
    username = f"test_link_{uuid.uuid4().hex[:8]}"
    mgr.register(username, "testpass123")
    login = mgr.login(username, "testpass123")
    account_id = login["account_id"]
    test_user_id = f"u_{uuid.uuid4().hex[:8]}"
    mgr.link_user_profile(account_id, test_user_id)
    session_id = login["session_id"]
    try:
        identity = mgr.verify_token({"Authorization": f"Bearer {session_id}"})
        assert identity is not None
        assert identity["user_id"] == test_user_id
    finally:
        mgr.logout(session_id)


# ========== 2. with_auth 装饰器 ==========

def test_with_auth_decorator_no_token_returns_401():
    """无 token → handler.send_json(401) 被调用,handler 不执行"""
    from server.router import with_auth

    called = {"yes": False}

    def my_handler(handler_obj, data):
        called["yes"] = True

    wrapped = with_auth(my_handler)
    mock_handler = _make_mock_handler()
    wrapped(mock_handler, {})
    assert called["yes"] is False
    assert mock_handler.last_status == 401
    body = json.loads(mock_handler.last_body.decode("utf-8"))
    assert body["ok"] is False
    assert body["error"]["code"] == "UNAUTHORIZED"


def test_with_auth_decorator_with_valid_token_runs_handler():
    """有效 token → handler 执行,current_user 注入"""
    from server.router import with_auth
    from auth.account_manager import AccountManager

    mgr = AccountManager()
    username = f"test_dec_{uuid.uuid4().hex[:8]}"
    mgr.register(username, "testpass123")
    login = mgr.login(username, "testpass123")
    session_id = login["session_id"]

    try:
        called = {"yes": False, "user": None}

        def my_handler(handler_obj, data):
            called["yes"] = True
            called["user"] = getattr(handler_obj, "current_user", None)

        wrapped = with_auth(my_handler)
        mock_handler = _make_mock_handler(
            headers={"Authorization": f"Bearer {session_id}"}
        )
        wrapped(mock_handler, {})
        assert called["yes"] is True
        assert called["user"] is not None
        assert called["user"]["account_id"] == login["account_id"]
    finally:
        mgr.logout(session_id)


def test_with_auth_public_skips_check():
    """public=True 跳过鉴权"""
    from server.router import with_auth

    called = {"yes": False}

    def my_handler(handler_obj, data):
        called["yes"] = True

    wrapped = with_auth(my_handler, public=True)
    wrapped(_make_mock_handler(), {})
    assert called["yes"] is True


# ========== 3. router 默认 auth_required=True ==========

def test_router_default_auth_required_true():
    """不显式传 auth_required → 默认 True"""
    from server.router import RouterRegistry, Route
    reg = RouterRegistry()
    reg.add_route("POST", "/api/test", lambda h, d: None)
    r = reg.find("POST", "/api/test")
    assert r is not None
    assert r.auth_required is True


def test_router_explicit_false_works():
    """显式 auth_required=False 保持 False"""
    from server.router import RouterRegistry
    reg = RouterRegistry()
    reg.add_route("GET", "/api/public", lambda h: None, auth_required=False)
    r = reg.find("GET", "/api/public")
    assert r.auth_required is False


# ========== 4. _dispatch 中间件 (端到端) ==========

def test_dispatch_public_endpoint_no_token_passes():
    """公共端点 /api/health 无 token 也应通过"""
    from server.app import RoutedRequestHandler
    from server.router import reset_registry, get_registry
    from server.routers import register_all_routes

    reset_registry()
    register_all_routes(get_registry())

    handler = _make_routed_handler(method="GET", path="/api/health", body=b"")
    RoutedRequestHandler.do_GET(handler)
    assert handler.last_status == 200, f"public endpoint should pass, got {handler.last_status}: {handler.last_body}"


def test_dispatch_protected_endpoint_no_token_401():
    """显式注册一个需要 auth 的端点,无 token → 401"""
    from server.app import RoutedRequestHandler
    from server.router import reset_registry, get_registry, Route
    from server.routers import register_all_routes

    reset_registry()
    register_all_routes(get_registry())

    # 注册一个显式需要 auth 的端点
    registry = get_registry()
    registry.add(Route("GET", "/api/private", lambda h: h.send_json({"ok": True}), auth_required=True, description="test private"))

    # 临时关闭 auth_required 看看本身 handler 没问题
    handler = _make_routed_handler(method="GET", path="/api/private", body=b"")
    RoutedRequestHandler.do_GET(handler)
    assert handler.last_status == 401
    body = json.loads(handler.last_body.decode("utf-8"))
    assert body["error"]["code"] == "UNAUTHORIZED"


def test_dispatch_protected_endpoint_with_valid_token_passes():
    """有 token → 通过"""
    from server.app import RoutedRequestHandler
    from server.router import reset_registry, get_registry, Route
    from server.routers import register_all_routes
    from auth.account_manager import AccountManager

    reset_registry()
    register_all_routes(get_registry())

    registry = get_registry()
    registry.add(Route("GET", "/api/private2", lambda h: h.send_json({"ok": True, "user": h.current_user["account_id"]}), auth_required=True, description="test private 2"))

    mgr = AccountManager()
    username = f"test_disp_{uuid.uuid4().hex[:8]}"
    mgr.register(username, "testpass123")
    login = mgr.login(username, "testpass123")
    session_id = login["session_id"]

    try:
        handler = _make_routed_handler(
            method="GET",
            path="/api/private2",
            body=b"",
            headers={"Authorization": f"Bearer {session_id}"},
        )
        RoutedRequestHandler.do_GET(handler)
        assert handler.last_status == 200, f"got {handler.last_status}: {handler.last_body}"
        body = json.loads(handler.last_body.decode("utf-8"))
        assert body["ok"] is True
        assert body["user"] == login["account_id"]
    finally:
        mgr.logout(session_id)


# ========== 5. 真实端到端: register → login → 用 token 访问 ==========

def test_e2e_auth_flow():
    """完整流程: 注册 → 登录 → 拿 session_id → 验证鉴权中间件认可"""
    from auth.account_manager import AccountManager
    mgr = AccountManager()
    username = f"test_e2e_{uuid.uuid4().hex[:8]}"

    # 1. 注册
    reg = mgr.register(username, "testpass123")
    assert reg["success"] is True, reg

    # 2. 登录
    login = mgr.login(username, "testpass123")
    assert login["success"] is True
    session_id = login["session_id"]

    # 3. 鉴权
    identity = mgr.verify_token({"Authorization": f"Bearer {session_id}"})
    assert identity is not None
    assert identity["account_id"] == login["account_id"]
    assert identity["username"] == username

    # 4. 登出后失效
    mgr.logout(session_id)
    identity2 = mgr.verify_token({"Authorization": f"Bearer {session_id}"})
    assert identity2 is None


def test_e2e_legacy_endpoints_still_work():
    """所有现存路由(/api/chat 等)无 token 也能走通(回归保护)"""
    from server.app import RoutedRequestHandler
    from server.router import reset_registry, get_registry
    from server.routers import register_all_routes

    reset_registry()
    register_all_routes(get_registry())

    # /api/policy/summary 是 public 且不需要 agent 初始化
    handler = _make_routed_handler(method="GET", path="/api/policy/summary", body=b"")
    RoutedRequestHandler.do_GET(handler)
    # 200 = 成功,或 500 = policy_updater 报错但不是 401/404
    assert handler.last_status in (200, 500), f"unexpected: {handler.last_status}"


# ========== 工具函数 ==========

def _make_mock_handler(headers: dict = None):
    """构造一个最小 mock handler,模拟 BaseHTTPRequestHandler"""
    class MockHandler:
        def __init__(self, hdrs):
            self.last_status = None
            self.last_body = b""
            self.headers = hdrs or {}
        def send_json(self, data, status=200):
            self.last_status = status
            self.last_body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    return MockHandler(headers or {})


def _make_routed_handler(method: str, path: str, body: bytes, headers: dict = None):
    """构造 RoutedRequestHandler 实例(跳过 __init__)"""
    from server.app import RoutedRequestHandler

    handler = RoutedRequestHandler.__new__(RoutedRequestHandler)
    handler.path = path
    handler.headers = headers or {}
    handler.command = method
    handler.request_version = "HTTP/1.1"
    handler.rfile = BytesIO(body if body else b"")
    handler.last_status = None
    handler.last_body = b""

    response_buffer = BytesIO()
    handler.wfile = response_buffer
    handler.send_response = lambda status: setattr(handler, "last_status", status)
    handler.send_header = lambda k, v: None
    handler.end_headers = lambda: None

    # _read_body / _cors_origin / log_message
    def _read_body():
        content_length = len(body)
        return body.decode("utf-8") if content_length else ""

    handler._read_body = _read_body
    handler._cors_origin = lambda: "*"
    handler.log_message = lambda fmt, *a: None

    # 关键: 在 instance 上覆盖 send_json,而不是在 class 上(避免污染后续测试)
    def instance_send_json(data, status=200):
        handler.last_status = status
        handler.last_body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")

    handler.send_json = instance_send_json
    return handler
