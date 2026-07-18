"""
P11.B:Skills 触发 + 行为评估脚本(扩到 100+ 场景,支持中英文)

使用方法:
    python scripts/eval_skills.py
    python scripts/eval_skills.py --golden tests/eval/skills_golden_set.jsonl
    python scripts/eval_skills.py --no-exit-code    # 不返 exit code,只跑诊断
    python scripts/eval_skills.py --threshold 0.90  # 自定义 CI gate 阈值

CI Gate:
    trigger_accuracy >= 0.90(P11.B 新阈值,原 0.85)→ exit 0
    否则 exit 1

报告:
    data/skills_eval_report.md — 含按 category 拆分 + 趋势对比
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

GOLDEN_PATH = PROJECT_ROOT / "tests" / "eval" / "skills_golden_set.jsonl"
REPORT_PATH = PROJECT_ROOT / "data" / "skills_eval_report.md"
TREND_PATH = PROJECT_ROOT / "data" / "skills_eval_trend.json"

# P11.B:CI gate 阈值从 0.85 上调到 0.90
THRESHOLD_TRIGGER = 0.90

# ============ 类别强信号字典(中英双语)============

# travel 类别强信号:用户在做"出行规划 / 碳排计算 / 天气查询"
TRAVEL_STRONG_ZH = (
    "出行", "通勤", "骑行", "打车", "公里", "下雨",
    "路线", "怎么去", "从", "到", "去",  # 路线方向
    "公交", "地铁", "开车", "自驾", "高铁", "飞机",
    "电动车", "单车", "步行", "徒步",
    "出门", "上班", "上学", "交通",
    "拼车", "顺风车", "出差",
    "去", "到",
    # 减碳意图(与"碳"组合时优先 travel)
    "少点碳", "少碳", "减碳", "省碳", "低碳",
)
# 注意:"天气"和"碳排放"从 STRONG 移到 WEAK(避免单独触发 travel)
TRAVEL_WEAK_ZH = ("天气", "碳排放", "碳", "公里", "环保", "减排", "排", "少")

# policy 类别强信号:政策/法规/补贴/碳市场
POLICY_STRONG_ZH = (
    "政策", "法规", "条例", "办法", "通知", "补贴",
    "碳交易", "配额", "ccer", "cbam", "碳市场",
    "碳达峰", "核查", "清缴", "低碳补贴",
    "激励", "申报", "意见", "标准", "指南",
    "要求", "规定", "扶持", "试点",
)

# profile 类别强信号:画像/偏好/记录行为
PROFILE_STRONG_ZH = (
    "画像", "偏好", "记录", "记一笔", "记一下",
    "标记", "记到", "更新一下", "记在",
    "修改", "更新", "行为", "关注", "兴趣",
    "加上", "调整", "加一笔", "我的目标",
    "环保目标", "减碳", "行为日志",
)

# travel 英文强信号
TRAVEL_STRONG_EN = (
    "transit", "commute", "travel", "carbon", "route", "weather",
    "bike", "cycle", "drive", "subway", "bus", "taxi", "car",
    "vehicle", "emission", "footprint", "eco", "low-carbon",
    "train", "flight", "ride", "km", "mile",
)
POLICY_STRONG_EN = (
    "policy", "regulation", "law", "subsidy", "incentive", "ccer",
    "cbam", "carbon market", "compliance", "carbon trade",
    "allowance", "carbon neutrality", "emissions cap",
    "emission standard", "rule", "directive", "agreement",
    "legislation", "regulation",
)
PROFILE_STRONG_EN = (
    "profile", "preference", "record", "behavior", "log",
    "update", "interest", "save", "track", "note",
)


# ============ Skill 选择器(LLM-free 启发式)============

def _normalize_text(text: str) -> str:
    return (text or "").strip().lower()


def _strong_signals_for(category: str) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """返回 (强信号 zh 列表, 强信号 en 列表)"""
    cat = (category or "").lower()
    if cat == "travel":
        return TRAVEL_STRONG_ZH, TRAVEL_STRONG_EN
    if cat == "policy":
        return POLICY_STRONG_ZH, POLICY_STRONG_EN
    if cat == "profile":
        return PROFILE_STRONG_ZH, PROFILE_STRONG_EN
    return ((), ())


def _score_skill(query: str, skill) -> float:
    """对单个 Skill 计算匹配分数"""
    if not query or skill is None:
        return 0.0
    q = _normalize_text(query)
    score = 0.0

    cat = (getattr(skill, "category", "") or "").lower()
    strong_zh, strong_en = _strong_signals_for(cat)

    # travel-context(弱信号加成 / 天气抑制 都靠它)
    # 包括 TRAVEL_STRONG_ZH 全部 + 上下文关键词
    travel_context = any(
        t in q for t in TRAVEL_STRONG_ZH
    ) or any(
        t in q for t in ("出发", "去", "到", "怎么", "咋", "碳",
                        "transit", "commute", "travel", "ride", "drive",
                        "bike", "subway", "bus", "carbon")
    )

    # ---- 1. trigger keyword 匹配(when_to_use)----
    triggers = skill._trigger_keywords()  # noqa: SLF001
    for kw in triggers:
        kw_l = kw.lower()
        if not kw_l:
            continue
        # 完整匹配 +3
        if kw_l == q:
            score += 3
        # 子串匹配 +2
        elif kw_l in q:
            # 特殊:"天气" 单独触发 travel 需要 travel context
            if kw_l == "天气" and cat == "travel" and not travel_context:
                # 抑制:仅匹配"天气"无出行语境 → 不加分
                continue
            # 特殊:profile 英文 "log/save/track/note" 单独触发需 my 后缀
            if cat == "profile" and kw_l in ("log", "save", "track", "note"):
                # 必须配合 my 上下文
                compound_patterns = ("log my", "save my", "track my", "note my",
                                    "log this", "save this", "log today",
                                    "log it", "save it")
                if not any(p in q for p in compound_patterns):
                    # 单独 log/save/track 不算
                    continue
            score += 2
        # 前缀模糊(对英文) — 单词前缀
        elif _is_english(kw_l) and len(kw_l) >= 3:
            # 单词级前缀匹配:每个 token 的开头
            kw_token = kw_l.split()[0] if " " not in kw_l else kw_l
            q_tokens = set(q.split())
            for qt in q_tokens:
                if qt.startswith(kw_token[:3]):
                    score += 1
                    break

    # ---- 2. 类别强信号加权 ----
    has_strong_zh = any(t in q for t in strong_zh)
    has_strong_en = any(t in q for t in strong_en)
    if has_strong_zh or has_strong_en:
        score += 3.0

    # ---- 3. 弱信号加成(避免"碳排放"或"天气"单独触发)----
    if cat == "travel":
        # 弱信号需配合出行/通勤/出门/上下班 等强上下文才加分
        weak_match = any(t in q for t in TRAVEL_WEAK_ZH)
        if weak_match and travel_context:
            score += 1.0

    # ---- 4. profile priority:reporting intent overrides travel noise ----
    # 当 query 同时有 profile_strong + travel 关键词(用户记录/报告行为),优先 profile
    if cat == "profile":
        reporting_verbs = ("记", "记录", "记一笔", "记一下", "标记", "加上",
                          "加一笔", "更新", "修改")
        has_reporting = any(rv in q for rv in reporting_verbs)
        if has_reporting:
            # 用户在报告/记录行为 → profile 显著加权
            score += 3.0

    # ---- 5. travel 减碳意图加成:用户问"少点碳"/"减碳" 是 travel 场景 ----
    if cat == "travel":
        carbon_reduce = ("少点碳", "少碳", "减碳", "省碳", "低碳")
        if any(t in q for t in carbon_reduce):
            score += 2.0  # 用户想减少出行碳排 → travel 强相关

    return score


def _is_english(text: str) -> bool:
    """判断是否纯英文/ASCII 词"""
    if not text:
        return False
    return all(ord(c) < 128 and c.isalpha() or c in "-_ " for c in text)


def select_skill(query: str, skill_executor) -> Optional[str]:
    """根据查询从已注册的 Skill 中挑一个

    返回: Skill name(str) 或 None(没匹配 → fallback)
    """
    if not query or not skill_executor:
        return None

    best_skill: Optional[str] = None
    best_score = 0.0

    # 当分数相同时,优先级: profile > travel > policy
    # (用户更可能在表达"记录行为"而不是"查询政策"——reporting intent 优先)
    skill_priority = {
        "profile_update": 3,
        "low_carbon_travel": 2,
        "policy_query": 1,
    }

    for name in skill_executor.list_all():
        skill = skill_executor.get(name)
        if skill is None:
            continue
        score = _score_skill(query, skill)
        # 加微小优先级打破平局(profile > travel > policy)
        # 仅在 score > 0 时生效(避免负例被错触发)
        if score > 0:
            priority = skill_priority.get(name, 0) * 0.01
            total = score + priority
        else:
            total = 0.0
        if total > best_score:
            best_score = total
            best_skill = name

    return best_skill if best_score > 0 else None


# ============ Skill 行为模拟(LLM-free)============

def _skill_execute_mock(skill_executor, skill_name: str, query: str) -> List[str]:
    """模拟 Skill 执行,返回触发的 behaviors 列表(子集)"""
    if not skill_name:
        return []
    skill = skill_executor.get(skill_name)
    if skill is None:
        return []
    tool_names = [t.name for t in skill.tools]
    q = _normalize_text(query)
    behaviors: List[str] = []

    # 各工具→行为映射(P11.B 更宽松 + 双语)
    for tn in tool_names:
        if tn == "weather_query":
            # 天气查询需要 travel context 才计 weather_check
            if any(k in q for k in ("天气", "下雨", "温度", "雨天", "weather",
                                    "雨", "晴", "霾")):
                # 必须配合出行语境才计
                if any(k in q for k in ("出行", "通勤", "出门", "上班", "上学",
                                        "去", "到", "出发", "路线",
                                        "transit", "commute", "travel", "ride")):
                    behaviors.append("weather_check")
        elif tn == "carbon_calc":
            if any(k in q for k in ("碳", "排放", "减排", "减", "碳排", "碳足迹",
                                    "carbon", "少", "footprint", "emission",
                                    "环保", "eco", "low-carbon", "co2", "污染",
                                    "少碳", "减碳", "省碳", "低碳")):
                behaviors.append("carbon_calc")
        elif tn == "public_transit":
            # travel skill:任何 travel context → transit_query(默认)
            travel_kw = ("公交", "地铁", "通勤", "出行", "路线", "transit",
                        "怎么去", "怎么", "去", "从", "到", "站", "线",
                        "线路", "train", "subway", "bus",
                        "ride", "travel", "how", "出发", "出门",
                        "通勤", "拼车", "顺风车", "出差", "打车",
                        "出租车", "高铁", "飞机", "开车", "自驾",
                        "公里", "km", "mile")
            if any(k in q for k in travel_kw):
                behaviors.append("transit_query")
            # travel skill + 单纯问"怎么去 / 咋去" → transit_query 也算
            elif any(k in q for k in ("怎么", "咋", "哪种", "推荐")):
                behaviors.append("transit_query")
        elif tn == "policy_query":
            if any(k in q for k in ("政策", "补贴", "碳交易", "ccer", "配额",
                                    "低碳社区", "policy", "办法", "通知", "法规",
                                    "条例", "申报", "cbam", "碳市场", "核查",
                                    "碳达峰", "碳中和", "激励", "意见", "标准",
                                    "指南", "扶持", "regulation", "law",
                                    "subsidy", "allowance", "要求", "规定",
                                    "compliance", "trade", "legislation",
                                    "directive", "agreement")):
                behaviors.append("policy_search")
        elif tn == "profile_update":
            if any(k in q for k in ("记录", "更新", "画像", "偏好", "修改", "记",
                                    "profile", "关注", "记一笔", "标记", "兴趣",
                                    "加一笔", "加上", "减碳", "save", "record",
                                    "log", "track", "加一笔", "加")):
                behaviors.append("behavior_record")

    # 画像 / 偏好 / 兴趣细分子类
    if "profile_update" in tool_names:
        if any(k in q for k in ("偏好", "关注", "喜欢", "调整", "目标", "preference",
                                "interest", "incentive")):
            behaviors.append("preference_update")
        if any(k in q for k in ("兴趣", "关注领域", "interest")):
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
    """对每条 query 跑选择器 + 行为模拟,聚合多个 metric"""
    trigger_hits, behavior_hits = 0, 0
    n = len(entries)
    per_cat: Dict[str, Dict[str, int]] = {}
    per_skill: Dict[str, Dict[str, int]] = {}
    misses = []
    fallbacks = 0
    false_positives = 0  # 负例被错误触发的次数
    untriggered = []  # 应该触发但没触发的 query 列表

    for e in entries:
        q = e["query"]
        expected_skill = e.get("expected_skill", "")  # 可能为 null
        expected_behaviors = e.get("expected_behavior", []) or []
        cat = e.get("category", "?")
        lang = e.get("language", "zh")

        # 1. trigger 准确性
        picked = select_skill(q, skill_executor)
        # 处理 null expected_skill(负例):期望不触发
        if expected_skill is None:
            trigger_ok = picked is None
            if picked is not None:
                false_positives += 1
        else:
            trigger_ok = picked == expected_skill
            if picked is None:
                untriggered.append(q)

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

        # per-skill 统计(只看正例)
        if expected_skill:
            per_skill.setdefault(expected_skill, {"n": 0, "trigger_hit": 0, "behavior_hit": 0})
            per_skill[expected_skill]["n"] += 1
            if trigger_ok:
                per_skill[expected_skill]["trigger_hit"] += 1
            if behavior_ok:
                per_skill[expected_skill]["behavior_hit"] += 1

        if not trigger_ok or not behavior_ok:
            misses.append({
                "query": q,
                "expected_skill": expected_skill,
                "picked": picked,
                "expected_behaviors": expected_behaviors,
                "actual_behaviors": actual_behaviors,
                "category": cat,
                "language": lang,
            })

    n = n or 1
    return {
        "n": n,
        "trigger_accuracy": trigger_hits / n,
        "behavior_match_rate": behavior_hits / n,
        "fallback_rate": fallbacks / n,
        "false_positive_rate": false_positives / n,
        "per_category": per_cat,
        "per_skill": per_skill,
        "misses": misses,
        "untriggered": untriggered,
    }


def load_trend() -> Optional[Dict]:
    """加载上次评估结果(趋势对比)"""
    if not TREND_PATH.exists():
        return None
    try:
        return json.loads(TREND_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_trend(result: Dict, threshold: float, passed: bool) -> None:
    """保存当前评估结果到 trend 文件"""
    TREND_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": time.time(),
        "n": result["n"],
        "trigger_accuracy": result["trigger_accuracy"],
        "behavior_match_rate": result["behavior_match_rate"],
        "fallback_rate": result["fallback_rate"],
        "false_positive_rate": result["false_positive_rate"],
        "threshold": threshold,
        "passed": passed,
        "per_skill": {
            k: {"n": v["n"], "trigger_hit": v["trigger_hit"], "behavior_hit": v["behavior_hit"]}
            for k, v in result["per_skill"].items()
        },
    }
    TREND_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_report(result: Dict, prev: Optional[Dict], threshold: float) -> None:
    """写 data/skills_eval_report.md"""
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    lines.append("# Skills 触发评估报告 — P11.B (100+ 场景)")
    lines.append("")
    lines.append(f"- 总 query 数: **{result['n']}**")
    lines.append("")

    lines.append("## 总体指标")
    lines.append("")
    lines.append("| 指标 | 值 | 阈值 | 趋势 | 状态 |")
    lines.append("|---|---|---|---|---|")
    for label, key, thresh in [
        ("trigger_accuracy", "trigger_accuracy", f">= {threshold}"),
        ("behavior_match_rate", "behavior_match_rate", "(信息性)"),
        ("fallback_rate", "fallback_rate", "(越低越好)"),
        ("false_positive_rate", "false_positive_rate", "(越低越好)"),
    ]:
        cur = result[key]
        if prev and key in prev:
            delta = cur - prev[key]
            trend = f"{'+' if delta >= 0 else ''}{delta:.4f}"
        else:
            trend = "(基线)"
        if key == "trigger_accuracy":
            status = "PASS" if cur >= threshold else "FAIL"
        elif key == "fallback_rate":
            status = "-"
        else:
            status = "-"
        lines.append(f"| {label} | {cur:.4f} | {thresh} | {trend} | {status} |")
    lines.append("")

    lines.append("## 分类明细(P11.B 拆分)")
    lines.append("")
    lines.append("| 类目 | n | trigger_hit | behavior_hit |")
    lines.append("|---|---|---|---|")
    for cat, v in sorted(result["per_category"].items()):
        lines.append(
            f"| {cat} | {v['n']} | {v['trigger_hit']}/{v['n']} | "
            f"{v['behavior_hit']}/{v['n']} |"
        )
    lines.append("")

    lines.append("## 按 Skill 拆分")
    lines.append("")
    lines.append("| Skill | n | trigger_hit | behavior_hit | coverage |")
    lines.append("|---|---|---|---|---|")
    for skill, v in sorted(result["per_skill"].items()):
        cov = v["trigger_hit"] / v["n"] if v["n"] else 0
        lines.append(
            f"| {skill} | {v['n']} | {v['trigger_hit']}/{v['n']} | "
            f"{v['behavior_hit']}/{v['n']} | {cov:.1%} |"
        )
    lines.append("")

    if result["untriggered"]:
        lines.append(f"## 应该触发但未触发的 query({len(result['untriggered'])} 条)")
        lines.append("")
        lines.append("> 这些 query 期望触发某个 Skill,但选择器 fallback 到 None。")
        lines.append("> 可能原因:trigger keyword 没覆盖到此 query 的隐含意图。")
        lines.append("")
        for q in result["untriggered"]:
            lines.append(f"- `{q}`")
        lines.append("")

    if result["misses"]:
        lines.append(f"## 未命中明细({len(result['misses'])} 条)")
        lines.append("")
        for m in result["misses"]:
            lines.append(f"- **query**: `{m['query']}`  (类目: {m['category']}, lang: {m['language']})")
            lines.append(f"  - 期望 skill: `{m['expected_skill']}`  实际: `{m['picked']}`")
            lines.append(
                f"  - 期望 behaviors: {m['expected_behaviors']}  "
                f"实际: {m['actual_behaviors']}"
            )
        lines.append("")

    if prev:
        lines.append("## 与上次基线对比")
        lines.append("")
        for key in ("trigger_accuracy", "behavior_match_rate", "fallback_rate"):
            cur = result[key]
            base = prev.get(key, cur)
            delta = cur - base
            sign = "+" if delta >= 0 else ""
            lines.append(f"- **{key}**: {base:.4f} → {cur:.4f} ({sign}{delta:.4f})")
        lines.append("")

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Skills 触发评估(P11.B — 100+ 场景)")
    parser.add_argument(
        "--golden",
        default=str(GOLDEN_PATH),
        help="golden set 路径(默认 tests/eval/skills_golden_set.jsonl)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=THRESHOLD_TRIGGER,
        help=f"trigger_accuracy 阈值(默认 {THRESHOLD_TRIGGER})",
    )
    parser.add_argument(
        "--no-exit-code",
        action="store_true",
        help="不根据阈值返 exit code",
    )
    parser.add_argument(
        "--no-trend",
        action="store_true",
        help="不写 trend 文件",
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
    passed = result["trigger_accuracy"] >= args.threshold

    print()
    print("=== 评估结果 ===")
    print(f"  n                  = {result['n']}")
    print(f"  trigger_accuracy   = {result['trigger_accuracy']:.4f}  "
          f"(threshold >= {args.threshold})")
    print(f"  behavior_match_rate= {result['behavior_match_rate']:.4f}")
    print(f"  fallback_rate      = {result['fallback_rate']:.4f}")
    print(f"  false_positive_rate= {result['false_positive_rate']:.4f}")
    print()
    print("  分类明细:")
    for cat, v in sorted(result["per_category"].items()):
        print(f"    {cat:20s} n={v['n']:2d}  "
              f"trigger={v['trigger_hit']}/{v['n']}  "
              f"behavior={v['behavior_hit']}/{v['n']}")
    print()
    print("  按 Skill:")
    for skill, v in sorted(result["per_skill"].items()):
        cov = v["trigger_hit"] / v["n"] if v["n"] else 0
        print(f"    {skill:20s} n={v['n']:2d}  "
              f"trigger={v['trigger_hit']}/{v['n']}  "
              f"behavior={v['behavior_hit']}/{v['n']}  "
              f"coverage={cov:.1%}")
    print()
    print(f"  未命中: {len(result['misses'])} 条")
    print(f"  未触发(应触发但 fallback): {len(result['untriggered'])} 条")
    print(f"  报告:   {REPORT_PATH}")

    prev = load_trend()
    write_report(result, prev, args.threshold)

    if not args.no_trend:
        save_trend(result, args.threshold, passed)

    print()
    print(f"  状态: {'PASS' if passed else 'FAIL'}")

    if args.no_exit_code:
        sys.exit(0)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()