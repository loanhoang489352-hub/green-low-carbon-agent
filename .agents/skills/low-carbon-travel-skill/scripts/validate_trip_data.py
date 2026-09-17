# -*- coding: utf-8 -*-
r"""
low-carbon-travel-skill —— 出行规划结果校验器

校验 travel_planning 工具返回的数据是否"完整、可执行":
  - 至少有 route
  - 每条 route 有 type/line/distance_km/carbon_kg/steps(详细走法)
  - 有 recommended(推荐方案 + score)
  - 有 weights(评分权重)
  - 有 source(高德地图API / 估算)

用法:
    python scripts/validate_trip_data.py <result.json>
    # 或直接 import:
    from validate_trip_data import validate
"""
from __future__ import annotations

import json
import sys
from typing import Any, Dict, List, Optional


def validate(data: Dict[str, Any]) -> List[str]:
    """校验出行结果,返问题列表(空列表=通过)。"""
    problems: List[str] = []
    if not isinstance(data, dict):
        problems.append("结果不是 dict")
        return problems
    routes = data.get("routes") or []
    if not routes:
        problems.append("没有 routes")
    # 每条路线完整性
    for i, r in enumerate(routes, 1):
        if not r.get("type"):
            problems.append(f"路线{i} 缺 type")
        if not r.get("line"):
            problems.append(f"路线{i} 缺 line(具体线路名)")
        if r.get("distance_km") is None:
            problems.append(f"路线{i} 缺 distance_km")
        if r.get("carbon_kg") is None:
            problems.append(f"路线{i} 缺 carbon_kg")
        if not r.get("steps"):
            problems.append(f"路线{i} 缺 steps(详细走法)——可执行性差")
        if not r.get("score_breakdown"):
            problems.append(f"路线{i} 缺 score_breakdown(碳/费/时/天明细)")
    # 推荐 + 权重 + 数据来源 + 天气
    rec = data.get("recommended") or {}
    if "score" not in rec:
        problems.append("缺 recommended.score(推荐评分)")
    weights = data.get("weights") or {}
    for k in ("carbon", "cost", "duration", "weather"):
        if k not in weights:
            problems.append(f"缺 weights.{k}")
    src = data.get("source", "")
    if not src:
        problems.append("缺 source(高德地图API/估算)")
    return problems


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print("用法: python scripts/validate_trip_data.py <result.json>")
        return 2
    try:
        with open(args[0], "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"❌ 读取/解析失败: {e}")
        return 1
    problems = validate(data)
    if problems:
        print("⚠️ 出行结果不完整:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("✅ 出行结果完整可执行 (routes / steps / score / weights / source)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
