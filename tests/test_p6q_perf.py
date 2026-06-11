"""
P6.Q 性能 profiling 脚本 单元测试

覆盖:
1. bench_sqlite_pool 真实跑 N=100 ops → 返回 dict 含 latency_ms
2. bench_rag_retrieval 引擎未初始化时返 error(优雅降级)
3. bench_memory_recall 3 层各跑 N/3
4. bench_query_cache hit/miss 各跑 N
5. bench_api_endpoints 服务未跑时返 error
6. percentile 边界条件
7. render_report 生成 md + 详细 json
8. main() CLI 各 --only 选项
"""
import sys
from pathlib import Path
from unittest import mock

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / 'src'))

import pytest


# ========== 1. percentile ==========

def test_percentile_basic():
    from scripts.perf_benchmark import percentile
    assert percentile([1, 2, 3, 4, 5], 50) == 3
    assert percentile([1, 2, 3, 4, 5], 100) == 5
    assert percentile([1, 2, 3, 4, 5], 0) == 1
    assert percentile([], 50) == 0.0
    assert percentile([42], 50) == 42


def test_percentile_p99_single_value():
    from scripts.perf_benchmark import percentile
    assert percentile([100], 99) == 100


# ========== 2. summarize ==========

def test_summarize_basic():
    from scripts.perf_benchmark import summarize
    r = summarize("test", [1.0, 2.0, 3.0, 4.0, 5.0], 5, 0.5)
    assert r["name"] == "test"
    assert r["ops"] == 5
    assert r["throughput_ops_per_sec"] == 10  # 5 / 0.5
    assert r["latency_ms"]["avg"] == 3.0
    assert r["latency_ms"]["min"] == 1.0
    assert r["latency_ms"]["max"] == 5.0
    assert r["latency_ms"]["p50"] == 3.0


def test_summarize_empty():
    from scripts.perf_benchmark import summarize
    r = summarize("empty", [], 0, 0)
    assert r["name"] == "empty"
    assert "error" in r


# ========== 3. bench_sqlite_pool 真实跑 ==========

def test_bench_sqlite_pool_runs(tmp_path):
    """P6.Q: SQLite 池跑 N=20 → 应返 latency_ms + 吞吐"""
    from scripts.perf_benchmark import bench_sqlite_pool
    import scripts.perf_benchmark as pb
    # 确保 data/ 子目录存在 + 切 PROJECT_ROOT
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    with mock.patch.object(pb, "PROJECT_ROOT", tmp_path):
        r = bench_sqlite_pool(n_ops=20, n_threads=2)
    assert r["name"] == "SQLite 连接池"
    assert r["ops"] == 20
    assert "latency_ms" in r
    assert r["latency_ms"]["p50"] >= 0
    assert r["throughput_ops_per_sec"] > 0


# ========== 4. bench_rag_retrieval 引擎未初始化优雅降级 ==========

def test_bench_rag_engine_not_initialized(monkeypatch):
    """P6.Q: RAG engine 不可用时返 error 而非崩溃"""
    from scripts.perf_benchmark import bench_rag_retrieval
    fake_engine = mock.MagicMock()
    fake_engine._initialized = False
    monkeypatch.setattr("rag.rag_engine.get_rag_engine", lambda: fake_engine)
    r = bench_rag_retrieval(n_ops=10)
    assert "error" in r
    assert "未初始化" in r["error"]


def test_bench_rag_engine_returns_none(monkeypatch):
    """P6.Q: get_rag_engine() 返 None 时也优雅降级"""
    from scripts.perf_benchmark import bench_rag_retrieval
    monkeypatch.setattr("rag.rag_engine.get_rag_engine", lambda: None)
    r = bench_rag_retrieval(n_ops=10)
    assert "error" in r


# ========== 5. bench_memory_recall ==========

def test_bench_memory_recall_runs():
    """P6.Q: 三层记忆 3 层各跑 ~3 次"""
    from scripts.perf_benchmark import bench_memory_recall
    r = bench_memory_recall(n_ops=9)  # 每层 3
    assert r["name"] == "三层记忆召回"
    assert r["ops"] == 9
    for layer in ("stm", "wm", "ltm"):
        assert layer in r
        assert "avg" in r[layer]


# ========== 6. bench_query_cache hit/miss ==========

def test_bench_query_cache_runs(tmp_path):
    """P6.Q: hit/miss 各 N 次"""
    from scripts.perf_benchmark import bench_query_cache
    from agent.cache import reset_query_cache
    from db.connection import close_all
    import uuid
    # 清环境 + 切缓存路径
    reset_query_cache()
    close_all()
    r = bench_query_cache(n_ops=10)  # hit 5 + miss 5
    assert r["name"] == "Query Cache 命中 vs 未命中"
    assert r["ops"] == 20
    assert "hit" in r and "miss" in r
    # 清理
    close_all()


# ========== 7. bench_api_endpoints 服务未跑 ==========

def test_bench_api_service_down(monkeypatch):
    """P6.Q: 服务未跑时返 error"""
    from scripts.perf_benchmark import bench_api_endpoints
    import urllib.error
    # mock urlopen 抛 ConnectionRefusedError
    def fake_urlopen(*a, **kw):
        raise urllib.error.URLError("Connection refused")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    r = bench_api_endpoints(n_ops=10)
    assert "error" in r


# ========== 8. render_report 生成 md ==========

def test_render_report_basic(tmp_path):
    """P6.Q: render_report 写 md 含表格 + 详细 json"""
    from scripts.perf_benchmark import render_report

    results = [
        {"name": "test1", "ops": 100, "throughput_ops_per_sec": 200, "latency_ms": {
            "avg": 5.0, "min": 1.0, "max": 10.0, "p50": 5.0, "p95": 9.5, "p99": 9.9, "stdev": 1.0
        }},
        {"name": "test2", "ops": 0, "error": "测试错误"},
    ]
    report_path = tmp_path / "report.md"
    render_report(results, report_path, total_seconds=1.5)

    assert report_path.exists()
    content = report_path.read_text(encoding="utf-8")
    assert "# 性能 Profiling 报告" in content
    assert "test1" in content
    assert "test2" in content
    assert "测试错误" in content
    assert "关键发现" in content
    assert "```json" in content


# ========== 9. main() CLI ==========

def test_main_only_sqlite_runs(tmp_path, monkeypatch):
    """P6.Q: --only sqlite CLI 跑通"""
    from scripts import perf_benchmark as pb
    with mock.patch.object(pb, "PROJECT_ROOT", tmp_path):
        with mock.patch("sys.argv", ["perf_benchmark.py", "--only", "sqlite", "--n", "20", "--report", "data/test.md"]):
            rc = pb.main()
    assert rc == 0
    assert (tmp_path / "data" / "test.md").exists()


def test_main_only_rag_handles_no_engine(monkeypatch, tmp_path):
    """P6.Q: --only rag + 无 engine → 不崩,返 error"""
    from scripts import perf_benchmark as pb

    # mock RAG engine 不可用
    fake_engine = mock.MagicMock()
    fake_engine._initialized = False
    monkeypatch.setattr("rag.rag_engine.get_rag_engine", lambda: fake_engine)

    with mock.patch.object(pb, "PROJECT_ROOT", tmp_path):
        with mock.patch("sys.argv", ["perf_benchmark.py", "--only", "rag", "--n", "10", "--report", "data/test_rag.md"]):
            rc = pb.main()
    assert rc == 0
    content = (tmp_path / "data" / "test_rag.md").read_text(encoding="utf-8")
    assert "未初始化" in content


def test_main_no_args_runs_all(tmp_path, monkeypatch):
    """P6.Q: 不传 --only → 跑全部(测试 sqlite + cache + memory 3 个,跳过 rag/api)"""
    from scripts import perf_benchmark as pb
    # 强制 RAG / API 跳过(避免依赖)
    fake_engine = mock.MagicMock()
    fake_engine._initialized = False
    monkeypatch.setattr("rag.rag_engine.get_rag_engine", lambda: fake_engine)
    import urllib.error
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: (_ for _ in ()).throw(urllib.error.URLError("test")))

    with mock.patch.object(pb, "PROJECT_ROOT", tmp_path):
        with mock.patch("sys.argv", ["perf_benchmark.py", "--n", "10", "--report", "data/full.md"]):
            rc = pb.main()
    assert rc == 0
    content = (tmp_path / "data" / "full.md").read_text(encoding="utf-8")
    # sqlite + memory + cache 应过,RAG / API 应 fail 但不崩
    assert "SQLite" in content
    assert "三层记忆" in content
    assert "Query Cache" in content
