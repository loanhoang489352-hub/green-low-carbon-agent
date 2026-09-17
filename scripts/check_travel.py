# -*- coding: utf-8 -*-
r"""
验证出行规划修复:直接调 TravelPlanningTool.execute,看是否返回真实高德数据(而非估算降级)。

用法(在项目根):
    cd D:\green-agent
    python scripts\check_travel.py
"""
import os
import sys
import json
from pathlib import Path

root = Path(__file__).resolve().parent.parent
env_file = root / ".env"
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

sys.path.insert(0, str(root / "src"))

key = os.environ.get("GAODE_API_KEY", "")
print(f"高德 key: {'已配置' if key else '(未配置 GAODE_API_KEY)'}")

from agent.tools.extended import TravelPlanningTool  # noqa: E402

tool = TravelPlanningTool()
res = tool.execute(origin="北京西单", destination="国贸", mode="all")

check_report = {
    "success": res.success,
    "error": res.error,
    "code": (res.data or {}).get("code"),
    "source": (res.data or {}).get("source"),
    "route_types": [r.get("type") for r in ((res.data or {}).get("routes") or [])],
    "data_quality": (res.data or {}).get("data_quality"),
}
(root / "data" / "travel_provider_check.json").write_text(
    json.dumps(check_report, ensure_ascii=False, indent=2), encoding="utf-8"
)

print(f"\n工具 success = {res.success}")
if not res.success:
    print(f"失败原因: {res.error}")
    sys.exit(1)

data = res.data
print(f"数据来源 : {data.get('source')}")
print(f"起终点   : {data.get('origin')} -> {data.get('destination')}")
print(f"起点坐标 : {data.get('origin_coord')}")
print(f"终点坐标 : {data.get('destination_coord')}")
routes = data.get("routes") or []
print(f"路线数量 : {len(routes)}")
for r in routes:
    print(f"  - {r.get('type')}: {r.get('line')} | {r.get('distance_km')}km | {r.get('duration_min')}min | 碳{r.get('carbon_kg')}kg | ¥{r.get('cost_yuan')}")

rec = data.get("recommended") or {}
print(f"\n推荐方案: {rec.get('type')} (score={rec.get('score')})")

print("\n判断:")
print("  source=高德地图API  -> 修复生效,已用真实高德数据")
print("  查询失败 -> 明确失败且 routes 为空，不生成替代路线")
