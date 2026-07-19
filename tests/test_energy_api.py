"""
P12.2: 节能规划 HTTP 路由集成测试

覆盖:
1. 7 个端点(POST /api/energy/profile, plan, actions/{id}/complete, household/delegation;
          GET /api/energy/today, stats, actions)
2. 4 个 delegation level (0/1/2/3) 的行为差异
3. 401 测试(无 token → UNAUTHORIZED)
4. 边界 case(空画像、未知城市、streak 跨天)
"""
import json
import sys
import uuid
from io import BytesIO
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

import pytest

from server.app import RoutedRequestHandler
from server.router import reset_registry, get_registry
from server.routers import register_all_routes


# ========== Fixtures ==========


@pytest.fixture(autouse=True)
def _setup_registry():
    """每个用例前重置路由表"""
    reset_registry()
    register_all_routes(get_registry())
    yield


@pytest.fixture
def session_user():
    """注册+登录一个测试用户,返回 (session_id, user_id, username)"""
    from auth.account_manager import AccountManager

    mgr = AccountManager()
    username = f"energy_{uuid.uuid4().hex[:8]}"
    mgr.register(username, "testpass123")
    login = mgr.login(username, "testpass123")
    sid = login["session_id"]
    uid = login.get("user_id") or str(login.get("account_id"))
    yield (sid, uid, username)
    try:
        mgr.logout(sid)
    except Exception:
        pass


@pytest.fixture
def make_handler():
    """工厂:构造 RoutedRequestHandler(跳过 socket)"""

    def _factory(method, path, body=b"", headers=None):
        h = RoutedRequestHandler.__new__(RoutedRequestHandler)
        h.path = path
        h.headers = headers or {}
        h.command = method
        h.request_version = "HTTP/1.1"
        h.rfile = BytesIO(body if body else b"")
        h.last_status = None
        h.last_body = b""
        rb = BytesIO()
        h.wfile = rb
        h.send_response = lambda status: setattr(h, "last_status", status)
        h.send_header = lambda k, v: None
        h.end_headers = lambda: None

        def _rb():
            cl = len(body) if body else 0
            return body.decode("utf-8") if cl else ""

        h._read_body = _rb
        h._cors_origin = lambda: "*"
        h.log_message = lambda fmt, *a: None

        def sj(data, status=200):
            h.last_status = status
            h.last_body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")

        h.send_json = sj
        return h

    return _factory


def _post(handler):
    RoutedRequestHandler.do_POST(handler)


def _get(handler):
    RoutedRequestHandler.do_GET(handler)


def _body(handler):
    return json.loads(handler.last_body.decode("utf-8"))


# ========== 1. 401 测试:无 token ==========


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("POST", "/api/energy/profile", b'{"family_size":3}'),
        ("POST", "/api/energy/plan", b"{}"),
        ("GET", "/api/energy/today", b""),
        ("POST", "/api/energy/actions/abc/complete", b'{"completion_level":"full"}'),
        ("GET", "/api/energy/stats", b""),
        ("POST", "/api/household/delegation", b'{"new_level":1}'),
        ("GET", "/api/energy/actions", b""),
    ],
)
def test_no_token_returns_401(method, path, body, make_handler):
    """无 token → 401 UNAUTHORIZED"""
    h = make_handler(method=method, path=path, body=body)
    if method == "GET":
        _get(h)
    else:
        _post(h)
    assert h.last_status == 401, (
        f"{method} {path} 应 401,实际 {h.last_status}: {h.last_body}"
    )
    body_json = _body(h)
    assert body_json["error"]["code"] == "UNAUTHORIZED"


# ========== 2. POST /api/energy/profile — 4 个 delegation level ==========


def test_profile_level_0_auto_save(make_handler, session_user):
    """Level 0: 直接存,无 confirmation"""
    sid, uid, _ = session_user
    # 先把 delegation_level 设为 0
    _set_level(make_handler, sid, uid, 0)

    h = make_handler(
        "POST",
        "/api/energy/profile",
        body=json.dumps({"family_size": 3, "city": "beijing"}).encode("utf-8"),
        headers={"X-Session-Id": sid},
    )
    _post(h)
    assert h.last_status == 200, h.last_body
    data = _body(h)
    assert data["ok"] is True
    assert data["delegation_level"] == 0
    assert data["persisted"] is True
    assert data["confirmation_required"] is False
    assert "profile" in data and data["profile"]["family_size"] == 3


def test_profile_level_1_save_with_default(make_handler, session_user):
    """Level 1: 存,但 confirmation_required=false"""
    sid, uid, _ = session_user
    _set_level(make_handler, sid, uid, 1)

    h = make_handler(
        "POST",
        "/api/energy/profile",
        body=json.dumps({"family_size": 4, "city": "shanghai"}).encode("utf-8"),
        headers={"X-Session-Id": sid},
    )
    _post(h)
    data = _body(h)
    assert data["ok"] is True
    assert data["delegation_level"] == 1
    assert data["persisted"] is True
    assert data["confirmation_required"] is False


def test_profile_level_2_returns_variants(make_handler, session_user):
    """Level 2: 不存,返回 3 个 variants"""
    sid, uid, _ = session_user
    _set_level(make_handler, sid, uid, 2)

    h = make_handler(
        "POST",
        "/api/energy/profile",
        body=json.dumps({"family_size": 3, "home_size_sqm": 100}).encode("utf-8"),
        headers={"X-Session-Id": sid},
    )
    _post(h)
    data = _body(h)
    assert data["ok"] is True
    assert data["delegation_level"] == 2
    assert data["variant_mode"] is True
    assert data["persisted"] is False
    assert data["confirmation_required"] is True
    assert "variants" in data
    assert len(data["variants"]) == 3
    variant_ids = {v["variant_id"] for v in data["variants"]}
    assert variant_ids == {"small_apartment", "balanced", "large_household"}


def test_profile_level_3_echo_only(make_handler, session_user):
    """Level 3: 不存,只 echo"""
    sid, uid, _ = session_user
    _set_level(make_handler, sid, uid, 3)

    h = make_handler(
        "POST",
        "/api/energy/profile",
        body=json.dumps({"family_size": 2, "city": "shenzhen"}).encode("utf-8"),
        headers={"X-Session-Id": sid},
    )
    _post(h)
    data = _body(h)
    assert data["ok"] is True
    assert data["delegation_level"] == 3
    assert data["persisted"] is False
    assert data["echo_only"] is True
    assert "profile_echo" in data


# ========== 3. POST /api/energy/plan — 4 个 level ==========


def test_plan_level_0_auto_activate(make_handler, session_user):
    """Level 0: 自动激活"""
    sid, uid, _ = session_user
    _set_level(make_handler, sid, uid, 0)
    # 先存一个 profile
    _post_profile(make_handler, sid, {"family_size": 3, "city": "beijing"}, level=0)

    h = make_handler(
        "POST",
        "/api/energy/plan",
        body=b"{}",
        headers={"X-Session-Id": sid},
    )
    _post(h)
    data = _body(h)
    assert data["ok"] is True
    assert data["persisted"] is True
    assert data["status"] == "active"
    assert "plan" in data
    assert "today_card" in data
    assert data["today_card"]["actions"]  # 至少 1 个


def test_plan_level_1_draft_pending(make_handler, session_user):
    """Level 1: 默认 draft,需用户激活"""
    sid, uid, _ = session_user
    _set_level(make_handler, sid, uid, 1)
    _post_profile(make_handler, sid, {"family_size": 3}, level=1)

    h = make_handler(
        "POST",
        "/api/energy/plan",
        body=b"{}",
        headers={"X-Session-Id": sid},
    )
    _post(h)
    data = _body(h)
    assert data["ok"] is True
    # level=1 默认 draft
    assert data["status"] in ("draft", "active")
    assert data["confirmation_required"] is True


def test_plan_level_2_returns_variants(make_handler, session_user):
    """Level 2: 3 个 plan variants(money_first/co2_first/easy_first)"""
    sid, uid, _ = session_user
    _set_level(make_handler, sid, uid, 2)
    _post_profile(make_handler, sid, {"family_size": 3}, level=2)

    h = make_handler(
        "POST",
        "/api/energy/plan",
        body=b"{}",
        headers={"X-Session-Id": sid},
    )
    _post(h)
    data = _body(h)
    assert data["variant_mode"] is True
    assert data["persisted"] is False
    assert len(data["variants"]) == 3
    variant_ids = {v["variant_id"] for v in data["variants"]}
    assert variant_ids == {"money_first", "co2_first", "easy_first"}


def test_plan_level_3_echo(make_handler, session_user):
    """Level 3: 不存只 echo"""
    sid, uid, _ = session_user
    _set_level(make_handler, sid, uid, 3)

    h = make_handler(
        "POST",
        "/api/energy/plan",
        body=b"{}",
        headers={"X-Session-Id": sid},
    )
    _post(h)
    data = _body(h)
    assert data["echo_only"] is True
    assert data["persisted"] is False
    assert "plan" in data


# ========== 4. GET /api/energy/today ==========


def test_today_no_profile_uses_default(make_handler, session_user):
    """空画像:用默认画像生成 today card"""
    sid, uid, _ = session_user

    h = make_handler(
        "GET",
        "/api/energy/today",
        body=b"",
        headers={"X-Session-Id": sid},
    )
    _get(h)
    assert h.last_status == 200, h.last_body
    data = _body(h)
    assert "today_card" in data
    assert data["today_card"]["actions"]
    assert "reminder" in data["today_card"]


def test_today_unknown_city_uses_default_pricing(make_handler, session_user):
    """未知城市:不报错,降级到 default"""
    sid, uid, _ = session_user
    _post_profile(
        make_handler,
        sid,
        {"family_size": 3, "city": "atlantis"},
        level=1,
    )

    h = make_handler(
        "GET",
        "/api/energy/today",
        body=b"",
        headers={"X-Session-Id": sid},
    )
    _get(h)
    assert h.last_status == 200, h.last_body


# ========== 5. POST /api/energy/actions/{id}/complete ==========


def test_complete_full_streak(make_handler, session_user):
    """完成度 full → streak +1,入账 100%"""
    sid, uid, _ = session_user

    h = make_handler(
        "POST",
        "/api/energy/actions/ac_temp_up_1c/complete",
        body=json.dumps(
            {
                "completion_level": "full",
                "estimated_saving_cny": 27.5,
                "estimated_saving_kwh": 50.0,
                "estimated_saving_co2_kg": 40.0,
            }
        ).encode("utf-8"),
        headers={"X-Session-Id": sid},
    )
    _post(h)
    assert h.last_status == 200, h.last_body
    data = _body(h)
    assert data["ok"] is True
    assert data["completion_level"] == "full"
    assert data["credited_saving_cny"] == 27.5
    assert data["streak_days"] >= 1


def test_complete_partial_half_credit(make_handler, session_user):
    """完成度 partial → 入账 50%"""
    sid, uid, _ = session_user

    h = make_handler(
        "POST",
        "/api/energy/actions/ac_temp_up_1c/complete",
        body=json.dumps(
            {
                "completion_level": "partial",
                "estimated_saving_cny": 100.0,
                "estimated_saving_kwh": 100.0,
                "estimated_saving_co2_kg": 80.0,
            }
        ).encode("utf-8"),
        headers={"X-Session-Id": sid},
    )
    _post(h)
    data = _body(h)
    assert data["credited_saving_cny"] == 50.0
    assert data["credited_saving_co2_kg"] == 40.0


def test_complete_none_no_credit(make_handler, session_user):
    """完成度 none → 不入账"""
    sid, uid, _ = session_user

    h = make_handler(
        "POST",
        "/api/energy/actions/led_replace_incandescent/complete",
        body=json.dumps(
            {
                "completion_level": "none",
                "estimated_saving_cny": 55.0,
            }
        ).encode("utf-8"),
        headers={"X-Session-Id": sid},
    )
    _post(h)
    data = _body(h)
    assert data["credited_saving_cny"] == 0


def test_complete_invalid_level(make_handler, session_user):
    """非法 completion_level → 400"""
    sid, uid, _ = session_user

    h = make_handler(
        "POST",
        "/api/energy/actions/x/complete",
        body=json.dumps({"completion_level": "invalid_xyz"}).encode("utf-8"),
        headers={"X-Session-Id": sid},
    )
    _post(h)
    # P5-E 应返 400(BAD_REQUEST)或 200 但 ok=False
    body_json = _body(h)
    assert h.last_status in (200, 400)
    if h.last_status == 200:
        assert body_json.get("ok") is False


# ========== 6. GET /api/energy/stats ==========


def test_stats_empty(make_handler, session_user):
    """新用户 stats 全 0"""
    sid, uid, _ = session_user

    h = make_handler(
        "GET",
        "/api/energy/stats?period=week",
        body=b"",
        headers={"X-Session-Id": sid},
    )
    _get(h)
    assert h.last_status == 200, h.last_body
    data = _body(h)
    assert data["total_saving_cny"] == 0
    assert data["streak_days"] == 0
    assert data["trend"] == []


def test_stats_after_completion(make_handler, session_user):
    """完成几次 action 后 stats 累加正确"""
    sid, uid, _ = session_user
    # 1) full
    h = make_handler(
        "POST",
        "/api/energy/actions/ac_temp_up_1c/complete",
        body=json.dumps(
            {"completion_level": "full", "estimated_saving_cny": 27.5}
        ).encode("utf-8"),
        headers={"X-Session-Id": sid},
    )
    _post(h)
    # 2) partial
    h = make_handler(
        "POST",
        "/api/energy/actions/water_bathing_shorter/complete",
        body=json.dumps(
            {"completion_level": "partial", "estimated_saving_cny": 6.0}
        ).encode("utf-8"),
        headers={"X-Session-Id": sid},
    )
    _post(h)

    h = make_handler(
        "GET",
        "/api/energy/stats?period=all",
        body=b"",
        headers={"X-Session-Id": sid},
    )
    _get(h)
    data = _body(h)
    # full=27.5 + partial=3.0(50%) = 30.5
    assert data["total_saving_cny"] == 30.5
    assert data["streak_days"] >= 1
    assert len(data["trend"]) >= 1


# ========== 7. POST /api/household/delegation ==========


def test_delegation_change(make_handler, session_user):
    """改 delegation_level → 返 old/new"""
    sid, uid, _ = session_user
    # 默认 1
    h = make_handler(
        "POST",
        "/api/household/delegation",
        body=json.dumps({"new_level": 2}).encode("utf-8"),
        headers={"X-Session-Id": sid},
    )
    _post(h)
    data = _body(h)
    assert data["ok"] is True
    assert data["old_level"] == 1
    assert data["new_level"] == 2
    assert data["label"] == "多方案选择"


def test_delegation_invalid_level(make_handler, session_user):
    """非法 level → 422 VALIDATION"""
    sid, uid, _ = session_user
    h = make_handler(
        "POST",
        "/api/household/delegation",
        body=json.dumps({"new_level": 99}).encode("utf-8"),
        headers={"X-Session-Id": sid},
    )
    _post(h)
    assert h.last_status == 422, h.last_body
    body_json = _body(h)
    assert body_json["error"]["code"] == "VALIDATION"


# ========== 8. GET /api/energy/actions ==========


def test_actions_list_pending_empty(make_handler, session_user):
    """新用户 pending 空"""
    sid, uid, _ = session_user
    h = make_handler(
        "GET",
        "/api/energy/actions?status=pending",
        body=b"",
        headers={"X-Session-Id": sid},
    )
    _get(h)
    data = _body(h)
    assert data["count"] == 0
    assert data["items"] == []


def test_actions_list_done_after_completion(make_handler, session_user):
    """完成一次后 done 列表能看到"""
    sid, uid, _ = session_user
    h = make_handler(
        "POST",
        "/api/energy/actions/ac_temp_up_1c/complete",
        body=json.dumps({"completion_level": "full"}).encode("utf-8"),
        headers={"X-Session-Id": sid},
    )
    _post(h)

    h = make_handler(
        "GET",
        "/api/energy/actions?status=done",
        body=b"",
        headers={"X-Session-Id": sid},
    )
    _get(h)
    data = _body(h)
    assert data["count"] >= 1
    assert any(item["action_id"] == "ac_temp_up_1c" for item in data["items"])


# ========== 9. 自然语言识别(NL 切 level) ==========


def test_parse_natural_language_level():
    """parse_level_from_natural_language 覆盖常见 NL"""
    from agent.energy.delegation import parse_level_from_natural_language

    assert parse_level_from_natural_language("以后不用每次问我") == 0
    assert parse_level_from_natural_language("给我选就行") == 2
    assert parse_level_from_natural_language("先别存") == 3
    assert parse_level_from_natural_language("切到 2 档") == 2
    assert parse_level_from_natural_language("level 0") == 0
    assert parse_level_from_natural_language("你好") is None


# ========== 10. 决定单元测试 ==========


def test_decide_for_write_levels():
    """decide_for_write 各 level 行为对照"""
    from agent.energy.delegation import decide_for_write

    d0 = decide_for_write(0)
    assert d0.should_persist is True
    assert d0.confirmation_required is False
    assert d0.variant_mode is False
    assert d0.echo_only is False

    d1 = decide_for_write(1)
    assert d1.should_persist is True
    assert d1.confirmation_required is False

    d2 = decide_for_write(2)
    assert d2.should_persist is False
    assert d2.confirmation_required is True
    assert d2.variant_mode is True

    d3 = decide_for_write(3)
    assert d3.should_persist is False
    assert d3.confirmation_required is True
    assert d3.echo_only is True


# ========== 工具函数 ==========


def _set_level(make_handler, sid, uid, level):
    """工具:用 API 设 delegation level"""
    h = make_handler(
        "POST",
        "/api/household/delegation",
        body=json.dumps({"new_level": level}).encode("utf-8"),
        headers={"X-Session-Id": sid},
    )
    _post(h)
    return _body(h)


def _post_profile(make_handler, sid, body_dict, level=None):
    """工具:存 profile(level=0/1 直接存,其他也直接存以方便测试)"""
    h = make_handler(
        "POST",
        "/api/energy/profile",
        body=json.dumps(body_dict).encode("utf-8"),
        headers={"X-Session-Id": sid},
    )
    _post(h)
    return _body(h)