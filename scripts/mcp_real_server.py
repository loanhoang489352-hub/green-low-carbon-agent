# -*- coding: utf-8 -*-
r"""
Real MCP Server —— 真实数据源的 MCP 工具(替代 mock 测试桩)

通过 stdin JSON-RPC(每行一个 JSON)暴露 4 个**真实数据**工具:
  - weather(Open-Meteo)  真实天气(温度/风速/天气码/描述)
  - carbon_calc          碳排计算(距离 × 方式系数)
  - geocode(高德)        地址 → 坐标(需 GAODE_API_KEY)
  - transit_route(高德)  公交换乘(需 GAODE_API_KEY)

启动: python scripts/mcp_real_server.py
依赖: 环境变量 GAODE_API_KEY(高德)、网络可达 Open-Meteo / restapi.amap.com
"""
import json
import os
import sys
import urllib.request
import urllib.parse

# 碳排系数(kg CO2 / km)
_FACTORS = {"car": 0.21, "bus": 0.08, "metro": 0.05, "transit": 0.05, "cycling": 0.0, "walking": 0.0}


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "green-agent-mcp/2.0"})
    with urllib.request.urlopen(req, timeout=6) as r:
        return json.loads(r.read().decode("utf-8", errors="ignore"))


def _weather(city):
    geo = _get("https://geocoding-api.open-meteo.com/v1/search?name=" + urllib.parse.quote(city) + "&count=1&language=zh")
    results = geo.get("results") or []
    if not results:
        return {"error": f"未找到城市 {city}", "city": city}
    r0 = results[0]
    w = _get(f"https://api.open-meteo.com/v1/forecast?latitude={r0['latitude']}&longitude={r0['longitude']}&current_weather=true")
    cw = w.get("current_weather") or {}
    code = cw.get("weathercode", 0)
    # WMO weather code → 中文(简化)
    cn = {0: "晴", 1: "基本晴", 2: "多云", 3: "阴", 45: "雾", 48: "雾凇",
          51: "毛毛雨", 53: "毛毛雨", 55: "毛毛雨", 61: "小雨", 63: "中雨", 65: "大雨",
          71: "小雪", 73: "中雪", 75: "大雪", 80: "阵雨", 95: "雷暴", 99: "强雷暴"}
    return {
        "city": city,
        "temp_c": cw.get("temperature"),
        "wind_kmh": cw.get("windspeed"),
        "weathercode": code,
        "description": cn.get(code, f"代码{code}"),
        "source": "open-meteo",
    }


def _geocode(address, city):
    key = os.environ.get("GAODE_API_KEY", "")
    if not key:
        return {"error": "GAODE_API_KEY 未配置"}
    params = {"key": key, "address": address}
    if city:
        params["city"] = city
    d = _get("https://restapi.amap.com/v3/geocode/geo?" + urllib.parse.urlencode(params))
    if d.get("status") != "1" or not d.get("geocodes"):
        return {"error": f"geocode 失败: {d.get('info','')}", "address": address}
    g = d["geocodes"][0]
    lng, lat = g["location"].split(",")
    return {"address": address, "city": city or "", "lng": float(lng), "lat": float(lat), "formatted": g.get("formatted_address", "")}


def _transit_route(origin, destination, city):
    key = os.environ.get("GAODE_API_KEY", "")
    if not key:
        return {"error": "GAODE_API_KEY 未配置"}
    o = _geocode(origin, city or None)
    d = _geocode(destination, city or None)
    if "error" in o or "error" in d:
        return {"error": o.get("error") or d.get("error")}
    params = {"key": key, "origin": f"{o['lng']},{o['lat']}", "destination": f"{d['lng']},{d['lat']}",
              "city": city or "北京", "datatype": "transit"}
    data = _get("https://restapi.amap.com/v3/direction/transit/integrated?" + urllib.parse.urlencode(params))
    if data.get("status") != "1":
        return {"error": f"transit 失败: {data.get('info','')}"}
    transits = (data.get("route") or {}).get("transits", [])
    out = []
    for t in transits[:5]:
        segs = t.get("segments", [])
        line = []
        for s in segs:
            if s.get("bus") and s["bus"].get("buslines"):
                line.append("公交" + s["bus"]["buslines"][0]["name"])
            elif s.get("metro"):
                line.append("地铁" + s["metro"]["name"])
            elif s.get("walking") and s["walking"].get("steps"):
                line.append("步行" + str(s["walking"]["steps"][0].get("distance", 0)) + "米")
        out.append({
            "line": " → ".join(line),
            "distance_km": round(float(t.get("distance", 0)) / 1000, 1),
            "duration_min": round(float(t.get("duration", 0)) / 60, 1),
            "carbon_kg": round(float(t.get("distance", 0)) / 1000 * 0.08, 3),
        })
    return {"origin": origin, "destination": destination, "routes": out, "source": "amap"}


def _carbon(distance_km, mode):
    try:
        dist = float(distance_km or 0)
    except (ValueError, TypeError):
        dist = 0.0
    factor = _FACTORS.get(mode or "car", 0.21)
    return {"distance_km": dist, "mode": mode or "car", "factor_kg_per_km": factor, "carbon_kg": round(dist * factor, 3)}


def handle_request(request):
    method = request.get("method", "")
    req_id = request.get("id")
    params = request.get("params", {})

    if req_id is None and method.startswith("notifications/"):
        return None
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": req_id, "result": {
            "protocolVersion": "2024-11-05", "serverInfo": {"name": "real-data-mcp-server", "version": "1.0.0"},
            "capabilities": {"tools": {}}}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": [
            {"name": "weather", "description": "查真实天气(Open-Meteo),输入城市", "inputSchema": {
                "type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}},
            {"name": "carbon_calc", "description": "按距离×方式系数算碳排(kg CO2)", "inputSchema": {
                "type": "object", "properties": {"distance_km": {"type": "number"}, "mode": {"type": "string"}}, "required": ["distance_km"]}},
            {"name": "geocode", "description": "地址→经纬度(高德)", "inputSchema": {
                "type": "object", "properties": {"address": {"type": "string"}, "city": {"type": "string"}}, "required": ["address"]}},
            {"name": "transit_route", "description": "公交换乘路线(高德)", "inputSchema": {
                "type": "object", "properties": {"origin": {"type": "string"}, "destination": {"type": "string"}, "city": {"type": "string"}}, "required": ["origin", "destination"]}},
        ]}}
    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {}) or {}
        try:
            if name == "weather":
                content = json.dumps(_weather(args.get("city", "北京")), ensure_ascii=False)
            elif name == "carbon_calc":
                content = json.dumps(_carbon(args.get("distance_km"), args.get("mode")), ensure_ascii=False)
            elif name == "geocode":
                content = json.dumps(_geocode(args.get("address", ""), args.get("city", "")), ensure_ascii=False)
            elif name == "transit_route":
                content = json.dumps(_transit_route(args.get("origin", ""), args.get("destination", ""), args.get("city", "")), ensure_ascii=False)
            else:
                return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": f"Tool not found: {name}"}}
        except Exception as e:
            content = json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False)
        return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": content}], "isError": False}}
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def main():
    print("[real-data-mcp] 启动, 等待 stdin JSON-RPC", file=sys.stderr, flush=True)
    try:
        for line in sys.stdin:
            text = line.strip()
            if not text:
                continue
            try:
                request = json.loads(text)
            except Exception as e:
                sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse: {e}"}}, ensure_ascii=False) + "\n")
                sys.stdout.flush()
                continue
            response = handle_request(request)
            if response is not None:
                sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                sys.stdout.flush()
    except (EOFError, BrokenPipeError):
        pass
    except Exception as e:
        print(f"[real-data-mcp] loop error: {e}", file=sys.stderr, flush=True)
    print("[real-data-mcp] 退出", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
