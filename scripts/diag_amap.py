# -*- coding: utf-8 -*-
"""
诊断高德地图 API —— 定位为何出行规划显示"高德不可用/估算数据"。

直接调高德:
  1) /v3/geocode/geo  地理编码(地址→坐标)
  2) /v3/direction/transit/integrated  公交换乘
打印真实 status/info/infocode,据此判断:
  - status=1 且 geocodes/transits 非空 → 高德正常,问题在别处
  - status=0 + 关键字(CUQPS/QUOTA/DAILY) → 配额/限流
  - status=0 + INVALID_USER_KEY → key 无效/未授权
  - status=0 + NO_DATA → 地址解析不出
  - network error → 网络/代理不通
用法:  python scripts/diag_amap.py
"""
import os
import json
import urllib.request
import urllib.parse
from pathlib import Path

root = Path(__file__).resolve().parent.parent
env_file = root / ".env"
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

key = os.environ.get("GAODE_API_KEY", "")
print(f"高德 key: {(key[:6] + '...' + key[-4:]) if key else '(未找到 GAODE_API_KEY)'}")


def get(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


print("\n[1] 地理编码 —— 几个写法,看哪个能解析出坐标:")
for addr, city in [("北京西单", None), ("北京市西城区西单", None), ("西单", "北京")]:
    q = {"key": key, "address": addr}
    if city:
        q["city"] = city
    url = "https://restapi.amap.com/v3/geocode/geo?" + urllib.parse.urlencode(q)
    d = get(url)
    gc = d.get("geocodes") or []
    print(f"  地址={addr!r} city={city} -> status={d.get('status')} info={d.get('info')} "
          f"infocode={d.get('infocode')} geocodes={len(gc)}")
    if gc:
        print(f"      首个坐标: {gc[0].get('location')} ({gc[0].get('formatted_address', '')})")

print("\n[2] 公交换乘 —— 北京西单 → 国贸:")
src = get("https://restapi.amap.com/v3/geocode/geo?" +
          urllib.parse.urlencode({"key": key, "address": "北京市西城区西单"}))
src_coord = src["geocodes"][0]["location"] if src.get("status") == "1" and src.get("geocodes") else None
print(f"  西单坐标: {src_coord}")
dst = get("https://restapi.amap.com/v3/geocode/geo?" +
          urllib.parse.urlencode({"key": key, "address": "北京市朝阳区国贸"}))
dst_coord = dst["geocodes"][0]["location"] if dst.get("status") == "1" and dst.get("geocodes") else None
print(f"  国贸坐标: {dst_coord}")
if src_coord and dst_coord:
    url = ("https://restapi.amap.com/v3/direction/transit/integrated?" +
           urllib.parse.urlencode({"key": key, "origin": src_coord, "destination": dst_coord,
                                   "city": "北京", "datatype": "transit"}))
    d = get(url)
    transits = (d.get("route", {}) or {}).get("transits", []) if d.get("status") == "1" else []
    print(f"  transit status={d.get('status')} info={d.get('info')} infocode={d.get('infocode')} transits={len(transits)}")
    if d.get("status") != "1":
        print("  -> 高德公交路线未成功, 原因请见上方 info/infocode")
    elif transits:
        print(f"  -> 高德正常, 返回 {len(transits)} 条公交方案")
    else:
        print("  -> status=1 但无 transits(可能两地址太近/无直达公交)")

print("\n按 info/infocode 判断:")
print("  CUQPS / QUOTA / USER_DAILY_QUERY_OVER_LIMIT -> 配额/限流, 换 key 或等配额恢复")
print("  INVALID_USER_KEY / USERKEY_PLAT_NOMATCH -> key 无效/平台未匹配, 检查 .env 的 GAODE_API_KEY")
print("  NO_DATA / 无 geocodes -> 地址解析不出, 换更完整地址")
print("  error: <网络错误> -> 网络/代理到 restapi.amap.com 不通")
