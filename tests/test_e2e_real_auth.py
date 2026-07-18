"""
P5-D 鉴权强制落地 — 端到端真实鉴权测试

覆盖:
1. 无 token 访问受保护端点 → 401(不再 400)
2. 错误 token → 401
3. 过期 token → 401
4. Bearer token 正确 → 通过鉴权
5. X-Session-Id header 兜底 → 通过鉴权
6. body.session_id 兜底 → 通过鉴权
7. 受保护端点覆盖 — 9 个核心敏感路由全 401
8. 公共端点不被误伤 — /api/health, /api/policy/summary 仍 200
9. auth/login, auth/register 自身端点公开

注:pytest 9.0.3 + Python 3.14 有 capfd 兼容问题(Bug32),所以本测试用 function-based
不用 fixture,与 test_auth_e2e.py 的成熟模式一致。
"""

import sys
import json
import uuid
from io import BytesIO
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

import pytest


# ========== 1. 无 token → 401 (不是 400) ==========

PROTECTED_PATHS = [
    ("POST", "/api/chat/enhanced"),
    ("POST", "/api/feedback"),
    ("GET", "/api/profile/abc"),
    ("GET", "/api/personalization/abc"),
    ("GET", "/api/stats/abc"),
    ("GET", "/api/conversation/abc"),
    ("POST", "/api/recommendations"),
    ("POST", "/api/onboarding/start"),
    ("POST", "/api/onboarding/answer"),
]


@pytest.mark.parametrize("method,path", PROTECTED_PATHS)
def test_no_token_returns_401_not_400(method, path):
    """
    受保护端点无 token → 401 UNAUTHORIZED(不泄栈到 400 BAD_REQUEST)

    关键回归:之前 30+ 受保护路由因 auth_required=False 透传到 handler,
    handler 校验 body 缺失返 400(测试期望 401 但实际 400)。
    """
    from server.app import RoutedRequestHandler
    from server.router import reset_registry, get_registry
    from server.routers import register_all_routes

    reset_registry()
    register_all_routes(get_registry())

    handler = _make_routed_handler(method=method, path=path, body=b"{}")
    if method == "GET":
        RoutedRequestHandler.do_GET(handler)
    else:
        RoutedRequestHandler.do_POST(handler)

    assert handler.last_status == 401, (
        f"{method} {path} 无 token 应 401,实际 {handler.last_status}: {handler.last_body}"
    )
    body = json.loads(handler.last_body.decode("utf-8"))
    assert body["error"]["code"] == "UNAUTHORIZED", (
        f"{method} {path} 错误码: {body}"
    )


# ========== 2. 错误 token → 401 ==========

@pytest.mark.parametrize("method,path", [
    ("POST", "/api/chat/enhanced"),
    ("POST", "/api/feedback"),
    ("GET", "/api/profile/abc"),
])
def test_invalid_token_returns_401(method, path):
    """错误格式的 token → 401"""
    from server.app import RoutedRequestHandler
    from server.router import reset_registry, get_registry
    from server.routers import register_all_routes

    reset_registry()
    register_all_routes(get_registry())

    handler = _make_routed_handler(
        method=method, path=path, body=b"{}",
        headers={"Authorization": "Bearer not-a-real-token-zzz"},
    )
    if method == "GET":
        RoutedRequestHandler.do_GET(handler)
    else:
        RoutedRequestHandler.do_POST(handler)

    assert handler.last_status == 401
    body = json.loads(handler.last_body.decode("utf-8"))
    assert body["error"]["code"] == "UNAUTHORIZED"


# ========== 3. 过期 token → 401 ==========

def test_expired_token_returns_401():
    """过期 session → 401"""
    from auth.account_manager import AccountManager, _get_connection
    from datetime import datetime, timedelta
    from server.app import RoutedRequestHandler
    from server.router import reset_registry, get_registry
    from server.routers import register_all_routes

    reset_registry()
    register_all_routes(get_registry())

    mgr = AccountManager()
    username = f"exp_{uuid.uuid4().hex[:8]}"
    mgr.register(username, "testpass123")
    login = mgr.login(username, "testpass123")
    session_id = login["session_id"]

    # 强制过期
    conn = _get_connection()
    past = (datetime.now() - timedelta(days=1)).isoformat()
    conn.execute(
        "UPDATE user_sessions SET expires_at = ? WHERE session_id = ?",
        (past, session_id),
    )
    conn.commit()
    conn.close()

    try:
        handler = _make_routed_handler(
            method="POST", path="/api/feedback", body=b'{"message_id":"m1","type":"like"}',
            headers={"Authorization": f"Bearer {session_id}"},
        )
        RoutedRequestHandler.do_POST(handler)
        assert handler.last_status == 401
        body = json.loads(handler.last_body.decode("utf-8"))
        assert body["error"]["code"] == "UNAUTHORIZED"
    finally:
        mgr.logout(session_id)


# ========== 4. 正确 Bearer token → 通过鉴权 ==========

def test_valid_bearer_token_passes_auth():
    """正确 Bearer token → 通过鉴权(可能 200 或 500,关键是 != 401)"""
    from auth.account_manager import AccountManager
    from server.app import RoutedRequestHandler
    from server.router import reset_registry, get_registry
    from server.routers import register_all_routes

    reset_registry()
    register_all_routes(get_registry())

    mgr = AccountManager()
    username = f"rt_{uuid.uuid4().hex[:6]}"
    mgr.register(username, "testpass123")
    login = mgr.login(username, "testpass123")
    session_id = login["session_id"]

    try:
        handler = _make_routed_handler(
            method="POST", path="/api/feedback",
            body=b'{"message_id":"m1","type":"like"}',
            headers={"Authorization": f"Bearer {session_id}"},
        )
        RoutedRequestHandler.do_POST(handler)
        # 鉴权通过:200 / 500 都可,但不能 401
        assert handler.last_status != 401, (
            f"正确 token 应通过鉴权,实际 {handler.last_status}: {handler.last_body}"
        )
    finally:
        mgr.logout(session_id)


def test_x_session_id_header_passes_auth():
    """X-Session-Id header → 通过鉴权"""
    from auth.account_manager import AccountManager
    from server.app import RoutedRequestHandler
    from server.router import reset_registry, get_registry
    from server.routers import register_all_routes

    reset_registry()
    register_all_routes(get_registry())

    mgr = AccountManager()
    username = f"xh_{uuid.uuid4().hex[:6]}"
    mgr.register(username, "testpass123")
    login = mgr.login(username, "testpass123")
    session_id = login["session_id"]

    try:
        handler = _make_routed_handler(
            method="POST", path="/api/feedback",
            body=b'{"message_id":"m1","type":"like"}',
            headers={"X-Session-Id": session_id},
        )
        RoutedRequestHandler.do_POST(handler)
        assert handler.last_status != 401, (
            f"X-Session-Id 应通过鉴权,实际 {handler.last_status}: {handler.last_body}"
        )
    finally:
        mgr.logout(session_id)


def test_body_session_id_passes_auth():
    """body.session_id 兜底 → 通过鉴权"""
    from auth.account_manager import AccountManager
    from server.app import RoutedRequestHandler
    from server.router import reset_registry, get_registry
    from server.routers import register_all_routes

    reset_registry()
    register_all_routes(get_registry())

    mgr = AccountManager()
    username = f"bs_{uuid.uuid4().hex[:6]}"
    mgr.register(username, "testpass123")
    login = mgr.login(username, "testpass123")
    session_id = login["session_id"]

    try:
        body_str = json.dumps({"message_id": "m1", "type": "like", "session_id": session_id})
        handler = _make_routed_handler(
            method="POST", path="/api/feedback", body=body_str.encode("utf-8"),
        )
        RoutedRequestHandler.do_POST(handler)
        assert handler.last_status != 401, (
            f"body.session_id 应通过鉴权,实际 {handler.last_status}: {handler.last_body}"
        )
    finally:
        mgr.logout(session_id)


# ========== 5. 公共端点不被误伤 ==========

PUBLIC_PATHS = [
    ("GET", "/api/health"),
    ("GET", "/api/ready"),
    ("GET", "/api/metrics"),
    ("GET", "/api/policy/summary"),
    ("GET", "/api/policy/latest"),
    ("GET", "/api/knowledge/stats"),
]


@pytest.mark.parametrize("method,path", PUBLIC_PATHS)
def test_public_endpoints_remain_public(method, path):
    """公共端点无 token 仍 200(不被误伤)"""
    from server.app import RoutedRequestHandler
    from server.router import reset_registry, get_registry
    from server.routers import register_all_routes

    reset_registry()
    register_all_routes(get_registry())

    handler = _make_routed_handler(method=method, path=path, body=b"")
    RoutedRequestHandler.do_GET(handler)
    assert handler.last_status not in (401, 404), (
        f"{path} 应公开,实际 {handler.last_status}: {handler.last_body}"
    )


# ========== 6. auth/login 自身端点公开 ==========

def test_auth_login_endpoint_public():
    """/api/auth/login 无 token 可访问(认证端点本身)"""
    from server.app import RoutedRequestHandler
    from server.router import reset_registry, get_registry
    from server.routers import register_all_routes

    reset_registry()
    register_all_routes(get_registry())

    handler = _make_routed_handler(
        method="POST", path="/api/auth/login",
        body=b'{"username":"nonexistent_xyz","password":"x"}',
    )
    RoutedRequestHandler.do_POST(handler)
    # 关键: 鉴权中间件没拦下(login 自身 public),所以不是 401 UNAUTHORIZED
    # 实际可能是 500(INTERNAL,因 mock handler 无 account_manager 属性)或 200/400/401(login 业务)
    # 只要 code != UNAUTHORIZED 就行
    body = json.loads(handler.last_body.decode("utf-8"))
    err_code = body.get("error", {}).get("code")
    assert err_code != "UNAUTHORIZED", (
        f"login 应公开不应被鉴权拦下,实际 body={body}"
    )


def test_auth_register_endpoint_public():
    """/api/auth/register 无 token 可访问"""
    from server.app import RoutedRequestHandler
    from server.router import reset_registry, get_registry
    from server.routers import register_all_routes

    reset_registry()
    register_all_routes(get_registry())

    # 用合法字段注册一个新用户
    username = f"new_{uuid.uuid4().hex[:8]}"
    handler = _make_routed_handler(
        method="POST", path="/api/auth/register",
        body=json.dumps({"username": username, "password": "testpass123"}).encode("utf-8"),
    )
    RoutedRequestHandler.do_POST(handler)
    # 200 = 注册成功; 400 = 用户名格式问题; 都不应是 401(路由鉴权拦下)
    assert handler.last_status != 401, (
        f"register 公开,实际 {handler.last_status}: {handler.last_body}"
    )


# ========== 7. /api/chat (基础聊天) 仍公开(匿名可用) ==========

def test_basic_chat_remains_public():
    """/api/chat 保持公开,匿名 user_id 也能用(浏览器 UX 兜底)"""
    from server.app import RoutedRequestHandler
    from server.router import reset_registry, get_registry
    from server.routers import register_all_routes

    reset_registry()
    register_all_routes(get_registry())

    handler = _make_routed_handler(
        method="POST", path="/api/chat",
        body=b'{"message":"hi","user_id":"anonymous"}',
    )
    RoutedRequestHandler.do_POST(handler)
    # 200 / 500 都行,但不能 401(基础 chat 保持公开)
    assert handler.last_status != 401, (
        f"/api/chat 保持公开,实际 {handler.last_status}: {handler.last_body}"
    )


# ========== 工具函数 ==========

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

    def _read_body():
        content_length = len(body)
        return body.decode("utf-8") if content_length else ""

    handler._read_body = _read_body
    handler._cors_origin = lambda: "*"
    handler.log_message = lambda fmt, *a: None

    def instance_send_json(data, status=200):
        handler.last_status = status
        handler.last_body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")

    handler.send_json = instance_send_json
    return handler
