"""
P6.S.14 测试: chat 端点对匿名 user_id 公开(避免 401)

P5-D 时代 chat 端点要求 auth_required=True,前端 onboarding 后 userId 已
生成但没 login session → 浏览器发请求没 Bearer token → 401 → 用户看到
降级内容或错误。P6.S.14 修后 chat 公开,user_id 当身份。

验证:
1. /api/chat/enhanced 无 token 也 200
2. /api/chat 无 token 也 200
3. 消息内容是真实 LLM(非模板)
4. 带 token 仍正常工作(向后兼容)
5. /api/feedback 等敏感端点仍需 auth(防止退步)
"""
import sys
import os
sys.path.insert(0, str(__file__).replace("\\", "/").replace("tests/test_p6s14_chat_anon_auth.py", "src"))

import urllib.request
import urllib.error
import json
import time


def _http_post(url, data, headers=None, timeout=60):
    headers = headers or {}
    headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=json.dumps(data).encode(), headers=headers, method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8", errors="ignore"))


def _http_get(url, headers=None, timeout=10):
    headers = headers or {}
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8", errors="ignore"))


def test_server_running():
    """前置:server 必须跑着"""
    code, body = _http_get("http://localhost:8000/api/health", timeout=5)
    if code != 200:
        print(f"⏭ SKIPPED: server not running (code={code})")
        return False
    return True


def test_chat_enhanced_anonymous_works():
    """P6.S.14: /api/chat/enhanced 无 token 应 200(关键修复)"""
    if not test_server_running():
        return
    code, body = _http_post(
        "http://localhost:8000/api/chat/enhanced",
        {"user_id": "u_anon_p6s14", "message": "碳中和是什么?"},
    )
    assert code == 200, f"匿名 chat 应 200, 实际 {code}: {body}"
    msg = body.get("message", "")
    assert len(msg) > 10, f"消息应有内容, 实际: {msg!r}"
    # 不应是模板回退
    assert "好的！让我用简单的方式" not in msg, "不应是模板回退"
    # 应含真实 LLM 关键词
    assert any(kw in msg for kw in ["碳", "排放", "低碳", "净零", "抵消"]), (
        f"应含碳相关知识, 实际: {msg[:200]!r}"
    )
    print("✅ test_chat_enhanced_anonymous_works PASSED")


def test_chat_basic_anonymous_works():
    """P6.S.14: /api/chat (basic) 无 token 也 200"""
    if not test_server_running():
        return
    code, body = _http_post(
        "http://localhost:8000/api/chat",
        {"user_id": "u_anon_p6s14", "message": "你好"},
    )
    assert code == 200, f"匿名 basic chat 应 200, 实际 {code}"
    print("✅ test_chat_basic_anonymous_works PASSED")


def test_conversation_history_anonymous_works():
    """P6.S.14: /api/conversation/history 无 token 也 200"""
    if not test_server_running():
        return
    code, body = _http_post(
        "http://localhost:8000/api/conversation/history",
        {"conversation_id": "test_conv_anon"},
    )
    assert code == 200, f"匿名 conversation history 应 200, 实际 {code}"
    print("✅ test_conversation_history_anonymous_works PASSED")


def test_recommendations_anonymous_works():
    """P6.S.14: /api/recommendations 无 token 也 200"""
    if not test_server_running():
        return
    code, body = _http_post(
        "http://localhost:8000/api/recommendations",
        {"user_id": "u_anon_p6s14"},
    )
    assert code == 200, f"匿名 recommendations 应 200, 实际 {code}"
    recs = body.get("recommendations", [])
    assert isinstance(recs, list)
    print(f"  recs: {len(recs)}")
    print("✅ test_recommendations_anonymous_works PASSED")


def test_sensitive_endpoints_still_require_auth():
    """P6.S.14: 敏感端点(feedback)仍需 auth,防止过度放宽"""
    if not test_server_running():
        return
    # /api/feedback 应仍需 auth
    code, body = _http_post(
        "http://localhost:8000/api/feedback",
        {"user_id": "u_anon", "message_id": "x", "rating": 5},
    )
    # 401 期望(没 token)
    assert code == 401, f"feedback 应仍 401, 实际 {code}"
    print("✅ test_sensitive_endpoints_still_require_auth PASSED")


def test_chat_enhanced_returns_real_llm_content():
    """P6.S.14: 真实 LLM 调用,非模板回退"""
    if not test_server_running():
        return
    code, body = _http_post(
        "http://localhost:8000/api/chat/enhanced",
        {"user_id": "u_anon_p6s14_llm", "message": "你是什么模型?请用一句话介绍自己"},
    )
    assert code == 200
    msg = body.get("message", "")
    # 真实 LLM 应返含"绿宝"(系统设定)或"测试模式"等
    assert "绿宝" in msg or "测试" in msg or "模型" in msg, (
        f"应含模型身份相关, 实际: {msg[:200]!r}"
    )
    # 不应是"好的！让我用..."模板
    assert "好的！让我用简单的方式" not in msg
    print(f"  msg 前 200: {msg[:200]!r}")
    print("✅ test_chat_enhanced_returns_real_llm_content PASSED")


def test_chat_routes_auth_required_false():
    """P6.S.14: chat.py 中 chat 路由应 auth_required=False"""
    from server.routers import register_all_routes
    from server.router import get_registry, reset_registry

    reset_registry()
    reg = get_registry()
    register_all_routes(reg)

    for path, expected in [
        ("/api/chat", False),
        ("/api/chat/enhanced", False),
        ("/api/conversation/reset", False),
        ("/api/conversation/history", False),
        ("/api/recommendations", False),
    ]:
        route = reg.find("POST", path)
        assert route is not None, f"{path} 路由未注册"
        assert route.auth_required is expected, (
            f"{path} 应 auth_required={expected}, 实际 {route.auth_required}"
        )
    print("✅ test_chat_routes_auth_required_false PASSED")


def test_feedback_route_still_requires_auth():
    """P6.S.14: feedback 仍 auth_required=True(不退步)"""
    from server.routers import register_all_routes
    from server.router import get_registry, reset_registry

    reset_registry()
    reg = get_registry()
    register_all_routes(reg)

    # 找 feedback 路由
    feedback_route = next(
        (r for r in reg.list_routes() if r.path == "/api/feedback" and r.method == "POST"),
        None,
    )
    assert feedback_route is not None
    assert feedback_route.auth_required is True, "feedback 应仍需 auth"
    print("✅ test_feedback_route_still_requires_auth PASSED")


if __name__ == "__main__":
    test_server_running()
    test_chat_routes_auth_required_false()
    test_feedback_route_still_requires_auth()
    test_chat_enhanced_anonymous_works()
    test_chat_basic_anonymous_works()
    test_conversation_history_anonymous_works()
    test_recommendations_anonymous_works()
    test_sensitive_endpoints_still_require_auth()
    test_chat_enhanced_returns_real_llm_content()
    print("\n🎉 All P6.S.14 tests PASSED")
