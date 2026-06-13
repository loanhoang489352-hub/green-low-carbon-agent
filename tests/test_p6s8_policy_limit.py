"""
P6.S.8 测试: 政策 limit 查询参数 + 画像 auth 放权

覆盖:
1. policy_latest 解析 ?limit=N(默认 10, 上限 50)
2. policy_latest 错误参数容错
3. personalization/auth 路由 auth_required=False(P6.S.7 + S.8 联合)
4. profile/auth 路由 auth_required=False
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def _make_handler_stub(path, policy_updater=None):
    """构造最小 handler 桩 — 模拟 router._dispatch 传进来的 handler"""

    class StubHandler:
        def __init__(self, path, updater):
            self.path = path
            self._policy_updater = updater
            self.sent = None

        @property
        def policy_updater(self):
            return self._policy_updater

        def send_json(self, data, status=200):
            self.sent = (data, status)

    return StubHandler(path, policy_updater)


def test_policy_latest_default_limit():
    """不传 limit → 默认 10"""
    from server.routers.system import register_system_routes
    from server.router import RouterRegistry

    captured_limit = {"v": None}

    class FakeUpdater:
        def get_latest_policies(self, limit=10):
            captured_limit["v"] = limit
            return [{"title": f"p{i}"} for i in range(limit)]

    reg = RouterRegistry()
    register_system_routes(reg)
    route = reg.find("GET", "/api/policy/latest")
    assert route is not None, "policy_latest 路由未注册"

    handler = _make_handler_stub("/api/policy/latest", FakeUpdater())
    route.handler(handler)
    assert captured_limit["v"] == 10, f"默认 limit 应为 10, 实际 {captured_limit['v']}"
    assert isinstance(handler.sent[0], list), "应直返数组"
    assert len(handler.sent[0]) == 10
    print("✅ test_policy_latest_default_limit PASSED")


def test_policy_latest_respects_limit_query():
    """?limit=5 → 应解析为 5"""
    from server.routers.system import register_system_routes
    from server.router import RouterRegistry

    captured_limit = {"v": None}

    class FakeUpdater:
        def get_latest_policies(self, limit=10):
            captured_limit["v"] = limit
            return [{"title": f"p{i}"} for i in range(limit)]

    reg = RouterRegistry()
    register_system_routes(reg)
    route = reg.find("GET", "/api/policy/latest")

    # P6.S.8: 路由匹配用 path-only, query string 在 handler 内解析
    # 模拟 urlparse(handler.path).query 实际是 handler 端接收的 raw path
    # 这里直接传带 query 的 path,policy_latest 内部用 urlparse
    handler = _make_handler_stub("/api/policy/latest?limit=5", FakeUpdater())
    route.handler(handler)
    assert captured_limit["v"] == 5, f"应解析为 5, 实际 {captured_limit['v']}"
    print("✅ test_policy_latest_respects_limit_query PASSED")


def test_policy_latest_invalid_limit_falls_back():
    """?limit=abc → 容错回退 10"""
    from server.routers.system import register_system_routes
    from server.router import RouterRegistry

    captured_limit = {"v": None}

    class FakeUpdater:
        def get_latest_policies(self, limit=10):
            captured_limit["v"] = limit
            return []

    reg = RouterRegistry()
    register_system_routes(reg)
    route = reg.find("GET", "/api/policy/latest")

    handler = _make_handler_stub("/api/policy/latest?limit=abc", FakeUpdater())
    route.handler(handler)
    assert captured_limit["v"] == 10, f"非法 limit 应回退 10, 实际 {captured_limit['v']}"
    print("✅ test_policy_latest_invalid_limit_falls_back PASSED")


def test_policy_latest_upper_bound_capped():
    """?limit=999 → 上限 50"""
    from server.routers.system import register_system_routes
    from server.router import RouterRegistry

    captured_limit = {"v": None}

    class FakeUpdater:
        def get_latest_policies(self, limit=10):
            captured_limit["v"] = limit
            return []

    reg = RouterRegistry()
    register_system_routes(reg)
    route = reg.find("GET", "/api/policy/latest")

    handler = _make_handler_stub("/api/policy/latest?limit=999", FakeUpdater())
    route.handler(handler)
    assert captured_limit["v"] == 50, f"上限应 50, 实际 {captured_limit['v']}"
    print("✅ test_policy_latest_upper_bound_capped PASSED")


def test_profile_routes_public():
    """P6.S.7: profile/personalization/stats 路由 auth_required=False"""
    from server.routers import register_all_routes
    from server.router import get_registry, reset_registry

    reset_registry()
    reg = get_registry()
    register_all_routes(reg)

    for path_prefix, desc in [
        ("/api/profile/", "profile"),
        ("/api/personalization/", "personalization GET"),
        ("/api/stats/", "stats"),
    ]:
        route = next(
            (r for r in reg.list_routes() if r.path.startswith("^") and r.path[1:].startswith(path_prefix)),
            None,
        )
        assert route is not None, f"{desc} 路由未注册"
        assert route.auth_required is False, f"{desc} 应 auth_required=False(前端无 token)"
        print(f"  ✓ {desc} auth_required=False")


def test_personalization_context_post_public():
    """P6.S.7: POST /api/personalization/context 应 public"""
    from server.routers import register_all_routes
    from server.router import get_registry, reset_registry

    reset_registry()
    reg = get_registry()
    register_all_routes(reg)

    route = reg.find("POST", "/api/personalization/context")
    assert route is not None
    assert route.auth_required is False, "personalization/context POST 应 public"
    print("✅ test_personalization_context_post_public PASSED")


def test_chat_routes_still_require_auth():
    """P6.S.7 回归: chat 路由应仍需 auth(只开放了 profile/policy)"""
    from server.routers import register_all_routes
    from server.router import get_registry, reset_registry

    reset_registry()
    reg = get_registry()
    register_all_routes(reg)

    for path in ["/api/chat", "/api/chat/enhanced", "/api/conversation/reset"]:
        route = reg.find("POST", path)
        assert route is not None
        assert route.auth_required is True, f"{path} 应保持 auth_required=True"
    print("✅ test_chat_routes_still_require_auth PASSED")


if __name__ == "__main__":
    test_policy_latest_default_limit()
    test_policy_latest_respects_limit_query()
    test_policy_latest_invalid_limit_falls_back()
    test_policy_latest_upper_bound_capped()
    test_profile_routes_public()
    test_personalization_context_post_public()
    test_chat_routes_still_require_auth()
    print("\n🎉 All P6.S.8 tests PASSED")
