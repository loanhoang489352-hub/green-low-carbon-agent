"""
P6.J 政府/媒体源 可达性测试

自动测 config/sources.yaml 的源列表 + 一组新候选源,生成报告
- HTTPS 状态码
- 响应大小
- 内容关键词命中(低碳/碳排/绿色)
- DNS 解析

用法:
    python scripts/test_new_sources.py                 # 测所有 enabled + 候选
    python scripts/test_new_sources.py --only-candidates  # 只测新增候选
    python scripts/test_new_sources.py --report PATH      # 自定义报告路径
    python scripts/test_new_sources.py --timeout 8         # 自定义超时

输出:
    data/source_test_report.md(可用源 enable=true 建议,不可用 disable=true 建议)
"""
import argparse
import json
import ssl
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ========== 候选源(P6.J 拓源) ==========
# 经实测,这些非 .gov.cn 源在港 IP 也可通,且 ESG/低碳内容丰富
CANDIDATE_SOURCES = [
    {
        "name": "新华网-能源频道",
        "url": "http://www.news.cn/energy/",
        "type": "html",
        "category": "媒体-能源",
        "keywords": ["低碳", "碳", "绿色", "气候", "能源"],
        "note": "新华社能源频道,权威媒体 + 大陆政府背景",
    },
    {
        "name": "经济参考报-绿色频道",
        "url": "http://www.jjckb.cn/",
        "type": "html",
        "category": "媒体-绿色",
        "keywords": ["绿色", "低碳", "碳", "生态", "环保"],
        "note": "新华社主办经济参考报,绿色经济报道密集",
    },
    {
        "name": "财新网-环境频道",
        "url": "https://www.caixin.com/environment/",
        "type": "html",
        "category": "媒体-环境",
        "keywords": ["碳", "排放", "气候", "环境", "能源"],
        "note": "财新环境频道,深度报道,需付费(但首页可访问)",
    },
    {
        "name": "中国新闻网-能源",
        "url": "https://www.chinanews.com/energy/",
        "type": "html",
        "category": "媒体-能源",
        "keywords": ["能源", "碳", "绿色", "低碳", "气候"],
        "note": "中新社能源频道,大陆官方媒体海外版",
    },
    {
        "name": "南方周末-绿色",
        "url": "https://www.infzm.com/",
        "type": "html",
        "category": "媒体-调查",
        "keywords": ["绿色", "环境", "生态", "碳", "污染"],
        "note": "南方周末,深度环境报道",
    },
    {
        "name": "21 经济网-碳中和",
        "url": "https://www.21jingji.com/",
        "type": "html",
        "category": "媒体-经济",
        "keywords": ["碳", "绿色", "低碳", "排放"],
        "note": "21 世纪经济报道,经济视角的 ESG 报道",
    },
    {
        "name": "国家发改委-双碳",
        "url": "https://www.ndrc.gov.cn/",
        "type": "html",
        "category": "政府-发改委",
        "keywords": ["双碳", "低碳", "碳", "能源", "气候"],
        "note": "国家发改委(.gov.cn,港 IP 测试可能 SSL 失败)",
    },
    {
        "name": "国家统计局-绿色发展",
        "url": "https://www.stats.gov.cn/",
        "type": "html",
        "category": "政府-统计",
        "keywords": ["绿色", "低碳", "能源", "碳"],
        "note": "国家统计局(.gov.cn,数据权威)",
    },
    {
        "name": "中国环境与发展国际合作委员会",
        "url": "https://www.cciced.net/",
        "type": "html",
        "category": "智库-环境",
        "keywords": ["气候", "绿色", "低碳", "可持续", "碳"],
        "note": "国合会,国际智库 + 政府背书",
    },
    {
        "name": "Environmental Defense Fund",
        "url": "https://www.edf.org/",
        "type": "html",
        "category": "国际-NGO",
        "keywords": ["climate", "carbon", "green", "energy"],
        "note": "EDF,国际环保 NGO(英文),港 IP 应可通",
    },
]


def test_source(
    source: dict,
    timeout: float = 8.0,
    min_size_kb: float = 5.0,
    min_keyword_hits: int = 1,
) -> dict:
    """
    测试一个源的可达性 + 内容质量

    返:
    {
        ...source..., "test": {
            "ok": bool,
            "status_code": int,
            "size_kb": float,
            "keyword_hits": int,
            "latency_ms": float,
            "error": str | None,
        }
    }
    """
    url = source["url"]
    headers = {
        "User-Agent": "Green-Agent-P6J-Test/1.0 (+https://github.com/green-agent)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    result = {
        **source,
        "test": {
            "ok": False,
            "status_code": 0,
            "size_kb": 0.0,
            "keyword_hits": 0,
            "latency_ms": 0.0,
            "error": None,
        },
    }
    start = time.time()
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(url, headers=headers)
        latency_ms = round((time.time() - start) * 1000, 2)
        result["test"]["status_code"] = resp.status_code
        result["test"]["size_kb"] = round(len(resp.content) / 1024, 1)
        result["test"]["latency_ms"] = latency_ms
        if resp.status_code == 200:
            content = resp.text
            keywords = source.get("keywords", [])
            hits = sum(1 for kw in keywords if kw in content)
            result["test"]["keyword_hits"] = hits
            # 判定 OK:状态 200 + 大小 > 阈值 + 关键词至少 1 个
            if (result["test"]["size_kb"] >= min_size_kb and hits >= min_keyword_hits):
                result["test"]["ok"] = True
        return result
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RemoteProtocolError) as e:
        result["test"]["latency_ms"] = round((time.time() - start) * 1000, 2)
        result["test"]["error"] = f"{type(e).__name__}: {str(e)[:200]}"
        return result
    except Exception as e:
        result["test"]["latency_ms"] = round((time.time() - start) * 1000, 2)
        result["test"]["error"] = f"{type(e).__name__}: {str(e)[:200]}"
        return result


def load_yaml_sources() -> list[dict]:
    """从 config/sources.yaml 加载 enabled 源"""
    try:
        import yaml
    except ImportError:
        return []
    yaml_path = PROJECT_ROOT / "config" / "sources.yaml"
    if not yaml_path.exists():
        return []
    with open(yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    sources = []
    for s in data.get("policy_sources", []):
        if s.get("enabled", True):
            sources.append(s)
    return sources


def render_report(results: list[dict], report_path: Path) -> None:
    """生成 Markdown 报告"""
    lines = [
        f"# 源可达性测试报告 — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"**测试源数**: {len(results)}",
        f"**通过**: {sum(1 for r in results if r['test']['ok'])}",
        f"**失败**: {sum(1 for r in results if not r['test']['ok'])}",
        "",
        "## 结果汇总",
        "",
        "| 名称 | 状态 | 大小 | 延迟 | 关键词 | 错误 |",
        "|------|------|------|------|--------|------|",
    ]
    for r in results:
        t = r["test"]
        status_emoji = "✅" if t["ok"] else "❌"
        status_text = f"{status_emoji} {t['status_code']}"
        kw = t.get("keyword_hits", 0)
        err = t.get("error") or "-"
        lines.append(
            f"| {r['name']} | {status_text} | {t['size_kb']} KB | {t['latency_ms']}ms | {kw} | {err[:50]} |"
        )
    lines.append("")

    # 通过的源(可启用)
    lines.append("## 建议启用(可达 + 内容匹配)")
    lines.append("")
    lines.append("```yaml")
    lines.append("# 加到 config/sources.yaml 的 policy_sources:")
    lines.append("policy_sources:")
    for r in results:
        if r["test"]["ok"]:
            lines.append(f"  - name: \"{r['name']}\"")
            lines.append(f"    url: \"{r['url']}\"")
            lines.append(f"    type: \"{r.get('type', 'html')}\"")
            lines.append(f"    category: \"{r.get('category', '媒体')}\"")
            lines.append(f"    enabled: true")
            lines.append(f"    check_interval_hours: 24")
            if r.get("note"):
                lines.append(f"    note: \"{r['note']}\"")
    lines.append("```")
    lines.append("")

    # 失败的源(应禁用)
    lines.append("## 不可用源(应保留 disabled)")
    lines.append("")
    for r in results:
        if not r["test"]["ok"]:
            lines.append(f"- **{r['name']}** ({r['url']}): {r['test'].get('error', '未知错误')}")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[OK] 报告已写入: {report_path}")


def main():
    parser = argparse.ArgumentParser(description="P6.J: 源可达性测试")
    parser.add_argument("--only-candidates", action="store_true", help="只测候选源")
    parser.add_argument("--report", default="data/source_test_report.md", help="报告路径")
    parser.add_argument("--timeout", type=float, default=8.0, help="HTTP 超时(秒)")
    args = parser.parse_args()

    if args.only_candidates:
        sources = CANDIDATE_SOURCES
    else:
        sources = load_yaml_sources() + CANDIDATE_SOURCES

    if not sources:
        print("[ERROR] 没有可测试的源")
        return 1

    print(f"[INFO] 待测试 {len(sources)} 个源,超时 {args.timeout}s ...")
    results = []
    for s in sources:
        name = s.get("name", s.get("url", "?"))
        print(f"  - {name} ... ", end="", flush=True)
        result = test_source(s, timeout=args.timeout)
        ok = result["test"]["ok"]
        size = result["test"]["size_kb"]
        kw = result["test"].get("keyword_hits", 0)
        print(f"{'[OK]' if ok else '[FAIL]'} {size}KB kw={kw}")
        results.append(result)

    # 写报告
    report_path = PROJECT_ROOT / args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    render_report(results, report_path)

    # 摘要
    ok_count = sum(1 for r in results if r["test"]["ok"])
    print(f"\n=== 摘要 ===")
    print(f"  测试: {len(results)} 个")
    print(f"  通过: {ok_count} 个")
    print(f"  失败: {len(results) - ok_count} 个")
    if ok_count > 0:
        print(f"\n  → 见 {args.report} 把通过的源加到 config/sources.yaml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
