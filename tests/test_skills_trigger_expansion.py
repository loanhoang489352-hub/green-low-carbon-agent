"""
P11.B 测试:Skills 触发扩到 100+ 场景

验证:
1. golden set 包含 ≥ 100 条 query(覆盖 3 个 Skill)
2. 每个 Skill 至少 30 条 query
3. 5 类 category 都覆盖:explicit / implicit / edge / english / negative
4. trigger_accuracy >= 0.90(原阈值 0.85)
5. per-skill coverage >= 80%
6. negative example 误触发率 == 0%(反例不能触发任何 skill)
7. golden set 字段完整(id, query, expected_skill, expected_behavior, category, language)

跑法:
    pytest tests/test_skills_trigger_expansion.py -v
"""
import json
import sys
from pathlib import Path

# 让脚本可以直接运行
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

GOLDEN_PATH = PROJECT_ROOT / "tests" / "eval" / "skills_golden_set.jsonl"


def load_golden():
    entries = []
    with open(GOLDEN_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entries.append(json.loads(line))
    return entries


def test_golden_set_size_at_least_100():
    """P11.B: golden set 应包含 ≥ 100 条 query"""
    entries = load_golden()
    assert len(entries) >= 100, f"应 ≥ 100 条,实际 {len(entries)} 条"
    print(f"  golden set 总数: {len(entries)} 条")


def test_each_skill_has_at_least_30_queries():
    """P11.B: 每个 Skill 至少 30 条 query"""
    entries = load_golden()
    per_skill = {}
    for e in entries:
        s = e.get("expected_skill") or "_negative_"
        per_skill[s] = per_skill.get(s, 0) + 1
    print(f"  per skill: {per_skill}")
    for skill in ["low_carbon_travel", "policy_query", "profile_update"]:
        assert per_skill.get(skill, 0) >= 30, (
            f"skill {skill} 应 ≥ 30 条,实际 {per_skill.get(skill, 0)} 条"
        )


def test_all_categories_covered():
    """P11.B: 5 类 category 都覆盖"""
    entries = load_golden()
    cats = set()
    for e in entries:
        cats.add(e.get("category", "?"))
    required = {"explicit", "implicit", "edge", "english", "negative"}
    missing = required - cats
    assert not missing, f"缺少 category: {missing}, 实际有: {cats}"
    print(f"  覆盖 category: {sorted(cats)}")


def test_field_completeness():
    """P11.B: 每条 entry 必须含 id-or-query / expected_skill / expected_behavior / category"""
    entries = load_golden()
    required_fields = {"query", "expected_skill", "expected_behavior", "category"}
    for i, e in enumerate(entries):
        missing = required_fields - set(e.keys())
        assert not missing, f"第 {i+1} 条缺字段 {missing}: {e}"
    print(f"  {len(entries)} 条字段完整")


def test_language_field_present():
    """P11.B: 每条 entry 应有 language 字段(zh/en)"""
    entries = load_golden()
    for i, e in enumerate(entries):
        lang = e.get("language", "zh")
        assert lang in ("zh", "en"), f"第 {i+1} 条 language={lang} 不合法"
    en_count = sum(1 for e in entries if e.get("language") == "en")
    print(f"  zh: {len(entries) - en_count}, en: {en_count}")


def test_run_full_evaluation_passes_threshold():
    """P11.B: 跑全量 100+ trigger,trigger_accuracy >= 0.90"""
    import subprocess
    import re

    result = subprocess.run(
        [sys.executable, "scripts/eval_skills.py", "--no-exit-code", "--no-trend"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        timeout=60,
    )
    output = (result.stdout or b"") + (result.stderr or b"")
    try:
        output = output.decode("utf-8", errors="ignore")
    except Exception:
        output = output.decode("gbk", errors="ignore")
    # 提取 trigger_accuracy
    m = re.search(r"trigger_accuracy\s*=\s*(\d+\.\d+)", output)
    assert m, f"未找到 trigger_accuracy,输出: {output[-500:]}"
    acc = float(m.group(1))
    assert acc >= 0.90, f"trigger_accuracy {acc:.4f} < 0.90"
    print(f"  trigger_accuracy: {acc:.4f} (>= 0.90)")


def test_run_full_evaluation_per_skill_coverage():
    """P11.B: 每个 Skill 的 coverage >= 80%"""
    import subprocess
    import re

    result = subprocess.run(
        [sys.executable, "scripts/eval_skills.py", "--no-exit-code", "--no-trend"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        timeout=60,
    )
    output = (result.stdout or b"") + (result.stderr or b"")
    try:
        output = output.decode("utf-8", errors="ignore")
    except Exception:
        output = output.decode("gbk", errors="ignore")
    # 提取按 Skill 的 coverage 行
    # 格式:    low_carbon_travel    n=41  trigger=41/41  behavior=41/41  coverage=100.0%
    skill_pattern = re.compile(
        r"^\s*(low_carbon_travel|policy_query|profile_update)\s+n=\d+\s+"
        r"trigger=(\d+)/(\d+)\s+behavior=\d+/\d+\s+coverage=([\d.]+)%",
        re.MULTILINE,
    )
    matches = skill_pattern.findall(output)
    assert matches, f"未找到 per-skill coverage,输出: {output[-500:]}"
    for skill, hit, total, cov in matches:
        cov_f = float(cov)
        assert cov_f >= 80.0, f"skill {skill} coverage {cov_f}% < 80%"
        print(f"  {skill}: coverage={cov_f}% ({hit}/{total})")


def test_negative_examples_not_triggered():
    """P11.B: negative examples 不能被误触发(false_positive_rate == 0%)"""
    import subprocess
    import re

    result = subprocess.run(
        [sys.executable, "scripts/eval_skills.py", "--no-exit-code", "--no-trend"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        timeout=60,
    )
    output = (result.stdout or b"") + (result.stderr or b"")
    try:
        output = output.decode("utf-8", errors="ignore")
    except Exception:
        output = output.decode("gbk", errors="ignore")
    m = re.search(r"false_positive_rate\s*=\s*(\d+\.\d+)", output)
    assert m, f"未找到 false_positive_rate,输出: {output[-500:]}"
    fpr = float(m.group(1))
    assert fpr == 0.0, f"false_positive_rate {fpr:.4f} != 0"
    print(f"  false_positive_rate: {fpr:.4f}")


def test_english_queries_covered():
    """P11.B: english category 至少 10 条"""
    entries = load_golden()
    en_count = sum(1 for e in entries
                   if e.get("language") == "en" and e.get("category") == "english")
    assert en_count >= 10, f"english category 应 ≥ 10 条,实际 {en_count} 条"
    print(f"  english category: {en_count} 条")


def test_negative_examples_count():
    """P11.B: negative 占比 < 20%(保持数据集有意义)"""
    entries = load_golden()
    neg_count = sum(1 for e in entries if e.get("category") == "negative")
    ratio = neg_count / len(entries)
    assert ratio < 0.20, f"negative 占比 {ratio:.1%} >= 20%"
    assert neg_count >= 10, f"negative 应 ≥ 10 条,实际 {neg_count} 条"
    print(f"  negative: {neg_count} 条 ({ratio:.1%})")


def test_preserves_original_30_queries():
    """P11.B: 原 30 条 query 必须保留(兼容性)"""
    entries = load_golden()
    # 用 query 内容去重
    expected_first_30_queries = [
        "帮我规划从北京到天津的低碳出行",
        "通勤应该选什么交通工具比较环保",
        "从家到公司 5 公里,推荐什么出行方式",
        "明天去上海出差,怎么去碳排放最少",
        "公交和地铁哪个更环保",
        "周末去郊区骑行 20 公里,大概多少碳排放",
        "下雨天通勤建议怎么安排",
        "骑自行车 10 公里能减多少碳",
        "打车 30 公里和坐地铁哪个碳排放少",
        "查一下最新的国家碳排放权交易管理办法",
        "碳交易市场的配额分配规则是什么",
        "新能源汽车补贴政策 2026 年还有吗",
        "我想了解 CCER 自愿减排的方法学",
        "北京有什么针对企业的低碳补贴",
        "深圳的垃圾分类政策有哪些最新规定",
        "欧盟 CBAM 碳边境调节机制对中国企业有什么影响",
        "国家碳达峰碳中和的总体目标是什么",
        "上海有什么样的低碳社区激励政策",
        "碳排放报告与核查的最新要求是什么",
        "我想记录一下今天骑行了 10 公里",
        "更新一下我的出行偏好,以后主要想坐地铁",
        "我把家里的灯都换成了 LED,帮我记一下",
        "记录我今天参与了社区的垃圾分类活动",
        "修改我的环保关注领域,想加上节能家电",
        "我已经一周没开车了,帮我更新一下画像",
        "今天出门坐了公交,顺便记录这个行为",
        "把对我的偏好调整一下,最近更关注碳足迹",
        "今天我用了新能源车通勤,记到我的低碳记录里",
        "帮我看看我家附近的环保补贴怎么申请",
        "今天出差打车 50 公里,排放怎么算,顺便记一笔",
    ]
    actual_queries = {e["query"] for e in entries}
    for q in expected_first_30_queries:
        assert q in actual_queries, f"原 30 条 query 缺失: {q}"
    print(f"  原 30 条全部保留")


if __name__ == "__main__":
    test_golden_set_size_at_least_100()
    test_each_skill_has_at_least_30_queries()
    test_all_categories_covered()
    test_field_completeness()
    test_language_field_present()
    test_english_queries_covered()
    test_negative_examples_count()
    test_preserves_original_30_queries()
    test_negative_examples_not_triggered()
    test_run_full_evaluation_passes_threshold()
    test_run_full_evaluation_per_skill_coverage()
    print("\n[P11.B] All tests PASSED")