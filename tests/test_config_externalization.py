"""
验证 P2-剩余: 硬编码配置外部化
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def test_cities_config_loaded():
    """cities.yaml 应该被加载"""
    from config_loader import get_major_cities, get_default_city
    cities = get_major_cities()
    assert "北京" in cities
    assert "上海" in cities
    assert len(cities) >= 5
    print(f"✅ test_cities_config_loaded PASSED: {len(cities)} cities, default={get_default_city()}")


def test_sources_config_loaded():
    """sources.yaml 应该被加载"""
    from config_loader import get_policy_sources
    sources = get_policy_sources()
    assert len(sources) >= 1
    for s in sources:
        assert "name" in s
        assert "url" in s
        assert s["url"].startswith("http")
        assert s.get("enabled", True)
    print(f"✅ test_sources_config_loaded PASSED: {len(sources)} sources")


def test_query_understanding_uses_config():
    """query_understanding 应从 config 加载城市列表"""
    from agent.query_understanding import LocationInfo
    info = LocationInfo("我想去上海旅游")
    assert info.city == "上海", f"应识别上海,实际 {info.city}"
    print(f"✅ test_query_understanding_uses_config PASSED: detected '{info.city}'")


def test_policy_updater_uses_config():
    """policy/updater.PolicyUpdater.POLICY_SOURCES 应来自 config"""
    from policy.updater import PolicyUpdater
    sources = PolicyUpdater.POLICY_SOURCES
    assert len(sources) >= 1
    for s in sources:
        assert "url" in s
        assert s["url"].startswith("http")
        # 补默认 type/check_interval_hours
        assert "type" in s
        assert "check_interval_hours" in s
    print(f"✅ test_policy_updater_uses_config PASSED: {len(sources)} sources with defaults")


def test_cache_clears_on_reload():
    """clear_cache 后能重新加载"""
    from config_loader import get_major_cities, clear_cache
    cities1 = get_major_cities()
    clear_cache()
    cities2 = get_major_cities()
    assert cities1 == cities2
    print("✅ test_cache_clears_on_reload PASSED")


if __name__ == "__main__":
    test_cities_config_loaded()
    test_sources_config_loaded()
    test_query_understanding_uses_config()
    test_policy_updater_uses_config()
    test_cache_clears_on_reload()
    print("\n🎉 all config externalization tests passed")
