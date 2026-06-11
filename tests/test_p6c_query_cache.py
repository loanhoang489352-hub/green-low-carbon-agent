"""
P6.C Query Cache 单元测试

覆盖:
1. 缓存键标准化:query 大小写 / 标点 / 空白统一
2. 画像指纹:同一画像相同指纹;不同画像不同指纹
3. get/set/invalidate 基本流程
4. TTL 过期
5. 画像变更 → invalidate
6. 命中率 metrics
7. SQLite 持久化(跨进程)
"""
import sys
import time
import uuid
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / 'src'))

import pytest


@pytest.fixture
def tmp_cache(monkeypatch, tmp_path):
    """每个测试用独立 DB 避免污染"""
    from agent.cache import query_cache as qc_module
    db_path = tmp_path / f"query_cache_{uuid.uuid4().hex[:6]}.db"
    cache = qc_module.QueryCache(db_path=db_path, ttl=2.0)
    return cache, db_path


# ========== 1. 缓存键标准化 ==========

def test_normalize_query_strips_whitespace_and_case():
    from agent.cache.query_cache import _normalize_query
    assert _normalize_query("Hello World") == _normalize_query("  hello   world  ")
    assert _normalize_query("Hello") == _normalize_query("hello")
    assert _normalize_query("Hello!") == _normalize_query("hello")
    assert _normalize_query("Hello?") == _normalize_query("hello")
    # 中文
    assert _normalize_query("  你好  ") == _normalize_query("你好")
    # 标点
    assert _normalize_query("北京,周末去哪儿?") == _normalize_query("北京周末去哪儿")


def test_profile_fingerprint_changes_with_region():
    from agent.cache.query_cache import _profile_fingerprint
    p1 = {"basic_info": {"region": "北京"}, "eco_profile": {}}
    p2 = {"basic_info": {"region": "上海"}, "eco_profile": {}}
    assert _profile_fingerprint(p1) != _profile_fingerprint(p2)


def test_profile_fingerprint_stable_for_same_profile():
    from agent.cache.query_cache import _profile_fingerprint
    p = {
        "basic_info": {"region": "北京"},
        "eco_profile": {
            "primary_interests": ["low_carbon_travel"],
            "knowledge_level": "intermediate",
            "behavior_stage": "意向",
        },
        "behavior": {"suggestion_intensity": "中"},
    }
    fp1 = _profile_fingerprint(p)
    fp2 = _profile_fingerprint(p)
    assert fp1 == fp2


# ========== 2. 基本 get/set/invalidate ==========

def test_cache_set_and_get(tmp_cache):
    cache, _ = tmp_cache
    profile = {"basic_info": {"region": "北京"}, "eco_profile": {}}
    cache.set("你好", "u1", profile, "你好,有什么可以帮你", ["建议 1", "建议 2"])
    got = cache.get("你好", "u1", profile)
    assert got is not None
    assert got["message"] == "你好,有什么可以帮你"
    assert got["suggestions"] == ["建议 1", "建议 2"]


def test_cache_miss_returns_none(tmp_cache):
    cache, _ = tmp_cache
    profile = {"basic_info": {"region": "北京"}, "eco_profile": {}}
    assert cache.get("从没缓存过的 query", "u1", profile) is None


def test_cache_different_users_isolated(tmp_cache):
    cache, _ = tmp_cache
    profile = {"basic_info": {"region": "北京"}, "eco_profile": {}}
    cache.set("你好", "u1", profile, "U1 的回答", [])
    assert cache.get("你好", "u2", profile) is None
    assert cache.get("你好", "u1", profile)["message"] == "U1 的回答"


def test_cache_invalidate_user(tmp_cache):
    cache, _ = tmp_cache
    profile = {"basic_info": {"region": "北京"}, "eco_profile": {}}
    cache.set("q1", "u1", profile, "m1", [])
    cache.set("q2", "u1", profile, "m2", [])
    cache.set("q3", "u2", profile, "m3", [])
    cleared = cache.invalidate("u1")
    assert cleared == 2
    assert cache.get("q1", "u1", profile) is None
    assert cache.get("q2", "u1", profile) is None
    # u2 不受影响
    assert cache.get("q3", "u2", profile)["message"] == "m3"


# ========== 3. TTL 过期 ==========

def test_cache_expires_after_ttl(tmp_cache):
    cache, _ = tmp_cache
    profile = {"basic_info": {"region": "北京"}, "eco_profile": {}}
    cache.set("ttl_test", "u1", profile, "msg", [])
    # TTL=2s,1s 后命中
    time.sleep(1.0)
    assert cache.get("ttl_test", "u1", profile) is not None
    # 2.5s 后过期
    time.sleep(1.5)
    assert cache.get("ttl_test", "u1", profile) is None


def test_cleanup_expired_removes_old_entries(tmp_cache):
    cache, _ = tmp_cache
    profile = {"basic_info": {"region": "北京"}, "eco_profile": {}}
    cache.set("e1", "u1", profile, "m1", [])
    cache.set("e2", "u1", profile, "m2", [])
    time.sleep(2.5)
    cleared = cache.cleanup_expired()
    assert cleared == 2
    stats = cache.stats()
    assert stats["size"] == 0


# ========== 4. 画像指纹变化 → 缓存失效 ==========

def test_cache_miss_when_profile_changes(tmp_cache):
    """画像变化(region/interests/knowledge_level 等)应视为不同 cache key"""
    cache, _ = tmp_cache
    p1 = {"basic_info": {"region": "北京"}, "eco_profile": {"primary_interests": []}}
    p2 = {"basic_info": {"region": "上海"}, "eco_profile": {"primary_interests": []}}
    cache.set("你好", "u1", p1, "北京回答", [])
    # 同 query + 同 user + 不同 region → 视为新查询
    assert cache.get("你好", "u1", p2) is None
    # 原画像仍命中
    assert cache.get("你好", "u1", p1)["message"] == "北京回答"


# ========== 5. metrics ==========

def test_stats_hit_rate(tmp_cache):
    cache, _ = tmp_cache
    cache.reset_metrics()
    profile = {"basic_info": {"region": "北京"}, "eco_profile": {}}
    # 3 miss + 2 hit
    cache.get("q1", "u1", profile)  # miss
    cache.get("q2", "u1", profile)  # miss
    cache.get("q3", "u1", profile)  # miss
    cache.set("q1", "u1", profile, "m1", [])
    cache.set("q2", "u1", profile, "m2", [])
    cache.get("q1", "u1", profile)  # hit
    cache.get("q2", "u1", profile)  # hit
    stats = cache.stats()
    assert stats["hits"] == 2
    assert stats["misses"] == 3
    assert stats["sets"] == 2
    assert abs(stats["hit_rate"] - 0.4) < 0.01  # 2/(2+3) = 0.4


def test_stats_invalidations_counter(tmp_cache):
    cache, _ = tmp_cache
    cache.reset_metrics()
    profile = {"basic_info": {"region": "北京"}, "eco_profile": {}}
    for i in range(5):
        cache.set(f"q{i}", "u1", profile, f"m{i}", [])
    cache.invalidate("u1")
    stats = cache.stats()
    assert stats["invalidations"] == 5
    assert stats["size"] == 0


# ========== 6. SQLite 持久化 ==========

def test_cache_persists_across_instances(tmp_path):
    """新 QueryCache 实例打开同一 DB → 读到旧数据"""
    from agent.cache.query_cache import QueryCache
    db_path = tmp_path / "persist_test.db"
    profile = {"basic_info": {"region": "北京"}, "eco_profile": {}}

    c1 = QueryCache(db_path=db_path, ttl=60.0)
    c1.set("持久化测试", "u1", profile, "保存的内容", ["s1"])
    del c1

    c2 = QueryCache(db_path=db_path, ttl=60.0)
    got = c2.get("持久化测试", "u1", profile)
    assert got is not None
    assert got["message"] == "保存的内容"


# ========== 7. /api/metrics 接入验证 ==========

def test_metrics_endpoint_exposes_query_cache():
    """P5-B /api/metrics 应包含 query_cache 字段"""
    from server.app import RoutedRequestHandler
    from server.router import reset_registry, get_registry
    from server.routers import register_all_routes
    import json as json_mod

    reset_registry()
    register_all_routes(get_registry())

    from io import BytesIO
    handler = RoutedRequestHandler.__new__(RoutedRequestHandler)
    handler.path = "/api/metrics"
    handler.headers = {}
    handler.command = "GET"
    handler.request_version = "HTTP/1.1"
    handler.rfile = BytesIO(b"")
    response_buffer = BytesIO()
    handler.wfile = response_buffer
    handler.last_status = None
    handler.last_body = b""

    def instance_send_json(data, status=200):
        handler.last_status = status
        handler.last_body = json_mod.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
    handler.send_json = instance_send_json
    handler.send_response = lambda s: setattr(handler, "last_status", s)
    handler.send_header = lambda k, v: None
    handler.end_headers = lambda: None
    handler._read_body = lambda: ""
    handler._cors_origin = lambda: "*"
    handler.log_message = lambda fmt, *a: None

    RoutedRequestHandler.do_GET(handler)
    assert handler.last_status == 200
    body = json_mod.loads(handler.last_body.decode("utf-8"))
    assert "query_cache" in body["metrics"], "P6.C: /api/metrics 应包含 query_cache 字段"
    qc = body["metrics"]["query_cache"]
    # 字段完整性
    for key in ("hits", "misses", "sets", "invalidations", "hit_rate", "size", "ttl_seconds"):
        assert key in qc, f"P6.C: query_cache 缺少字段 {key}"
