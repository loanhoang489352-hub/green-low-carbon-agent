"""
YAML 配置加载器
从 config/ 目录加载外部化配置,提供缓存
"""

from functools import lru_cache
from typing import Any, Dict, List

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore

from paths import CONFIG_DIR


def _load_yaml(name: str) -> Dict[str, Any]:
    """从 config 目录加载 YAML 文件"""
    path = CONFIG_DIR / name
    if not path.exists():
        return {}
    if yaml is None:
        return {"_error": f"PyYAML 未安装,无法加载 {name}"}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data


@lru_cache(maxsize=8)
def get_cities_config() -> Dict[str, Any]:
    """获取城市配置(缓存)"""
    return _load_yaml("cities.yaml")


@lru_cache(maxsize=8)
def get_sources_config() -> Dict[str, Any]:
    """获取政策源配置(缓存)"""
    return _load_yaml("sources.yaml")


def get_major_cities() -> List[str]:
    """获取主要城市列表"""
    return list(get_cities_config().get("cities", {}).get("major", []))


def get_default_city() -> str:
    """获取默认城市"""
    return str(get_cities_config().get("cities", {}).get("default", "北京"))


def get_policy_sources() -> List[Dict[str, Any]]:
    """获取启用的政策源列表"""
    sources = get_sources_config().get("policy_sources", [])
    return [s for s in sources if s.get("enabled", True)]


def clear_cache() -> None:
    """清空缓存(配置热重载时使用)"""
    get_cities_config.cache_clear()
    get_sources_config.cache_clear()
