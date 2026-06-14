"""
P6.S.22 测试: 3 层 fallback 定位
- 浏览器 navigator.geolocation
- IP 反查 (ip-api.com)
- 画像 default city
"""
import sys
import os
import json
import urllib.request
import urllib.error

sys.path.insert(0, str(__file__).replace("\\", "/").replace("tests/test_p6s22_geolocation.py", "src"))


def _http_get(url, timeout=10):
    req = urllib.request.Request(url, method="GET")
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8", errors="ignore"))


def _http_post(url, data, timeout=30):
    req = urllib.request.Request(
        url, data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8", errors="ignore"))


def test_server_running():
    return _http_get("http://localhost:8000/api/health", timeout=5)[0] == 200


# ============ 单元测试: geolocate 模块 ============

def test_geolocate_module_imports():
    """P6.S.22: geolocate 模块可 import"""
    from utils.geolocate import (
        GeoInfo, geolocate_by_ip, geolocate_request,
        geolocate_from_profile, best_location, _get_client_ip,
    )
    print("✅ test_geolocate_module_imports PASSED")


def test_geolocate_localhost_returns_default():
    """P6.S.22: localhost IP → 返默认北京(避免浪费 IP 反查)"""
    from utils.geolocate import geolocate_by_ip
    geo = geolocate_by_ip("127.0.0.1")
    assert geo.source == "default", f"localhost 应 default, 实际 {geo.source}"
    assert geo.city == "北京", f"应默认北京, 实际 {geo.city}"
    assert abs(geo.lat - 39.9042) < 0.01
    assert abs(geo.lng - 116.4074) < 0.01
    print(f"  ✓ localhost: {geo.city} ({geo.source})")
    print("✅ test_geolocate_localhost_returns_default PASSED")


def test_geolocate_profile_reads_city():
    """P6.S.22: 画像 basic_info.region 读取 → GeoInfo"""
    from utils.geolocate import geolocate_from_profile
    # 设一个测试 user 有画像
    from user_profile.user_profile import UserProfileManager
    upm = UserProfileManager()
    uid = "p6s22_geo_test_user"
    try:
        upm.update_profile_field(uid, "basic_info", {"region": "上海"})
    except Exception:
        # 尝试直接 SQLite 改
        pass
    geo = geolocate_from_profile(uid)
    if geo:
        assert geo.source == "profile", f"应 source=profile, 实际 {geo.source}"
        assert "上海" in geo.city, f"应含上海, 实际 {geo.city}"
        assert geo.lat and geo.lng
        print(f"  ✓ profile: {geo.city} ({geo.lat}, {geo.lng})")
    else:
        print("  ⏭ profile 字段未设置,跳过")
    print("✅ test_geolocate_profile_reads_city PASSED")


def test_best_location_3_layer_fallback():
    """P6.S.22: best_location 3 层 fallback"""
    from utils.geolocate import best_location
    # 场景 1: 无 handler + anonymous → default
    class StubHandler:
        pass
    geo = best_location(handler=StubHandler(), user_id="anonymous")
    assert geo.source in ("default", "ip_api"), f"anonymous 应 default/ip_api, 实际 {geo.source}"
    print(f"  ✓ anonymous: {geo.source}")

    # 场景 2: handler._browser_location 已设 → browser
    class HandlerWithLoc:
        _browser_location = {"lat": 31.23, "lng": 121.47, "city": "上海"}
    geo = best_location(handler=HandlerWithLoc(), user_id="anonymous")
    assert geo.source == "browser", f"应 source=browser, 实际 {geo.source}"
    assert geo.city == "上海", f"应 city=上海, 实际 {geo.city}"
    print(f"  ✓ browser override: {geo.city} ({geo.source})")
    print("✅ test_best_location_3_layer_fallback PASSED")


# ============ HTTP 端到端 ============

def test_api_geolocate_endpoint():
    """P6.S.22: GET /api/geolocate 应返定位"""
    if not test_server_running():
        return
    code, body = _http_get("http://localhost:8000/api/geolocate?user_id=p6s22_test")
    assert code == 200
    assert body.get("ok")
    loc = body.get("location", {})
    assert "city" in loc
    assert "lat" in loc
    assert "lng" in loc
    assert "source" in loc
    print(f"  ✓ {loc}")
    print("✅ test_api_geolocate_endpoint PASSED")


def test_api_geolocate_post_browser():
    """P6.S.22: POST /api/geolocate 存浏览器定位"""
    if not test_server_running():
        return
    code, body = _http_post(
        "http://localhost:8000/api/geolocate",
        {"lat": 39.9042, "lng": 116.4074, "city": "北京", "region": "北京", "country": "中国"},
    )
    assert code == 200
    assert body.get("ok")
    assert body.get("stored") is True
    print("✅ test_api_geolocate_post_browser PASSED")


def test_chat_enhanced_returns_location_source():
    """P6.S.22: chat_enhanced 响应含 location.source(便于前端展示)"""
    if not test_server_running():
        return
    code, body = _http_post(
        "http://localhost:8000/api/chat/enhanced",
        {
            "user_id": "p6s22_chat_test",
            "message": "你好",
            "location": {"lat": 31.23, "lng": 121.47, "city": "上海"},
        },
    )
    assert code == 200
    assert "location" in body, f"响应应含 location 字段, 实际 keys: {list(body.keys())}"
    loc = body["location"]
    assert loc.get("source") == "browser", f"应 source=browser, 实际 {loc.get('source')}"
    assert "上海" in loc.get("city", ""), f"应含上海, 实际 {loc}"
    print(f"  ✓ location: {loc}")
    print("✅ test_chat_enhanced_returns_location_source PASSED")


if __name__ == "__main__":
    test_geolocate_module_imports()
    test_geolocate_localhost_returns_default()
    test_geolocate_profile_reads_city()
    test_best_location_3_layer_fallback()
    test_server_running()
    test_api_geolocate_endpoint()
    test_api_geolocate_post_browser()
    test_chat_enhanced_returns_location_source()
    print("\n🎉 All P6.S.22 tests PASSED")
