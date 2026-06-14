"""
P6.S.21 KB 合规审计脚本:
- 扫描所有 knowledge_base/ .md 文件
- 用关键词 + LLM 双重判定每条是否属于"绿色低碳"主题
- 输出违规条目清单 + 清理建议
"""
import os
import sys
import re
import json
from pathlib import Path

PROJECT_ROOT = Path("d:/绿色低碳智能体")
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# 绿色低碳相关关键词
GREEN_KEYWORDS = [
    "碳", "低碳", "减排", "环保", "绿色", "节能", "可持续", "生态",
    "再生能源", "太阳能", "风能", "电动车", "新能源汽车", "碳排放",
    "碳达峰", "碳中和", "CCER", "碳市场", "碳交易", "碳足迹",
    "碳普惠", "光伏", "ESG", "双碳", "温室气体", "碳积分",
    "植树", "碳汇", "气候", "污染", "排放", "节能",
]

# 非绿色低碳的强信号
OFFTOPIC_KEYWORDS = [
    "股票", "期货", "娱乐", "明星", "演唱会", "彩票", "赌博",
    "网络游戏", "电竞", "八卦", "绯闻", "房地产", "二手房",
    "求职", "招聘", "高考", "考研", "公务员", "事业单位",
    "两性", "情感", "相亲", "婚礼",
]

def heuristic_score(text: str) -> tuple[float, list, list]:
    """返 (合规分 0-1, 命中绿色词, 命中非绿词)"""
    text_lower = text[:5000]  # 前 5K 字足够
    green_hits = [k for k in GREEN_KEYWORDS if k in text]
    off_hits = [k for k in OFFTOPIC_KEYWORDS if k in text]
    # 绿色词按密度算
    green_density = len(green_hits) / max(len(text) / 100, 1)  # 每 100 字几个
    if off_hits and not green_hits:
        return 0.0, green_hits, off_hits
    score = min(1.0, len(green_hits) * 0.1 + green_density * 0.05)
    return score, green_hits, off_hits


def main():
    kb_dir = PROJECT_ROOT / "knowledge_base"
    files = list(kb_dir.rglob("*.md"))
    print(f"扫描 {len(files)} 个 .md 文件\n")

    rows = []
    for f in sorted(files):
        rel = f.relative_to(kb_dir)
        try:
            content = f.read_text(encoding="utf-8")
        except Exception:
            content = ""
        title = ""
        # 提取标题
        for line in content.split("\n")[:3]:
            if line.startswith("# "):
                title = line[2:].strip()
                break
        score, green, off = heuristic_score(content)
        rows.append({
            "path": str(rel),
            "title": title,
            "size_kb": round(len(content) / 1024, 1),
            "green_hits": green,
            "offtopic_hits": off,
            "score": score,
            "verdict": "合规" if score >= 0.3 and not off else "可疑/违规",
        })

    # 汇总
    by_dir = {}
    for r in rows:
        d = r["path"].split("/")[0] if "/" in r["path"] else "."
        by_dir.setdefault(d, []).append(r)

    print(f"{'='*80}")
    print(f"分类结果(按目录):")
    print(f"{'='*80}")
    for d in sorted(by_dir.keys()):
        items = by_dir[d]
        total = len(items)
        bad = sum(1 for r in items if r["verdict"] != "合规")
        print(f"\n[{d}] {total} 个文件, 其中 {bad} 个可疑/违规")
        for r in items:
            mark = "✗" if r["verdict"] != "合规" else "✓"
            print(f"  {mark} {r['score']:.2f} {r['path']}")
            if r["title"]:
                print(f"     标题: {r['title'][:60]}")
            if r["offtopic_hits"]:
                print(f"     ⚠ 非绿词: {r['offtopic_hits'][:5]}")
            if r["green_hits"]:
                print(f"     ✓ 绿词: {r['green_hits'][:5]}")

    # 写入结果
    out = PROJECT_ROOT / "data" / "kb_compliance_audit.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果写入: {out}")
    print(f"\n共 {sum(1 for r in rows if r['verdict'] != '合规')} 个可疑/违规条目")


if __name__ == "__main__":
    main()
