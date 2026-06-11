"""
性能 profiling 详细报告 — P6.Q

跑 5 大类基准测试,输出 data/perf_report.md
- P50 / P95 / P99 / 平均延迟分布
- 吞吐(req/s 或 ops/s)
- 推荐优化点

用法:
    python scripts/perf_benchmark.py                  # 全跑
    python scripts/perf_benchmark.py --only sqlite   # 只跑 SQLite 池
    python scripts/perf_benchmark.py --report data/my_perf.md

不依赖真实 LLM API(用 LLM_MOCK=true 或走 mock 路径)。
"""
import argparse
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def percentile(data: list[float], p: float) -> float:
    """计算 p 分位数(0-100)"""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    idx = int(len(sorted_data) * p / 100)
    idx = min(idx, len(sorted_data) - 1)
    return sorted_data[idx]


def summarize(name: str, latencies_ms: list[float], total_ops: int, total_seconds: float) -> dict:
    """生成单个测试的统计摘要"""
    if not latencies_ms:
        return {"name": name, "ops": total_ops, "error": "no data"}
    return {
        "name": name,
        "ops": total_ops,
        "total_seconds": round(total_seconds, 3),
        "throughput_ops_per_sec": round(total_ops / total_seconds, 2),
        "latency_ms": {
            "avg": round(statistics.mean(latencies_ms), 3),
            "min": round(min(latencies_ms), 3),
            "max": round(max(latencies_ms), 3),
            "p50": round(percentile(latencies_ms, 50), 3),
            "p95": round(percentile(latencies_ms, 95), 3),
            "p99": round(percentile(latencies_ms, 99), 3),
            "stdev": round(statistics.stdev(latencies_ms) if len(latencies_ms) > 1 else 0, 3),
        },
    }


# ========== 1. SQLite 连接池 ==========

def bench_sqlite_pool(n_ops: int = 1000, n_threads: int = 20) -> dict:
    """SQLite 连接池 吞吐基准"""
    import threading
    from db.connection import get_connection, close_all

    close_all()
    db_path = PROJECT_ROOT / "data" / "benchmark_pool.db"
    db_path.unlink(missing_ok=True)

    # 建表
    conn = get_connection(str(db_path))
    conn.execute("CREATE TABLE IF NOT EXISTS t (n INTEGER)")
    conn.execute("INSERT INTO t VALUES (0)")
    conn.commit()
    conn.close()
    close_all()

    latencies = []
    lock = threading.Lock()
    barrier = threading.Barrier(n_threads)

    def worker():
        nonlocal latencies
        barrier.wait()
        local = []
        for _ in range(n_ops // n_threads):
            start = time.time()
            c = get_connection(str(db_path))
            c.execute("UPDATE t SET n = n + 1")
            c.commit()
            local.append((time.time() - start) * 1000)
        with lock:
            latencies.extend(local)

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    start = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    total = time.time() - start

    close_all()
    # 留 db_path 清理给测试(避免 Windows 锁)
    return summarize("SQLite 连接池", latencies, n_ops, total)


# ========== 2. RAG 检索延迟 ==========

def bench_rag_retrieval(n_ops: int = 100) -> dict:
    """RAG 检索延迟分布(语义+BM25 混合)"""
    from rag.rag_engine import get_rag_engine

    engine = get_rag_engine()
    if engine is None or not getattr(engine, "_initialized", False):
        return {"name": "RAG 检索", "ops": 0, "error": "engine 未初始化(无 KB 或 mock 不可用)"}

    # 测试查询列表
    queries = [
        "北京有哪些低碳生活政策",
        "碳中和是什么意思",
        "如何减少碳排放",
        "绿色出行的好处",
        "垃圾分类指南",
    ] * (n_ops // 5)

    latencies = []
    for q in queries:
        start = time.time()
        try:
            engine.retrieve(q, top_k=5)
        except Exception as e:
            continue
        latencies.append((time.time() - start) * 1000)

    return summarize("RAG 检索", latencies, len(latencies), sum(latencies) / 1000)


# ========== 3. 三层记忆召回 ==========

def bench_memory_recall(n_ops: int = 100) -> dict:
    """三层记忆召回延迟(stm/wm/ltm 单独测)"""
    from memory.short_term import get_short_term_memory
    from memory.working import get_working_memory
    from memory.long_term import LongTermMemory
    import uuid

    # 准备数据
    uid = f"bench_{uuid.uuid4().hex[:8]}"
    stm = get_short_term_memory()
    wm = get_working_memory()
    ltm = LongTermMemory()

    # 短期记忆:加 5 条消息
    conv_id = f"bench_conv_{uuid.uuid4().hex[:8]}"
    for i in range(5):
        stm.add_message(conv_id, "user", f"msg {i}", metadata={})

    latencies = {"stm": [], "wm": [], "ltm": []}
    for _ in range(n_ops // 3):
        # STM 召回
        start = time.time()
        stm.get_conversation_history(conv_id)
        latencies["stm"].append((time.time() - start) * 1000)

        # WM 召回
        start = time.time()
        wm.get(uid, "current_focus")  # 不存在返 None
        latencies["wm"].append((time.time() - start) * 1000)

        # LTM 召回
        start = time.time()
        ltm.get_recent_memories(uid, limit=5)
        latencies["ltm"].append((time.time() - start) * 1000)

    # 合并结果
    return {
        "name": "三层记忆召回",
        "ops": n_ops,
        "stm": summarize("STM", latencies["stm"], n_ops // 3, sum(latencies["stm"]) / 1000).get("latency_ms", {}),
        "wm": summarize("WM", latencies["wm"], n_ops // 3, sum(latencies["wm"]) / 1000).get("latency_ms", {}),
        "ltm": summarize("LTM", latencies["ltm"], n_ops // 3, sum(latencies["ltm"]) / 1000).get("latency_ms", {}),
    }


# ========== 4. Query Cache 命中 vs 未命中 ==========

def bench_query_cache(n_ops: int = 100) -> dict:
    """Query Cache 命中/未命中延迟对比"""
    from agent.cache import QueryCache, get_query_cache, reset_query_cache
    from db.connection import close_all
    import tempfile
    import uuid

    reset_query_cache()
    close_all()

    db_path = Path(tempfile.gettempdir()) / f"bench_qc_{uuid.uuid4().hex[:8]}.db"
    # 唯一路径(不 unlink,避免 Windows 锁) — test fixture 结束自动 GC 释放
    cache = QueryCache(db_path=db_path, ttl=60.0)
    profile = {
        "basic_info": {"region": "北京"},
        "eco_profile": {
            "primary_interests": ["low_carbon_travel"],
            "knowledge_level": "intermediate",
            "behavior_stage": "意向",
        },
    }

    # 预热:写 1 条
    cache.set("test query", "u1", profile, "answer", ["s1"])

    hit_lat = []
    miss_lat = []
    for i in range(n_ops):
        # 命中(同一 query)
        start = time.time()
        cache.get("test query", "u1", profile)
        hit_lat.append((time.time() - start) * 1000)

        # 未命中(新 query)
        start = time.time()
        cache.get(f"miss query {i}", "u1", profile)
        miss_lat.append((time.time() - start) * 1000)

    # db_path 留给 GC 释放,不显式 unlink(避免 Windows 文件锁)
    import gc
    gc.collect()
    return {
        "name": "Query Cache 命中 vs 未命中",
        "ops": n_ops * 2,
        "hit": summarize("Hit", hit_lat, n_ops, sum(hit_lat) / 1000).get("latency_ms", {}),
        "miss": summarize("Miss", miss_lat, n_ops, sum(miss_lat) / 1000).get("latency_ms", {}),
    }


# ========== 5. Web API 端到端(httpx 模拟) ==========

def bench_api_endpoints(n_ops: int = 100) -> dict:
    """Web API 端到端延迟(/api/health, /api/metrics)"""
    import urllib.request
    import urllib.error

    url = "http://localhost:8000"
    # 检查服务是否在跑
    try:
        with urllib.request.urlopen(f"{url}/api/ready", timeout=2) as r:
            if r.status != 200:
                return {"name": "Web API", "error": "服务未运行在 :8000(请先启动 cd src && python main.py)"}
    except Exception as e:
        return {"name": "Web API", "error": f"服务未运行: {e}"}

    endpoints = ["/api/health", "/api/ready", "/api/metrics"]
    results = {}
    for ep in endpoints:
        latencies = []
        for _ in range(n_ops // len(endpoints)):
            start = time.time()
            try:
                with urllib.request.urlopen(f"{url}{ep}", timeout=10) as r:
                    r.read()
            except Exception:
                continue
            latencies.append((time.time() - start) * 1000)
        results[ep] = summarize(ep, latencies, len(latencies), sum(latencies) / 1000).get("latency_ms", {})

    return {
        "name": "Web API 端到端",
        "ops": n_ops,
        "endpoints": results,
    }


# ========== 报告生成 ==========

def render_report(results: list[dict], report_path: Path, total_seconds: float) -> None:
    lines = [
        f"# 性能 Profiling 报告 — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"**总耗时**: {total_seconds:.2f}s",
        f"**测试项数**: {len(results)}",
        "",
        "## 摘要",
        "",
        "| 测试项 | 操作数 | 吞吐(ops/s) | 平均 | P50 | P95 | P99 |",
        "|--------|--------|-------------|------|-----|-----|-----|",
    ]
    for r in results:
        if "error" in r:
            lines.append(f"| {r['name']} | - | - | {r['error']} | - | - | - |")
            continue
        lat = r.get("latency_ms", {})
        if not lat:
            # 嵌套结果(SQLite 池、Query Cache、API 端点、三层记忆)
            if "stm" in r:  # 三层记忆
                lines.append(f"| 三层记忆(整体) | {r['ops']} | - | - | - | - | - |")
                for layer in ("stm", "wm", "ltm"):
                    sub = r[layer]
                    if sub:
                        lines.append(
                            f"| &nbsp;&nbsp;{layer.upper()} | - | - | {sub['avg']:.3f}ms | {sub['p50']:.3f} | {sub['p95']:.3f} | {sub['p99']:.3f} |"
                        )
            elif "hit" in r:  # Query Cache
                lines.append(f"| Query Cache(hit) | {r['ops']//2} | - | {r['hit']['avg']:.3f}ms | - | - | - |")
                lines.append(f"| Query Cache(miss) | {r['ops']//2} | - | {r['miss']['avg']:.3f}ms | - | - | - |")
            elif "endpoints" in r:  # Web API
                lines.append(f"| Web API(整体) | {r['ops']} | - | - | - | - | - |")
                for ep, sub in r['endpoints'].items():
                    if sub:
                        lines.append(
                            f"| &nbsp;&nbsp;{ep} | - | - | {sub['avg']:.3f}ms | {sub['p50']:.3f} | {sub['p95']:.3f} | {sub['p99']:.3f} |"
                        )
            else:
                lines.append(f"| {r['name']} | {r.get('ops', '?')} | - | (详见子项) | - | - | - |")
            continue
        throughput = r.get("throughput_ops_per_sec", "-")
        lines.append(
            f"| {r['name']} | {r.get('ops', '?')} | {throughput} | "
            f"{lat.get('avg', 0):.3f}ms | {lat.get('p50', 0):.3f} | "
            f"{lat.get('p95', 0):.3f} | {lat.get('p99', 0):.3f} |"
        )

    lines.append("")
    lines.append("## 详细数据")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(results, ensure_ascii=False, indent=2))
    lines.append("```")

    lines.append("")
    lines.append("## 关键发现 / 推荐")
    lines.append("")
    # 简单推荐规则
    for r in results:
        lat = r.get("latency_ms", {})
        if not lat:
            continue
        p95 = lat.get("p95", 0)
        if p95 > 100:
            lines.append(f"- **{r['name']}**: P95 {p95:.1f}ms 偏高 → 考虑加缓存或异步化")
        elif p95 > 50:
            lines.append(f"- **{r['name']}**: P95 {p95:.1f}ms → 当前可接受")
        else:
            lines.append(f"- **{r['name']}**: P95 {p95:.1f}ms → 性能良好")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[OK] 报告写入: {report_path}")


# ========== 入口 ==========

def main():
    parser = argparse.ArgumentParser(description="P6.Q: 性能 profiling")
    parser.add_argument("--only", choices=["sqlite", "rag", "memory", "cache", "api"],
                        help="只跑某个测试")
    parser.add_argument("--report", default="data/perf_report.md", help="报告路径")
    parser.add_argument("--n", type=int, default=200, help="每个测试的操作数")
    args = parser.parse_args()

    # 强制 LLM_MOCK(避免真实 API 阻塞)
    import os
    os.environ["LLM_MOCK"] = "true"

    benches = {
        "sqlite": ("SQLite 连接池", bench_sqlite_pool),
        "rag": ("RAG 检索", bench_rag_retrieval),
        "memory": ("三层记忆召回", bench_memory_recall),
        "cache": ("Query Cache 命中 vs 未命中", bench_query_cache),
        "api": ("Web API 端到端", bench_api_endpoints),
    }

    if args.only:
        targets = [args.only]
    else:
        targets = list(benches.keys())

    print(f"[INFO] 跑 {len(targets)} 个基准测试,每次 {args.n} ops ...")
    results = []
    start = time.time()
    for key in targets:
        name, fn = benches[key]
        print(f"  - {name} ... ", end="", flush=True)
        try:
            r = fn(n_ops=args.n)
        except Exception as e:
            r = {"name": name, "error": f"{type(e).__name__}: {e}"}
        print("OK" if "error" not in r else f"FAIL: {r.get('error', '?')[:50]}")
        results.append(r)

    total = time.time() - start

    # 报告
    report_path = PROJECT_ROOT / args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    render_report(results, report_path, total)
    print(f"\n[INFO] 总耗时 {total:.2f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
