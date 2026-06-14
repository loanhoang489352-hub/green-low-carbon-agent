"""
P6.S.22: 地理位置定位 — Server 端 IP 反查

提供 3 层 fallback(上游选择):
  1. 浏览器 navigator.geolocation(前端)
  2. Server 端 IP 反查(本模块)
  3. 用户画像 default city(已有,本模块读 profile.region)

外部 API: ip-api.com (免费,45 req/min,免 key)
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

import urllib.request
import urllib.parse

_logger = logging.getLogger(__name__)

# 简单进程内缓存(IP -> GeoInfo),避免每次请求都打外部
_CACHE: Dict[str, Tuple[float, "GeoInfo"]] = {}
_CACHE_TTL = 3600  # 1 小时
_LOCK = threading.Lock()


@dataclass
class GeoInfo:
    """P6.S.22: 定位结果"""
    city: str = ""               # 城市
    region: str = ""              # 省份
    country: str = ""             # 国家
    lat: float = 0.0             # 纬度
    lng: float = 0.0             # 经度
    ip: str = ""                 # 来源 IP
    source: str = "unknown"      # "ip_api" / "profile" / "browser" / "default"
    cached: bool = False          # 是否来自缓存

    def to_dict(self) -> Dict[str, Any]:
        return {
            "city": self.city,
            "region": self.region,
            "country": self.country,
            "lat": self.lat,
            "lng": self.lng,
            "ip": self.ip,
            "source": self.source,
            "cached": self.cached,
        }


def _get_client_ip(handler) -> str:
    """P6.S.22: 从 handler 提取客户端 IP(支持 X-Forwarded-For)"""
    # 优先 X-Forwarded-For(反代场景)
    if hasattr(handler, "headers"):
        xff = handler.headers.get("X-Forwarded-For", "")
        if xff:
            # 取第一个 IP
            return xff.split(",")[0].strip()
    # 否则用 client_address
    try:
        if hasattr(handler, "client_address") and handler.client_address:
            return handler.client_address[0] or "127.0.0.1"
    except Exception:
        pass
    return "127.0.0.1"


def _query_ip_api(ip: str) -> Optional[GeoInfo]:
    """P6.S.22: 调 ip-api.com 反查 IP 地理位置"""
    # 跳过本地 / 私有 IP
    if ip.startswith(("127.", "10.", "192.168.", "172.16.", "::1", "localhost")):
        return None
    try:
        url = f"http://ip-api.com/json/{urllib.parse.quote(ip)}?lang=zh-CN"
        req = urllib.request.Request(url, headers={"User-Agent": "green-agent/2.0"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        if data.get("status") != "success":
            return None
        return GeoInfo(
            city=data.get("city", ""),
            region=data.get("regionName", ""),
            country=data.get("country", ""),
            lat=float(data.get("lat", 0.0) or 0.0),
            lng=float(data.get("lon", 0.0) or 0.0),
            ip=ip,
            source="ip_api",
            cached=False,
        )
    except Exception as e:
        _logger.debug("[P6.S.22] ip-api 查询失败 %s: %s", ip, e)
        return None


def geolocate_by_ip(ip: str) -> GeoInfo:
    """P6.S.22: 公开接口 — IP 反查(带缓存)

    失败返默认北京(兜底,让出行规划有 origin)
    """
    if not ip or ip == "127.0.0.1":
        return GeoInfo(city="北京", country="中国", lat=39.9042, lng=116.4074,
                        ip=ip, source="default")
    with _LOCK:
        cached = _CACHE.get(ip)
        if cached and (time.time() - cached[0]) < _CACHE_TTL:
            geo = cached[1]
            geo.cached = True
            return geo
    geo = _query_ip_api(ip)
    if geo is None:
        # 失败兜底北京
        geo = GeoInfo(city="北京", country="中国", lat=39.9042, lng=116.4074, ip=ip, source="default")
    with _LOCK:
        _CACHE[ip] = (time.time(), geo)
    return geo


def geolocate_request(handler) -> GeoInfo:
    """P6.S.22: 公开接口 — 从 handler 自动提取 IP + 反查

    给 app.py 的 _dispatch 在每个请求前调,缓存到 handler.geolocate
    """
    if hasattr(handler, "geolocate"):
        return handler.geolocate
    ip = _get_client_ip(handler)
    geo = geolocate_by_ip(ip)
    try:
        handler.geolocate = geo
    except Exception:
        pass
    return geo


def geolocate_from_profile(user_id: str) -> Optional[GeoInfo]:
    """P6.S.22: 从用户画像读 default city"""
    if not user_id or user_id == "anonymous":
        return None
    try:
        from user_profile.user_profile import UserProfileManager
        upm = UserProfileManager()
        profile = upm.get_profile(user_id)
        basic = profile.get("basic_info", {}) or {}
        city = basic.get("region") or basic.get("city")
        if not city or city in ("未知", "其他"):
            return None
        # 默认坐标(主要城市)
        CITY_COORDS = {
            "北京": (39.9042, 116.4074), "上海": (31.2304, 121.4737),
            "广州": (23.1291, 113.2644), "深圳": (22.5431, 114.0579),
            "杭州": (30.2741, 120.1551), "成都": (30.5728, 104.0668),
            "武汉": (30.5928, 114.3055), "西安": (34.3416, 108.9398),
        }
        for name, (lat, lng) in CITY_COORDS.items():
            if name in city:
                return GeoInfo(city=name, country="中国", lat=lat, lng=lng,
                                ip="profile", source="profile", cached=False)
        return None
    except Exception as e:
        _logger.debug("[P6.S.22] profile 读 region 失败: %s", e)
        return None


def best_location(handler=None, user_id: str = None) -> GeoInfo:
    """P6.S.22: 公开接口 — 3 层 fallback 选最优定位

    优先级: 浏览器/前端传入 > 用户画像 city > IP 反查
    浏览器传入的 location 暂存 handler.browser_location(handler 设的)
    """
    # 1. 浏览器传入(前端已发,放在 handler 或 data 里)
    if handler is not None and hasattr(handler, "_browser_location"):
        bl = handler._browser_location
        if bl and bl.get("lat") and bl.get("lng"):
            return GeoInfo(
                city=bl.get("city", ""),
                region=bl.get("region", ""),
                country=bl.get("country", "中国"),
                lat=float(bl["lat"]),
                lng=float(bl["lng"]),
                ip="browser",
                source="browser",
                cached=False,
            )
    # 2. 用户画像 city
    if user_id:
        gp = geolocate_from_profile(user_id)
        if gp:
            return gp
    # 3. IP 反查
    if handler is not None:
        return geolocate_request(handler)
    return GeoInfo(city="北京", country="中国", lat=39.9042, lng=116.4074, source="default")
