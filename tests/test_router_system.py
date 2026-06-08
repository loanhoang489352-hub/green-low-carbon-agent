"""
验证 P2-剩余: main.py 拆分 routers
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def test_router_registration():
    """路由可注册、可查询"""
    from server.router import RouterRegistry, Route

    reg = RouterRegistry()
    reg.add_route("GET", "/foo", lambda h: None)
    reg.add_route("POST", "/api/bar", lambda h, d: None, auth_required=False)

    g = reg.find("GET", "/foo")
    assert g is not None and g.method == "GET"

    p = reg.find("POST", "/api/bar")
    assert p is not None and p.method == "POST"

    miss = reg.find("GET", "/missing")
    assert miss is None
    print(f"✅ test_router_registration PASSED")


def test_router_prefix_match():
    """前缀匹配(^)应工作"""
    from server.router import RouterRegistry

    reg = RouterRegistry()
    reg.add_route("GET", "^/api/profile/", lambda h: None)

    assert reg.find("GET", "/api/profile/user1") is not None
    assert reg.find("GET", "/api/other/") is None
    print(f"✅ test_router_prefix_match PASSED")


def test_all_routes_registered():
    """所有 router 模块都应成功注册,无重复"""
    from server.router import get_registry, reset_registry
    from server.routers import register_all_routes

    reset_registry()
    registry = get_registry()
    register_all_routes(registry)

    routes = registry.list_routes()
    assert len(routes) >= 5, f"至少应有 5 个路由,实际 {len(routes)}"

    # 检查重复
    seen = set()
    for r in routes:
        key = (r.method, r.path)
        assert key not in seen, f"重复路由: {key}"
        seen.add(key)
    print(f"✅ test_all_routes_registered PASSED ({len(routes)} routes registered)")


def test_routed_handler_dispatches():
    """RoutedRequestHandler 正确分发到路由"""
    from server.router import RouterRegistry, reset_registry, get_registry

    reset_registry()
    registry = get_registry()

    called = {}

    def my_handler(handler):
        called["yes"] = True
        handler.send_json({"ok": True})

    registry.add_route("GET", "/test-route", my_handler, auth_required=False)

    # 用 BaseHTTPRequestHandler 的测试工具
    from io import BytesIO
    from server.app import RoutedRequestHandler

    # 构造 mock handler 实例
    class MockHandler:
        path = "/test-route"
        def _read_body(self):
            return ""
        def _cors_origin(self):
            return "*"

    # 直接调用 dispatch(用 monkey patch do_GET 的方法)
    handler = RoutedRequestHandler.__new__(RoutedRequestHandler)
    # 跳过 BaseHTTPRequestHandler.__init__,手动设置
    handler.path = "/test-route"
    handler.headers = {}
    handler.rfile = BytesIO(b"")

    # 设置响应缓冲
    response_buffer = BytesIO()
    handler.wfile = response_buffer
    handler.send_response = lambda status: None
    handler.send_header = lambda k, v: None
    handler.end_headers = lambda: None

    # 触发 do_GET
    RoutedRequestHandler.do_GET(handler)

    assert called.get("yes") is True
    response_text = response_buffer.getvalue().decode("utf-8")
    assert '"ok": true' in response_text
    print(f"✅ test_routed_handler_dispatches PASSED")


if __name__ == "__main__":
    test_router_registration()
    test_router_prefix_match()
    test_all_routes_registered()
    test_routed_handler_dispatches()
    print("\n🎉 all router system tests passed")
