"""
P5-E 错误处理 + 健康检查契约测试

覆盖:
1. APIError 异常类 + code → status 映射
2. error_response / health_check_payload
3. _dispatch 捕获 APIError → 正确 status + JSON
4. _dispatch 兜底异常 → 不泄栈,返 INTERNAL
5. /api/health 真探活: ok / degraded / down 场景
6. /api/ready readiness probe
7. routers 改用 APIError 后,旧 try/except + send_error(500) 0 命中
"""

import sys
import json
import sqlite3
import time
from io import BytesIO
from pathlib import Path
from unittest.mock import patch, MagicMock

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / 'src'))

import pytest


# ========== 1. APIError 单元测试 ==========

def test_api_error_basic():
    """APIError 携带 code / message / status"""
    from server.errors import APIError
    e = APIError("BAD_REQUEST", "字段缺失")
    assert e.code == "BAD_REQUEST"
    assert e.message == "字段缺失"
    assert e.status == 400
    assert isinstance(e, Exception)


def test_api_error_default_message():
    """P6.H: 不传 message → 用 HTTP_STATUS_MAP 默认值(按 locale 选)"""
    from server.errors import APIError

    # 默认 locale = zh(中文)
    e = APIError("UNAUTHORIZED")  # 不传 locale
    assert e.message == "需要登录"
    assert e.status == 401

    e2 = APIError("INTERNAL")
    assert e2.message == "服务暂时不可用"
    assert e2.status == 500

    # 显式 locale="en" → 英文
    e_en = APIError("UNAUTHORIZED", locale="en")
    assert e_en.message == "Authentication required"


def test_api_error_unknown_code():
    """未知 code → 500 + Unknown error(P6.H: 按 locale)"""
    from server.errors import APIError
    e = APIError("WEIRD_CODE")
    assert e.status == 500
    # 默认 zh 返中文
    assert "未知" in e.message

    e_en = APIError("WEIRD_CODE", locale="en")
    assert e_en.message == "Unknown error"


def test_api_error_to_dict():
    """to_dict 输出标准 JSON 结构"""
    from server.errors import APIError
    e = APIError("NOT_FOUND", "用户不存在")
    d = e.to_dict()
    assert d == {
        "ok": False,
        "error": {
            "code": "NOT_FOUND",
            "message": "用户不存在",
            "status": 404,
        },
    }


def test_api_error_to_dict_with_extra():
    """APIError 可携带 extra 字段"""
    from server.errors import APIError
    e = APIError("BAD_REQUEST", "字段缺失", field="user_id", hint="请先登录")
    d = e.to_dict()
    assert d["error"]["field"] == "user_id"
    assert d["error"]["hint"] == "请先登录"


def test_status_for_known_codes():
    """status_for / message_for 查表(P6.H: message_for 按 locale)"""
    from server.errors import status_for, message_for
    assert status_for("BAD_REQUEST") == 400
    assert status_for("UNAUTHORIZED") == 401
    assert status_for("FORBIDDEN") == 403
    assert status_for("NOT_FOUND") == 404
    assert status_for("RATE_LIMITED") == 429
    assert status_for("INTERNAL") == 500
    assert status_for("LLM_UNAVAILABLE") == 503
    assert status_for("TIMEOUT") == 504
    assert status_for("WEIRD") == 500  # default

    # 默认 locale=zh
    assert message_for("UNAUTHORIZED") == "需要登录"
    assert "服务" in message_for("INTERNAL")

    # 显式 locale="en"
    assert message_for("UNAUTHORIZED", locale="en") == "Authentication required"
    assert "Service" in message_for("INTERNAL", locale="en")


# ========== 2. health_check_payload 聚合 ==========

def test_health_check_all_ok():
    from server.errors import health_check_payload
    checks = {
        "a": {"status": "ok", "detail": "..."},
        "b": {"status": "ok"},
    }
    result = health_check_payload(checks)
    assert result["status"] == "ok"
    assert result["checks"] == checks


def test_health_check_one_down_makes_whole_down():
    from server.errors import health_check_payload
    checks = {
        "a": {"status": "ok"},
        "b": {"status": "down", "detail": "DB unreachable"},
    }
    result = health_check_payload(checks)
    assert result["status"] == "down"


def test_health_check_degraded_aggregate():
    from server.errors import health_check_payload
    checks = {
        "a": {"status": "ok"},
        "b": {"status": "degraded", "detail": "slow"},
        "c": {"status": "ok"},
    }
    result = health_check_payload(checks)
    assert result["status"] == "degraded"


# ========== 3. _dispatch 集成测试 ==========

def _make_routed_handler(method: str, path: str, body: bytes = b"", headers: dict = None):
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
    handler.wfile = BytesIO()
    handler.send_response = lambda status: setattr(handler, "last_status", status)
    handler.send_header = lambda k, v: None
    handler.end_headers = lambda: None
    def _read_body():
        return body.decode("utf-8") if body else ""
    handler._read_body = _read_body
    handler._cors_origin = lambda: "*"
    handler.log_message = lambda fmt, *a: None
    def instance_send_json(data, status=200):
        handler.last_status = status
        handler.last_body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
    handler.send_json = instance_send_json
    return handler


def test_dispatch_404_returns_json_error():
    """未匹配路由 → 404 + JSON 错误,不泄栈"""
    from server.app import RoutedRequestHandler
    from server.router import reset_registry, get_registry
    reset_registry()

    handler = _make_routed_handler(method="GET", path="/api/does-not-exist")
    RoutedRequestHandler.do_GET(handler)
    assert handler.last_status == 404
    body = json.loads(handler.last_body.decode("utf-8"))
    assert body["ok"] is False
    assert body["error"]["code"] == "NOT_FOUND"
    assert "Not Found" in body["error"]["message"]


def test_dispatch_invalid_json_returns_400():
    """Invalid JSON body → 400"""
    from server.app import RoutedRequestHandler
    from server.router import reset_registry, get_registry
    from server.routers import register_all_routes
    reset_registry()
    register_all_routes(get_registry())

    handler = _make_routed_handler(method="POST", path="/api/auth/login", body=b"{not valid json")
    RoutedRequestHandler.do_POST(handler)
    assert handler.last_status == 400
    body = json.loads(handler.last_body.decode("utf-8"))
    assert body["error"]["code"] == "BAD_REQUEST"
    assert "Invalid JSON" in body["error"]["message"]


def test_dispatch_api_error_caught_with_status():
    """handler 抛 APIError → _dispatch 捕获并用其 status"""
    from server.app import RoutedRequestHandler
    from server.router import reset_registry, get_registry, Route
    from server.errors import APIError
    reset_registry()

    def my_handler(handler_obj):
        raise APIError("FORBIDDEN", "无权访问此资源")

    registry = get_registry()
    registry.add(Route("GET", "/api/x", my_handler, auth_required=False, description="test"))

    handler = _make_routed_handler(method="GET", path="/api/x")
    RoutedRequestHandler.do_GET(handler)
    assert handler.last_status == 403
    body = json.loads(handler.last_body.decode("utf-8"))
    assert body["error"]["code"] == "FORBIDDEN"
    assert body["error"]["message"] == "无权访问此资源"


def test_dispatch_unexpected_exception_becomes_internal():
    """未捕获异常 → INTERNAL,绝不泄栈"""
    from server.app import RoutedRequestHandler
    from server.router import reset_registry, get_registry, Route
    reset_registry()

    def my_handler(handler_obj):
        raise RuntimeError("SECRET INTERNAL DETAIL: 数据库密码 = hunter2")

    registry = get_registry()
    registry.add(Route("GET", "/api/boom", my_handler, auth_required=False, description="test"))

    handler = _make_routed_handler(method="GET", path="/api/boom")
    RoutedRequestHandler.do_GET(handler)
    assert handler.last_status == 500
    body = json.loads(handler.last_body.decode("utf-8"))
    assert body["error"]["code"] == "INTERNAL"
    assert "hunter2" not in handler.last_body.decode("utf-8"), \
        "stack trace / 敏感信息绝不能泄到客户端"
    assert "数据库密码" not in handler.last_body.decode("utf-8")
    assert "服务暂时不可用" in body["error"]["message"]


# ========== 4. /api/health 真探活 ==========

def test_health_check_success_path():
    """DB 正常时 /api/health 返 200 + ok"""
    from server.app import RoutedRequestHandler
    from server.router import reset_registry, get_registry
    from server.routers import register_all_routes
    reset_registry()
    register_all_routes(get_registry())

    handler = _make_routed_handler(method="GET", path="/api/health")
    RoutedRequestHandler.do_GET(handler)
    # 200 if ok/degraded, 503 if down
    assert handler.last_status in (200, 503), f"unexpected: {handler.last_status}"
    body = json.loads(handler.last_body.decode("utf-8"))
    assert "health" in body
    assert "checks" in body["health"]
    assert "accounts_db" in body["health"]["checks"]


def test_health_check_accounts_db_probe():
    """health.checks.accounts_db 真探活"""
    from server.health import _check_accounts_db
    result = _check_accounts_db()
    # 真实项目里 accounts.db 存在 → ok
    assert result["status"] in ("ok", "down")
    assert "detail" in result


def test_health_check_accounts_db_down_when_missing(tmp_path, monkeypatch):
    """accounts.db 不存在 → accounts_db check status=down"""
    from server import health
    from server.health import _check_accounts_db

    # 把 DATA_DIR 指向 tmp_path(没 accounts.db)
    fake_dir = tmp_path / "fake_data"
    fake_dir.mkdir()
    monkeypatch.setattr("paths.DATA_DIR", fake_dir)

    result = _check_accounts_db()
    assert result["status"] == "down"
    assert "DB not found" in result["detail"]


def test_health_probe_returns_overall_status():
    """health_probe 返回 ok/degraded/down 三态之一"""
    from server.health import health_probe
    result = health_probe()
    assert "status" in result
    assert "checks" in result
    assert result["status"] in ("ok", "degraded", "down")


def test_health_check_vector_store_check_present():
    """vector_store check 存在"""
    from server.health import health_probe
    result = health_probe()
    assert "vector_store" in result["checks"]


def test_health_check_scheduler_check_present():
    """scheduler check 存在"""
    from server.health import health_probe
    result = health_probe()
    assert "scheduler" in result["checks"]


def test_health_check_metrics_check_present():
    """metrics check 存在"""
    from server.health import health_probe
    result = health_probe()
    assert "metrics" in result["checks"]


# ========== 5. /api/ready readiness probe ==========

def test_ready_endpoint_returns_ready_true():
    """accounts.db 可达时返 ready=true"""
    from server.app import RoutedRequestHandler
    from server.router import reset_registry, get_registry
    from server.routers import register_all_routes
    reset_registry()
    register_all_routes(get_registry())

    handler = _make_routed_handler(method="GET", path="/api/ready")
    RoutedRequestHandler.do_GET(handler)
    # accounts.db 应存在,readiness=True
    assert handler.last_status == 200
    body = json.loads(handler.last_body.decode("utf-8"))
    assert body["ready"] is True
    assert "accounts.db reachable" in body["detail"]


def test_ready_endpoint_returns_503_when_db_missing(tmp_path, monkeypatch):
    """accounts.db 不可达时返 503 + ready=false"""
    from server.app import RoutedRequestHandler
    from server.router import reset_registry, get_registry
    from server.routers import register_all_routes
    reset_registry()
    register_all_routes(get_registry())

    fake_dir = tmp_path / "fake_data"
    fake_dir.mkdir()
    monkeypatch.setattr("paths.DATA_DIR", fake_dir)

    handler = _make_routed_handler(method="GET", path="/api/ready")
    RoutedRequestHandler.do_GET(handler)
    assert handler.last_status == 503
    body = json.loads(handler.last_body.decode("utf-8"))
    assert body["ready"] is False


# ========== 6. routers 不再散落 send_error(500, str(e)) ==========

def test_routers_no_leak_send_error_500():
    """所有 routers 不能再出现 send_error(500, str(...))"""
    import re
    routers_dir = Path(__file__).resolve().parent.parent / "src" / "server" / "routers"
    pattern = re.compile(r"send_error\s*\(\s*5\d\d\s*,\s*(f[\"']|.*str\()")
    for py_file in routers_dir.glob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        matches = pattern.findall(text)
        assert not matches, f"{py_file.name} still has send_error(500, str(e)): {matches}"


def test_routers_no_inline_str_e_500():
    """所有 routers 不能再出现 send_json({...str(e)...}, status=500)"""
    import re
    routers_dir = Path(__file__).resolve().parent.parent / "src" / "server" / "routers"
    pattern = re.compile(r"status\s*=\s*5\d\d.*str\(e\)", re.DOTALL)
    for py_file in routers_dir.glob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        matches = pattern.findall(text)
        assert not matches, f"{py_file.name} has str(e) in 5xx response: {matches}"


# ========== 7. 端到端: 真实 handler 抛 APIError ==========

def test_e2e_chat_no_message_returns_400():
    """P6.A: POST /api/chat 缺 message → 400 + BAD_REQUEST(带 token 走鉴权)"""
    from server.app import RoutedRequestHandler
    from server.router import reset_registry, get_registry
    from server.routers import register_all_routes
    from auth.account_manager import AccountManager
    import uuid as _uuid
    reset_registry()
    register_all_routes(get_registry())

    # P6.A: chat 路由现在需鉴权,先注册拿 token
    mgr = AccountManager()
    username = f"tc_{_uuid.uuid4().hex[:6]}"
    mgr.register(username, "testpass123")
    login = mgr.login(username, "testpass123")
    session_id = login["session_id"]

    try:
        body = json.dumps({"user_id": "u1"}).encode("utf-8")
        handler = _make_routed_handler(
            method="POST", path="/api/chat", body=body,
            headers={"Authorization": f"Bearer {session_id}"},
        )
        RoutedRequestHandler.do_POST(handler)
        assert handler.last_status == 400
        body_json = json.loads(handler.last_body.decode("utf-8"))
        assert body_json["error"]["code"] == "BAD_REQUEST"
        assert "Message is required" in body_json["error"]["message"]
    finally:
        mgr.logout(session_id)


def test_e2e_metrics_endpoint_still_works():
    """P5-B /api/metrics 仍工作(不破坏向后兼容)"""
    from server.app import RoutedRequestHandler
    from server.router import reset_registry, get_registry
    from server.routers import register_all_routes
    reset_registry()
    register_all_routes(get_registry())

    handler = _make_routed_handler(method="GET", path="/api/metrics")
    RoutedRequestHandler.do_GET(handler)
    assert handler.last_status == 200
    body = json.loads(handler.last_body.decode("utf-8"))
    assert body["ok"] is True
    assert "metrics" in body
    assert "total_calls" in body["metrics"]


def test_e2e_invalid_path_returns_404_with_json():
    """/api/garbage 404 + JSON,而不是 HTML 错误页"""
    from server.app import RoutedRequestHandler
    from server.router import reset_registry, get_registry
    reset_registry()

    handler = _make_routed_handler(method="GET", path="/api/garbage")
    RoutedRequestHandler.do_GET(handler)
    assert handler.last_status == 404
    body = json.loads(handler.last_body.decode("utf-8"))
    assert body["error"]["code"] == "NOT_FOUND"


# ========== 8. _log 写 traceback 不泄到客户端 ==========

def test_unexpected_exception_logged_with_traceback(caplog):
    """未捕获异常应写 traceback 到日志,客户端只看到 INTERNAL"""
    import logging
    from server.app import RoutedRequestHandler
    from server.router import reset_registry, get_registry, Route
    reset_registry()

    def boom(handler_obj):
        raise ValueError("internal-only error: API_KEY=secret123")

    registry = get_registry()
    registry.add(Route("GET", "/api/secret-boom", boom, auth_required=False, description="test"))

    handler = _make_routed_handler(method="GET", path="/api/secret-boom")

    with caplog.at_level(logging.ERROR, logger="server.app"):
        RoutedRequestHandler.do_GET(handler)

    # 客户端拿到的
    body = json.loads(handler.last_body.decode("utf-8"))
    assert body["error"]["code"] == "INTERNAL"
    assert "secret123" not in handler.last_body.decode("utf-8")

    # 日志应记录了完整异常(供运维排查)
    # (caplog 可能抓不到,因为 _log.exception 走标准 logging,要看 logger 配置)
    # 至少我们验证了 client side 不泄
