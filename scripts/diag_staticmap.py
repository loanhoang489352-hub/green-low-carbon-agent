# -*- coding: utf-8 -*-
r"""
诊断高德静态地图 API —— 定位为何出行地图没有真实底图。

直接调 restapi.amap.com/v3/staticmap,打印 HTTP 状态 / Content-Type / 返回体前 200 字节。
若返回 image/* → amap 正常,问题在 /api/staticmap 代理;若 error JSON → 参数格式不对。

用法:
    python scripts/diag_staticmap.py
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
print(f"高德 key: {(key[:6] + '...' + key[-4:]) if key else '(未找到)'}")

# 西单→国贸 真实坐标(lng,lat)
lng1, lat1 = 116.373439, 39.910918
lng2, lat2 = 116.458850, 39.909860
center_lng = (lng1 + lng2) / 2
center_lat = (lat1 + lat2) / 2

# 一条折线(西单→国贸中段,示意)
poly = "116.373439,39.910918;116.40,39.91;116.42,39.9098;116.44,39.9099;116.458850,39.909860"


def build(location, zoom, size, paths="", markers="", scale="1"):
    params = [("key", key), ("location", location), ("zoom", zoom), ("size", size), ("scale", scale)]
    # markers 允许 ";" 分隔 → 拆成多个独立 markers 参数(amap 每个 markers 是同一样式组)
    if markers:
        for part in str(markers).split(";"):
            part = part.strip()
            if part:
                params.append(("markers", part))
    if paths:
        params.append(("paths", paths))
    url = "https://restapi.amap.com/v3/staticmap?" + urllib.parse.urlencode(params)
    return url


def test(label, url):
    print(f"\n[{label}]")
    print("  URL:", url[:160] + "...")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "green-agent/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            body = r.read()
            ctype = r.headers.get("Content-Type", "?")
            status = r.status
        print(f"  status={status} Content-Type={ctype} 大小={len(body)}B")
        if "image" in ctype:
            print("  ✅ amap 返回图片(静态图可用)")
        else:
            print("  ⚠️ amap 返回非图片,body前200:", body[:200])
    except Exception as e:
        print(f"  ❌ 请求失败: {type(e).__name__}: {e}")


# 纯中心图(无折线) —— 最简,验证 key/基础参数
test("基础(仅 center+zoom)", build(f"{center_lng},{center_lat}", "12", "800*500", "", ""))
# 带 markers A/B —— 用 ";" 拆成两个独立 markers 参数(修复后代理的写法)
test("markers 拆两参数(A/B)", build(f"{center_lng},{center_lat}", "12", "800*500",
                                      "", f"mid,0x11998e,A:{lng1},{lat1};mid,0xef4444,B:{lng2},{lat2}"))
# 单条折线(加 multi0)
test("单折线(multi0:)", build(f"{center_lng},{center_lat}", "12", "800*500", "6,0x11998e,1,multi0:" + poly))
# 两条折线(用 | 连接,各带 multi0)
test("两条折线(|连接multi0)", build(f"{center_lng},{center_lat}", "12", "800*500",
                                      "6,0x11998e,1,multi0:" + poly + "|3,0x9ca3af,1,multi0:" + poly))
# 完整: markers 拆两参数 + 两条折线
test("完整(markers拆分+双边线)", build(f"{center_lng},{center_lat}", "12", "800*500",
                                          "6,0x11998e,1,multi0:" + poly + "|3,0x9ca3af,1,multi0:" + poly,
                                          f"mid,0x11998e,A:{lng1},{lat1};mid,0xef4444,B:{lng2},{lat2}"))

print("\n判断: 哪个标 ✅ image → 用该参数格式改 /api/staticmap 代理;都 ❌ → 检查 GAODE_API_KEY 是否开通静态图服务")
