"""
P12.3: 家庭节能规划评估脚本

评估 EnergyPlanner 在 20 个真实家庭场景下生成方案的质量:
- hit_rate: 满足最低行为数 / 类别覆盖 / source_ref 完整 等硬约束的 case 占比
- hallucination_rate: action 缺 source_ref 或节省数字出合理带 = 视为"幻觉"
- coverage: 至少 5 个 action 覆盖 water/electricity/gas 三大类的占比
- realism: 总节省数字落在合理带 (50 < cny < 1500, 50 < co2 < 2000) 的占比

使用方法:
    cd D:/绿色低碳智能体 && python scripts/eval_energy.py
    python scripts/eval_energy.py --no-exit-code   # 不强制 exit code,用于本地诊断
    python scripts/eval_energy.py --json data/eval_energy_report.json

exit 0 if quality_score >= 0.80 else exit 1.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

GOLDEN_SET_PATH = PROJECT_ROOT / "tests" / "eval" / "energy_golden_set.jsonl"
REPORT_MD = PROJECT_ROOT / "data" / "eval_energy_report.md"
REPORT_JSON = PROJECT_ROOT / "data" / "eval_energy_report.json"


# ========== Profile 适配器 ==========

# 城市名 → 拼音(便于 HouseholdProfile 拼接)
_CITY_ALIAS = {
    "北京": "beijing",
    "上海": "shanghai",
    "广州": "guangzhou",
    "深圳": "shenzhen",
    "成都": "chengdu",
    "杭州": "hangzhou",
    "南京": "nanjing",
}

# 真实家用电器关键词 → HouseholdProfile.appliances 中的标准化 token
_APPLIANCE_KEYWORDS = [
    ("空调", "空调"),
    ("AC", "空调"),
    ("air_conditioner", "空调"),
    ("冰箱", "冰箱"),
    ("fridge", "冰箱"),
    ("冰柜", "冰箱"),
    ("洗衣机", "洗衣机"),
    ("washer", "洗衣机"),
    ("烘干机", "洗衣机"),      # 共用 + washer 模板;planner 会查 water_heater_present 等
    ("洗碗机", "洗衣机"),
    ("热水器", "热水器"),
    ("water_heater", "热水器"),
    ("热泵热水器", "热水器"),
    ("电热水器", "热水器"),
    ("燃气热水器", "热水器"),
    ("灯", "灯"),
    ("灯具", "灯"),
    ("lighting", "灯"),
]

# 水/气 量 → 费用的简单估算(单价人民币)
WATER_PRICE_PER_M3 = 6.0
GAS_PRICE_PER_M3 = 3.0

# 合理带(违反即视为数字幻觉)
_REALISTIC_BAND = {
    "cny": (50.0, 1500.0),
    "co2_kg": (50.0, 2000.0),
    "per_action": {
        "electricity": {"cny": (5.0, 200.0), "co2": (5.0, 200.0), "kwh": (10.0, 200.0)},
        "water":       {"cny": (1.0, 200.0),  "co2": (0.1, 20.0), "kwh": (0.0, 0.0)},
        "gas":         {"cny": (10.0, 300.0), "co2": (50.0, 500.0), "kwh": (0.0, 0.0)},
    },
}


def adapt_golden_to_profile(raw: dict, idx: int) -> "HouseholdProfile":
    """把 tests/eval/energy_golden_set.jsonl 里的 rich profile 适配成 HouseholdProfile

    适配差异:
      - city "北京" → "beijing" (planner 支持中英别名,建议给 pinyin)
      - appliances 归一化为 ["空调","热水器","冰箱","洗衣机","灯"]
      - monthly_water_m3 × 6 → water_bill
      - monthly_gas_m3   × 3 → gas_bill
      - 月电费优先取 monthly_bill_yuan,缺则按 monthly_electricity_kwh × 0.55 估算
    """
    from agent.energy.models import HouseholdProfile

    prof = raw.get("profile", raw)
    user_id = f"eval_user_{idx:03d}"

    city_raw = prof.get("city", "北京")
    city = _CITY_ALIAS.get(city_raw, city_raw)

    raw_app = prof.get("appliances", []) or []
    norm: List[str] = []
    for a in raw_app:
        if not a:
            continue
        for kw, token in _APPLIANCE_KEYWORDS:
            if kw in a or kw.lower() in a.lower():
                if token not in norm:
                    norm.append(token)
                break
    if not norm:
        norm = ["灯", "冰箱"]

    monthly_bill = float(prof.get("monthly_bill_yuan") or 0.0)
    if monthly_bill <= 0:
        kwh = float(prof.get("monthly_electricity_kwh") or 0.0)
        monthly_bill = round(kwh * 0.55, 2)

    water_m3 = float(prof.get("monthly_water_m3") or 0.0)
    gas_m3 = float(prof.get("monthly_gas_m3") or 0.0)
    water_bill = round(water_m3 * WATER_PRICE_PER_M3, 2)
    gas_bill = round(gas_m3 * GAS_PRICE_PER_M3, 2)

    season = prof.get("season", "") or ""
    peak = "peak" if season in ("夏季", "summer") else "mixed"

    return HouseholdProfile(
        user_id=user_id,
        family_size=int(prof.get("household_size", 3)),
        home_size_sqm=float(prof.get("home_area_sqm", 90.0)),
        city=city,
        monthly_electricity_bill=monthly_bill,
        monthly_water_bill=water_bill,
        monthly_gas_bill=gas_bill,
        appliances=norm,
        peak_offpeak_usage=peak,
        ac_temp_setting=24,
        delegation_level=int(prof.get("delegation_level", 1)),
    )


# ========== 评估指标 ==========

def _per_action_realism(action) -> List[str]:
    """返回违带字段名列表(空=合现实)"""
    violations: List[str] = []
    band = _REALISTIC_BAND["per_action"].get(action.category)
    if not band:
        return violations
    if not (band["cny"][0] <= action.estimated_saving_cny <= band["cny"][1]):
        violations.append(f"cny={action.estimated_saving_cny}")
    if not (band["co2"][0] <= action.estimated_saving_co2_kg <= band["co2"][1]):
        violations.append(f"co2={action.estimated_saving_co2_kg}")
    if band["kwh"] != (0.0, 0.0):
        if not (band["kwh"][0] <= action.estimated_saving_kwh <= band["kwh"][1]):
            violations.append(f"kwh={action.estimated_saving_kwh}")
    return violations


def _eval_one(case: dict, idx: int) -> Dict:
    """评估单条 golden case → 返回 dict 含 pass/fail + 失败原因 + 指标"""
    from agent.energy.planner import EnergyPlanner

    raw_profile = case.get("profile", {})
    profile = adapt_golden_to_profile(case, idx)
    planner = EnergyPlanner()

    case_result: Dict = {
        "id": case.get("id", f"energy_{idx:03d}"),
        "category": case.get("category", "?"),
        "city": raw_profile.get("city"),
        "delegation_level": raw_profile.get("delegation_level"),
        "errors": [],
        "metrics": {},
    }

    # 1. 出方案
    try:
        plan = planner.generate_plan(profile)
    except Exception as e:  # noqa: BLE001
        case_result["errors"].append(f"planner crashed: {type(e).__name__}: {e}")
        case_result["passed"] = False
        return case_result

    actions = plan.actions
    n = len(actions)

    # 2. 数量下限
    min_actions = case.get("expected_actions_min", 5)
    if n < min_actions:
        case_result["errors"].append(
            f"action count {n} < min {min_actions}"
        )

    # 3. 类别覆盖:三大类每类至少 1 个(任务要求,不强制每类 2 个)
    counter = Counter(a.category for a in actions)
    expected_cats = set(case.get("expected_categories", ["water", "electricity", "gas"]))
    missing_categories = sorted(expected_cats.difference(counter))
    for cat in missing_categories:
        case_result["errors"].append(f"missing category: {cat}")

    # 4. source_ref 完整(无幻觉防火墙)
    hallucinated: List[str] = []
    for a in actions:
        if not a.source_ref or not a.source_ref.strip():
            hallucinated.append(f"{a.id}/empty-source")
            continue
        # source_ref 必须以 policy: / standard: / appliance: 之一为前缀,或包含文档路径
        prefixes = ("policy:", "standard:", "appliance:", "GB ")
        if not any(a.source_ref.startswith(p) or p in a.source_ref[:30] for p in prefixes):
            hallucinated.append(f"{a.id}/unverifiable-source={a.source_ref[:60]}")
        # 数字合理性
        bad = _per_action_realism(a)
        if bad:
            hallucinated.append(f"{a.id}/numbers-out-of-band={'|'.join(bad)}")

    if hallucinated:
        case_result["errors"].append(f"hallucinated: {len(hallucinated)} actions — {';'.join(hallucinated[:3])}")

    # 5. 总节省数字在合理带
    total_cny = plan.total_estimated_saving_cny
    total_co2 = plan.total_estimated_saving_co2_kg
    cny_band = _REALISTIC_BAND["cny"]
    co2_band = _REALISTIC_BAND["co2_kg"]
    band_ok_cny = cny_band[0] <= total_cny <= cny_band[1]
    band_ok_co2 = co2_band[0] <= total_co2 <= co2_band[1]
    if not band_ok_cny:
        case_result["errors"].append(
            f"total cny {total_cny} out of band {cny_band}"
        )
    if not band_ok_co2:
        case_result["errors"].append(
            f"total co2 {total_co2} out of band {co2_band}"
        )

    # 6. 难度分级合理(易 ≥ 3,难 ≤ 2)
    diff_dist = case.get("expected_difficulty_distribution", {})
    if diff_dist:
        easy_min = diff_dist.get("easy_min", 0)
        hard_max = diff_dist.get("hard_max", 99)
        easy_count = sum(1 for a in actions if a.difficulty == 1)
        hard_count = sum(1 for a in actions if a.difficulty >= 3)
        if easy_count < easy_min:
            case_result["errors"].append(
                f"only {easy_count} easy actions (< {easy_min})"
            )
        if hard_count > hard_max:
            case_result["errors"].append(
                f"{hard_count} hard actions (> {hard_max})"
            )

    case_result["metrics"] = {
        "action_count": n,
        "categories": dict(counter),
        "total_cny": total_cny,
        "total_co2": total_co2,
        "hallucinated_actions": len(hallucinated),
    }
    case_result["passed"] = not case_result["errors"]
    return case_result


# ========== 报告输出 ==========

def _write_markdown(results: List[Dict], totals: Dict, threshold: float, passed: bool) -> None:
    lines: List[str] = []
    lines.append("# P12.3 节能规划评估报告")
    lines.append("")
    lines.append(f"- 生成时间: {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"- 总 case 数: **{totals['n']}**")
    lines.append(f"- 全部通过数: **{totals['passed']}**")
    lines.append(f"- 质量分 (quality_score): **{totals['quality_score']:.4f}**")
    lines.append(f"- 阈值: {threshold:.2f} → {'PASS' if passed else 'FAIL'}")
    lines.append("")
    lines.append("## 总体指标")
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("|---|---|")
    for k, v in totals.items():
        if k == "n":
            continue
        if isinstance(v, float):
            lines.append(f"| {k} | {v:.4f} |")
        else:
            lines.append(f"| {k} | {v} |")
    lines.append("")
    lines.append("## 各 case 明细")
    lines.append("")
    lines.append("| ID | 城市 | 类目 | # | water | elec | gas | total ¥ | total CO2 | 状态 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in results:
        cats = r["metrics"].get("categories", {})
        lines.append(
            f"| {r['id']} | {r.get('city','?')} | {r['category']} | "
            f"{r['metrics'].get('action_count', 0)} | "
            f"{cats.get('water',0)} | {cats.get('electricity',0)} | {cats.get('gas',0)} | "
            f"{r['metrics'].get('total_cny', 0):.1f} | {r['metrics'].get('total_co2', 0):.1f} | "
            f"{'OK' if r.get('passed') else 'FAIL'} |"
        )
    fail = [r for r in results if not r.get("passed")]
    if fail:
        lines.append("")
        lines.append(f"## 失败明细 ({len(fail)} 条)")
        lines.append("")
        for r in fail:
            lines.append(f"- **{r['id']}** ({r['category']}):")
            for err in r["errors"]:
                lines.append(f"  - {err}")
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")


# ========== 入口 ==========

def main() -> int:
    parser = argparse.ArgumentParser(description="P12.3 节能方案质量评估")
    parser.add_argument("--golden-set", default=str(GOLDEN_SET_PATH),
                        help="JSONL 评估集路径")
    parser.add_argument("--threshold", type=float, default=0.80,
                        help="quality_score 通过阈值(默认 0.80)")
    parser.add_argument("--no-exit-code", action="store_true",
                        help="本地诊断时始终返回 0")
    parser.add_argument("--report-json", dest="report_json_explicit", default=None,
                        help="JSON 报告路径")
    parser.add_argument("--json", dest="report_json_legacy", default=None,
                        help="兼容旧参数,等同于 --report-json")
    parser.add_argument("--debug", action="store_true", help="DEBUG logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.WARNING,
        format="%(levelname)s [%(name)s] %(message)s",
    )

    if not args.golden_set:
        args.golden_set = str(GOLDEN_SET_PATH)
    golden_path = Path(args.golden_set)
    if not golden_path.exists():
        print(f"[ERR] golden set 不存在: {golden_path}")
        return 2

    cases: List[Dict] = []
    with golden_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                cases.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"[WARN] JSON 解析失败跳过: {e}")
    if not cases:
        print("[ERR] golden set 为空")
        return 2

    print(f"[eval-energy] cases={len(cases)} threshold={args.threshold:.2f}")

    results: List[Dict] = []
    for idx, case in enumerate(cases):
        r = _eval_one(case, idx)
        results.append(r)
        flag = "OK" if r.get("passed") else "FAIL"
        print(f"  {idx+1:02d}. {r['id']:13s} {r['category']:38s} → {flag}")

    n = len(results)
    passed = sum(1 for r in results if r.get("passed"))
    quality_score = passed / n if n else 0.0
    # hit_rate is the requested minimum-action hit rate, independent of
    # category/source/realism diagnostics.
    hit_rate = sum(
        1 for r, c in zip(results, cases)
        if r["metrics"].get("action_count", 0) >= int(c.get("expected_actions_min", 5))
    ) / n if n else 0.0
    coverage = sum(
        1 for r, c in zip(results, cases)
        if set(c.get("expected_categories", ["water", "electricity", "gas"])).issubset(
            set(r["metrics"].get("categories", {}).keys())
        )
    ) / n if n else 0.0
    realism = sum(
        1 for r in results
        if r["metrics"].get("hallucinated_actions", 0) == 0
        and not any("out of band" in e for e in r.get("errors", []))
    ) / n if n else 0.0
    hallucinated_total = sum(
        r["metrics"].get("hallucinated_actions", 0) for r in results
    )
    actions_total = sum(r["metrics"].get("action_count", 0) for r in results)
    hallucination_rate = hallucinated_total / max(1, actions_total)

    totals = {
        "n": n,
        "passed": passed,
        "failed": n - passed,
        "hit_rate": hit_rate,
        "hallucination_rate": hallucination_rate,
        "coverage": coverage,
        "realism": realism,
        "quality_score": quality_score,
        # Backward-compatible aliases for existing reports.
        "coverage_full": coverage,
        "hallucinated_action_count": hallucinated_total,
    }

    print()
    print("=== 评估结果 ===")
    for k, v in totals.items():
        if isinstance(v, float):
            print(f"  {k:30s} {v:.4f}")
        else:
            print(f"  {k:30s} {v}")

    ok = quality_score >= args.threshold
    print(f"\n  threshold={args.threshold:.2f} → {'PASS' if ok else 'FAIL'}")

    # 报告
    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    _write_markdown(results, totals, args.threshold, ok)
    report_json = args.report_json_explicit or args.report_json_legacy or str(REPORT_JSON)
    Path(report_json).write_text(
        json.dumps(
            {"totals": totals, "results": results, "threshold": args.threshold, "passed": ok},
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"  报告(MD)  : {REPORT_MD}")
    print(f"  报告(JSON): {report_json}")

    if args.no_exit_code:
        return 0
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
