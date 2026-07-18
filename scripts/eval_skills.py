"""
P10.A:Skills 触发 + 行为评估脚本

使用方法:
    python scripts/eval_skills.py
    python scripts/eval_skills.py --golden tests/eval/skills_golden_set.jsonl
    python scripts/eval_skills.py --no-exit-code    # 不返 exit code,只跑诊断

CI Gate:
    trigger_accuracy >= 0.85 → exit 0
    否则 exit 1
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

GOLDEN_PATH = PROJECT_ROOT / "tests" / "eval" / "skills_golden_set.jsonl"
REPORT_PATH = PROJECT_ROOT / "data" / "skills_eval_report.md"

THRESHOLD_TRIGGER = 0.85


# ============ Skill 选择器(LLM-free 启发式)============

def _normalize_text(text: str) -> str:
    return (text or "").strip().lower()


def select_skill(query: str, skill_executor) -> Optional[str]:
    """根据查询从已注册的 Skill 中挑一个

    启发式:遍历每个 Skill 的 trigger_keywords,对每个 keyword 计算匹配分数:
    - 完全相等 +3
    - keyword 是 query 子串 +2
    - keyword 前 2 字符出现在 query 中(前缀模糊)+1
    再加上 Skill category 优先级:
    - policy 类关键词(政策/法规/条例/补贴/碳交易/碳市场/碳排放权/cber/cbam/碳达峰 等)
      命中时,policy_query 分数额外 +1.5
    - profile 类关键词(画像/偏好/记录/更新/关注/修改)命中时,profile_update 分数 +1.5
    - travel 类关键词(出行/通勤/公交/地铁/骑行/打车/路线/公里/碳排放/碳)命中时,
      low_carbon_travel 分数 +1.5

    取最高分(并列时按注册顺序)。

    返回: Skill name(str) 或 None(没匹配 → fallback)
    """
    if not query or not skill_executor:
        return None
    q = _normalize_text(query)
    best_skill: Optional[str] = None
    best_score = 0.0
    for name in skill_executor.list_all():
        skill = skill_executor.get(name)
        if skill is None:
            continue
        triggers = skill._trigger_keywords()  # noqa: SLF001
        if not triggers:
            continue
        score = 0.0
        for kw in triggers:
            kw_l = kw.lower()
            if not kw_l:
                continue
            if kw_l == q:
                score += 3
            elif kw_l in q:
                score += 2
            elif len(kw_l) >= 2 and kw_l[:2] in q:
                # 前缀模糊:keyword 前 2 字符在 query 里
                score += 1
        # 类别优先加权 — 解决 "碳排放权" / "出行偏好" 同时命中多类的混淆
        cat = (getattr(skill, "category", "") or "").lower()
        # 强 policy 信号(查到政策/法规/补贴/碳交易等)— 即使 query 含 "碳排放"
        policy_strong = any(
            t in q for t in ("政策", "法规", "条例", "办法", "通知", "补贴",
                             "碳交易", "配额", "ccer", "cbam", "碳市场",
                             "碳达峰", "核查", "清缴", "低碳补贴")
        )
        # 强 profile 信号(画像/偏好/记录 行为)
        profile_strong = any(
            t in q for t in ("画像", "偏好", "记录一下", "记一下", "记一笔",
                             "标记", "记到", "更新一下", "记在")
        )
        # 强 travel 信号(出行/通勤/公里/天气)
        travel_strong = any(
            t in q for t in ("出行", "通勤", "骑行", "打车", "公里", "天气",
                            "下雨", "路线", "怎么去")
        )

        if cat == "travel" and travel_strong:
            score += 1.5
        elif cat == "policy" and policy_strong:
            # 强 policy 信号 → 大幅加权,压制 travel
            score += 3.0
        elif cat == "profile" and profile_strong:
            # 强 profile 信号 → 大幅加权,压制 travel
            score += 3.0
        # 次级信号(travel 的弱信号如"公交/地铁"在没有 policy/profile 强信号时也加权)
        if cat == "travel" and any(
            t in q for t in ("公交", "地铁", "碳排放", "碳")
        ) and not policy_strong and not profile_strong:
            score += 1.0
        if score > best_score:
            best_score = score
            best_skill = name
    return best_skill if best_score > 0 else None


# ============ Skill 行为模拟(LLM-free)============

def _skill_execute_mock(skill_executor, skill_name: str, query: str) -> List[str]:
    """模拟 Skill 执行,返回触发的 behaviors 列表(子集)

    不实际跑底层 Tool(避免外部依赖),按 Skill 的工具组合 + query 关键词
    判定实际可能执行的步骤类型。
    """
    if not skill_name:
        return []
    skill = skill_executor.get(skill_name)
    if skill is None:
        return []
    tool_names = [t.name for t in skill.tools]
    q = _normalize_text(query)
    behaviors: List[str] = []

    # 各工具→行为映射(更宽松)
    for tn in tool_names:
        if tn == "weather_query":
            if any(k in q for k in ("天气", "下雨", "温度", "雨天", "weather")):
                behaviors.append("weather_check")
        elif tn == "carbon_calc":
            if any(k in q for k in ("碳", "排放", "减排", "减", "碳排", "碳足迹",
                                    "carbon", "少")):
                behaviors.append("carbon_calc")
        elif tn == "public_transit":
            if any(k in q for k in ("公交", "地铁", "通勤", "出行", "路线", "transit",
                                    "怎么去", "去", "从", "到")):
                behaviors.append("transit_query")
        elif tn == "policy_query":
            if any(k in q for k in ("政策", "补贴", "碳交易", "ccer", "配额",
                                    "低碳社区", "policy", "办法", "通知", "法规",
                                    "条例", "申报", "cbam", "碳市场", "核查",
                                    "碳达峰", "碳中和", "激励")):
                behaviors.append("policy_search")
        elif tn == "profile_update":
            if any(k in q for k in ("记录", "更新", "画像", "偏好", "修改", "记",
                                    "profile", "关注", "记一笔", "标记", "兴趣")):
                behaviors.append("behavior_record")

    # 画像 / 偏好 / 兴趣细分子类
    if "profile_update" in tool_names:
        if any(k in q for k in ("偏好", "关注", "喜欢", "调整")):
            behaviors.append("preference_update")
        if any(k in q for k in ("兴趣", "关注领域")):
            behaviors.append("interest_update")

    return sorted(set(behaviors))


# ============ 评估函数 ============

def load_golden(path: Path) -> List[Dict]:
    entries = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entries.append(json.loads(line))
    return entries


def evaluate(entries: List[Dict], skill_executor) -> Dict:
    """对每条 query 跑选择器 + 行为模拟,聚合三个 metric"""
    trigger_hits, behavior_hits = 0, 0
    n = len(entries)
    per_cat: Dict[str, Dict[str, int]] = {}
    misses = []
    fallbacks = 0

    for e in entries:
        q = e["query"]
        expected_skill = e.get("expected_skill", "")
        expected_behaviors = e.get("expected_behavior", []) or []
        cat = e.get("category", "?")

        # 1. trigger 准确性
        picked = select_skill(q, skill_executor)
        trigger_ok = picked == expected_skill
        trigger_hits += 1 if trigger_ok else 0
        if picked is None:
            fallbacks += 1

        # 2. 行为匹配(子集关系: expected ⊆ actual)
        actual_behaviors = _skill_execute_mock(skill_executor, picked, q)
        if expected_behaviors:
            behavior_ok = all(b in actual_behaviors for b in expected_behaviors)
        else:
            behavior_ok = True  # 没指定 → 视为通过
        behavior_hits += 1 if behavior_ok else 0

        # per-cat 统计
        per_cat.setdefault(cat, {"n": 0, "trigger_hit": 0, "behavior_hit": 0})
        per_cat[cat]["n"] += 1
        if trigger_ok:
            per_cat[cat]["trigger_hit"] += 1
        if behavior_ok:
            per_cat[cat]["behavior_hit"] += 1

        if not trigger_ok or not behavior_ok:
            misses.append({
                "query": q,
                "expected_skill": expected_skill,
                "picked": picked,
                "expected_behaviors": expected_behaviors,
                "actual_behaviors": actual_behaviors,
                "category": cat,
            })

    n = n or 1
    return {
        "n": n,
        "trigger_accuracy": trigger_hits / n,
        "behavior_match_rate": behavior_hits / n,
        "fallback_rate": fallbacks / n,
        "per_category": per_cat,
        "misses": misses,
    }


def write_report(result: Dict) -> None:
    """写 data/skills_eval_report.md"""
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    lines.append("# Skills 触发评估报告 — P10.A")
    lines.append("")
    lines.append(f"- 总 query 数: **{result['n']}**")
    lines.append("")
    lines.append("## 总体指标")
    lines.append("")
    lines.append("| 指标 | 值 | 阈值 | 状态 |")
    lines.append("|---|---|---|---|")
    lines.append(
        f"| trigger_accuracy | {result['trigger_accuracy']:.4f} | "
        f">= {THRESHOLD_TRIGGER} | "
        f"{'PASS' if result['trigger_accuracy'] >= THRESHOLD_TRIGGER else 'FAIL'} |"
    )
    lines.append(
        f"| behavior_match_rate | {result['behavior_match_rate']:.4f} | "
        f"(信息性) | - |"
    )
    lines.append(
        f"| fallback_rate | {result['fallback_rate']:.4f} | (越低越好) | - |"
    )
    lines.append("")
    lines.append("## 分类明细")
    lines.append("")
    lines.append("| 类目 | n | trigger_hit | behavior_hit |")
    lines.append("|---|---|---|---|")
    for cat, v in sorted(result["per_category"].items()):
        lines.append(
            f"| {cat} | {v['n']} | {v['trigger_hit']}/{v['n']} | "
            f"{v['behavior_hit']}/{v['n']} |"
        )
    lines.append("")
    if result["misses"]:
        lines.append(f"## 未命中明细({len(result['misses'])} 条)")
        lines.append("")
        for m in result["misses"]:
            lines.append(f"- **query**: `{m['query']}`  (类目: {m['category']})")
            lines.append(f"  - 期望 skill: `{m['expected_skill']}`  实际: `{m['picked']}`")
            lines.append(
                f"  - 期望 behaviors: {m['expected_behaviors']}  "
                f"实际: {m['actual_behaviors']}"
            )
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Skills 触发评估(P10.A)")
    parser.add_argument(
        "--golden",
        default=str(GOLDEN_PATH),
        help="golden set 路径(默认 tests/eval/skills_golden_set.jsonl)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=THRESHOLD_TRIGGER,
        help="trigger_accuracy 阈值(默认 0.85)",
    )
    parser.add_argument(
        "--no-exit-code",
        action="store_true",
        help="不根据阈值返 exit code",
    )
    args = parser.parse_args()

    golden_path = Path(args.golden)
    if not golden_path.exists():
        print(f"[ERR] golden set 不存在: {golden_path}")
        sys.exit(2)
    entries = load_golden(golden_path)
    if not entries:
        print(f"[ERR] golden set 为空: {golden_path}")
        sys.exit(2)

    # 注册 Skills(不依赖 server 启动)
    try:
        from agent.skills import get_skill_executor
        from agent.skills.builtin import (
            LowCarbonTravelSkill,
            PolicyQuerySkill,
            ProfileUpdateSkill,
        )
        skill_exec = get_skill_executor()
        for SkillCls in [LowCarbonTravelSkill, PolicyQuerySkill, ProfileUpdateSkill]:
            inst = SkillCls()
            skill_exec.register(inst)
            # 也写 SKILL.md(便于 docs/check 直接验证)
            try:
                inst.write_skill_md()
            except Exception:
                pass
    except Exception as e:
        print(f"[ERR] Skill 注册失败: {e}")
        sys.exit(2)

    print(f"[eval] loaded {len(entries)} queries from {golden_path}")
    print(f"[eval] skills: {skill_exec.list_all()}")

    result = evaluate(entries, skill_exec)
    print()
    print("=== 评估结果 ===")
    print(f"  n                  = {result['n']}")
    print(f"  trigger_accuracy   = {result['trigger_accuracy']:.4f}  "
          f"(threshold >= {args.threshold})")
    print(f"  behavior_match_rate= {result['behavior_match_rate']:.4f}")
    print(f"  fallback_rate      = {result['fallback_rate']:.4f}")
    print()
    print("  分类明细:")
    for cat, v in sorted(result["per_category"].items()):
        print(f"    {cat:20s} n={v['n']:2d}  "
              f"trigger={v['trigger_hit']}/{v['n']}  "
              f"behavior={v['behavior_hit']}/{v['n']}")
    print()
    print(f"  未命中: {len(result['misses'])} 条")
    print(f"  报告:   {REPORT_PATH}")

    write_report(result)

    passed = result["trigger_accuracy"] >= args.threshold
    print()
    print(f"  状态: {'PASS' if passed else 'FAIL'}")

    if args.no_exit_code:
        sys.exit(0)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()