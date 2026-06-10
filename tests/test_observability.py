"""
可观测性契约测试 (P5-B 安全网)

覆盖:
1. trace_id 唯一性 + 长度
2. with_trace context manager 隔离
3. JSON formatter 输出结构正确
4. MetricsCollector 聚合(P50/P95 + by_provider)
5. 6 LLM provider 注入 trace_id
6. /api/metrics 端点路由
"""

import sys
import json
import logging
import tempfile
from pathlib import Path
from io import StringIO

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / 'src'))

import pytest


# ========== 1. trace_id 契约 ==========

def test_new_trace_id_length_and_format():
    """trace_id 12 位 hex"""
    from observability import new_trace_id
    tid = new_trace_id()
    assert len(tid) == 12
    assert all(c in "0123456789abcdef" for c in tid)


def test_trace_id_uniqueness():
    """连续 1000 次生成无重复"""
    from observability import new_trace_id
    tids = {new_trace_id() for _ in range(1000)}
    assert len(tids) == 1000


def test_get_trace_id_default():
    """无上下文时返回 '-'"""
    from observability import get_trace_id
    # 在子线程中跑(隔离)
    import threading
    result = []
    def worker():
        result.append(get_trace_id())
    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert result[0] == "-"


def test_with_trace_context():
    """with_trace 块内可拿到 trace_id,块外恢复"""
    from observability import with_trace, get_trace_id, new_trace_id
    assert get_trace_id() == "-"
    with with_trace() as tid:
        assert len(tid) == 12
        assert get_trace_id() == tid
    assert get_trace_id() == "-"


def test_with_trace_nested():
    """嵌套 with_trace 正确恢复"""
    from observability import with_trace, get_trace_id
    with with_trace() as outer:
        assert get_trace_id() == outer
        with with_trace() as inner:
            assert get_trace_id() == inner
            assert inner != outer
        assert get_trace_id() == outer
    assert get_trace_id() == "-"


def test_with_trace_accepts_explicit_id():
    """with_trace(trace_id=...) 用指定 ID"""
    from observability import with_trace, get_trace_id
    with with_trace(trace_id="my_custom_id"):
        assert get_trace_id() == "my_custom_id"


# ========== 2. JSON Formatter ==========

def test_json_formatter_basic_fields():
    """JSON formatter 输出必备字段"""
    from observability import JSONFormatter
    fmt = JSONFormatter()
    rec = logging.LogRecord(
        name="test", level=logging.INFO, pathname="x.py", lineno=1,
        msg="hello", args=(), exc_info=None,
    )
    out = fmt.format(rec)
    parsed = json.loads(out)
    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "test"
    assert parsed["msg"] == "hello"
    assert "ts" in parsed
    assert "trace_id" in parsed


def test_json_formatter_extra_fields():
    """JSON formatter 透传 extra 字段"""
    from observability import JSONFormatter
    fmt = JSONFormatter()
    rec = logging.LogRecord(
        name="test", level=logging.INFO, pathname="x.py", lineno=1,
        msg="event", args=(), exc_info=None,
    )
    rec.k = "value"
    rec.count = 42
    out = fmt.format(rec)
    parsed = json.loads(out)
    assert parsed["k"] == "value"
    assert parsed["count"] == 42


def test_json_formatter_trace_id_from_context():
    """JSON formatter 拿当前 ContextVar 的 trace_id"""
    from observability import JSONFormatter, with_trace
    fmt = JSONFormatter()
    with with_trace() as tid:
        rec = logging.LogRecord(
            name="test", level=logging.INFO, pathname="x.py", lineno=1,
            msg="inside", args=(), exc_info=None,
        )
        out = fmt.format(rec)
        parsed = json.loads(out)
        assert parsed["trace_id"] == tid


# ========== 3. setup_logging ==========

def test_setup_logging_creates_file():
    """setup_logging 写文件成功"""
    from observability import setup_logging, get_logger
    import os, logging as _logging
    tmp = tempfile.mkdtemp(prefix="obs_test_")
    log_path = os.path.join(tmp, "test.log")
    setup_logging(level="INFO", log_file=log_path, also_stdout=False)
    try:
        log = get_logger("test_setup")
        log.info("hello world", extra={"k": "v"})
        assert os.path.exists(log_path)
        content = Path(log_path).read_text(encoding="utf-8")
        assert "hello world" in content
        assert '"k": "v"' in content
    finally:
        # 关键: 拆掉刚装的 FileHandler, 否则后续测试还会写已删的 tmp 目录
        for h in list(_logging.getLogger().handlers):
            _logging.getLogger().removeHandler(h)
            try:
                h.close()
            except Exception:
                pass
        import shutil
        try:
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:
            pass


# ========== 4. MetricsCollector ==========

def test_metrics_empty_summary():
    """空 metrics 返合理默认值"""
    from observability import MetricsCollector
    m = MetricsCollector()
    s = m.summary()
    assert s["total_calls"] == 0
    assert s["error_rate"] == 0.0
    assert s["p50_latency_ms"] == 0.0
    assert s["by_provider"] == {}


def test_metrics_record_and_aggregate():
    """record 后 summary 正确聚合"""
    from observability import MetricsCollector
    m = MetricsCollector()
    for _ in range(5):
        m.record(provider="openai", model="gpt-4", latency_ms=100.0, success=True, prompt_tokens=10, completion_tokens=20, total_tokens=30)
    for _ in range(3):
        m.record(provider="openai", model="gpt-4", latency_ms=200.0, success=True, prompt_tokens=15, completion_tokens=25, total_tokens=40)
    m.record(provider="openai", model="gpt-4", latency_ms=5000.0, success=False, error="timeout")
    s = m.summary()
    assert s["total_calls"] == 9
    assert s["success_calls"] == 8
    assert s["failed_calls"] == 1
    assert abs(s["error_rate"] - 1/9) < 0.01
    assert s["total_prompt_tokens"] == 5*10 + 3*15
    assert s["total_completion_tokens"] == 5*20 + 3*25
    assert s["total_tokens"] == 5*30 + 3*40
    # P50 计算:所有 9 个 latency 排序 [100*5, 200*3, 5000], index = (9-1)*0.5 = 4
    # values[4]=100, values[5]=200, P50 = 100 + (200-100)*0 = 100
    assert abs(s["p50_latency_ms"] - 100.0) < 1.0, f"expected 100, got {s['p50_latency_ms']}"
    # by_provider
    assert "openai" in s["by_provider"]
    assert s["by_provider"]["openai"]["total_calls"] == 9
    assert s["by_provider"]["openai"]["failed_calls"] == 1


def test_metrics_by_provider_separation():
    """按 provider 分组正确"""
    from observability import MetricsCollector
    m = MetricsCollector()
    m.record(provider="openai", model="gpt-4", latency_ms=100.0, success=True)
    m.record(provider="mock", model="mock", latency_ms=1.0, success=True)
    m.record(provider="mock", model="mock", latency_ms=2.0, success=False)
    s = m.summary()
    assert set(s["by_provider"].keys()) == {"openai", "mock"}
    assert s["by_provider"]["mock"]["failed_calls"] == 1
    assert s["by_provider"]["mock"]["error_rate"] == 0.5


def test_metrics_p95_calculation():
    """P95 计算合理性(100 个点 P95 在 95 左右)"""
    from observability import MetricsCollector
    m = MetricsCollector()
    for i in range(100):
        m.record(provider="x", model="m", latency_ms=float(i), success=True)
    s = m.summary()
    # 排序后 latency 0..99, P95 = 0 + (99-0)*0.95 = 94.05
    assert 94.0 < s["p95_latency_ms"] < 95.0


def test_metrics_history_limit():
    """历史超过 maxlen 自动丢弃"""
    from observability import MetricsCollector
    m = MetricsCollector(max_history=10)
    for i in range(20):
        m.record(provider="x", model="m", latency_ms=float(i), success=True)
    s = m.summary()
    assert s["history_size"] == 10
    assert s["total_calls"] == 10


def test_metrics_singleton():
    """get_metrics_collector 返同一实例"""
    from observability import get_metrics_collector, reset_metrics_collector
    reset_metrics_collector()
    a = get_metrics_collector()
    b = get_metrics_collector()
    assert a is b


# ========== 5. 6 LLM provider 注入 trace_id ==========

def test_all_6_providers_inject_request_id():
    """6 provider chat() 返回 LLMResponse.request_id 非 None"""
    from llm import LLMResponse
    from observability import reset_metrics_collector
    from llm.client import (
        OpenAIClient, ZhipuClient, BaiduClient, AliClient,
        MiniMaxClient, DeepSeekClient, MockLLMClient,
    )
    reset_metrics_collector()
    providers = [
        OpenAIClient(), ZhipuClient(), BaiduClient(),
        AliClient(), MiniMaxClient(), DeepSeekClient(), MockLLMClient(),
    ]
    for c in providers:
        out = c.chat([{"role": "user", "content": "测试碳中和"}])
        assert isinstance(out, LLMResponse)
        assert out.request_id is not None, f"{type(c).__name__} 没填 request_id"
        assert len(out.request_id) == 12, f"{type(c).__name__} request_id 长度 != 12"


def test_all_6_providers_record_metrics():
    """6 provider 都会写 MetricsCollector"""
    from observability import get_metrics_collector, reset_metrics_collector
    from llm.client import (
        OpenAIClient, ZhipuClient, BaiduClient, AliClient,
        MiniMaxClient, DeepSeekClient, MockLLMClient,
    )
    reset_metrics_collector()
    m = get_metrics_collector()
    for c in [OpenAIClient(), ZhipuClient(), BaiduClient(), AliClient(), MiniMaxClient(), DeepSeekClient(), MockLLMClient()]:
        c.chat([{"role": "user", "content": "测试"}])
    s = m.summary()
    assert s["total_calls"] >= 7  # 7 个 provider 各调一次


def test_bayesian_router_preserves_trace_id():
    """BayesianRouter 透传 trace_id 到子 client"""
    from llm import LLMResponse
    from observability import reset_metrics_collector
    from llm.client import MockLLMClient, BayesianModelRouter
    reset_metrics_collector()
    router = BayesianModelRouter(strategy="thompson", auto_add_clients=False)
    router.register_model("mock", MockLLMClient(), "mock-v1")
    router._clients["mock"]._is_available = lambda: True
    out = router.chat([{"role": "user", "content": "测试"}], force_model="mock")
    assert isinstance(out, LLMResponse)
    assert out.request_id is not None
    assert len(out.request_id) == 12


# ========== 6. /api/metrics 端点 ==========

def test_metrics_endpoint_registered():
    """/api/metrics 路由已注册"""
    from server.router import RouterRegistry
    from server.routers.system import register_system_routes
    reg = RouterRegistry()
    register_system_routes(reg)
    route = reg.find("GET", "/api/metrics")
    assert route is not None
    assert route.description  # 必有 description


def test_metrics_endpoint_handler_returns_json():
    """/api/metrics handler 返正确 JSON 结构"""
    from observability import get_metrics_collector, reset_metrics_collector
    reset_metrics_collector()
    m = get_metrics_collector()
    m.record(provider="openai", model="gpt-4", latency_ms=100.0, success=True, total_tokens=50)
    m.record(provider="openai", model="gpt-4", latency_ms=300.0, success=False, error="timeout")

    # 直接调 handler 测逻辑(handler 需要 send_json 方法)
    class FakeHandler:
        def __init__(self):
            self.captured = None
            self.status = None
        def send_json(self, data, status=200):
            self.captured = data
            self.status = status

    from server.routers.system import register_system_routes
    from server.router import RouterRegistry
    reg = RouterRegistry()
    register_system_routes(reg)
    route = reg.find("GET", "/api/metrics")
    h = FakeHandler()
    route.handler(h)
    assert h.status == 200
    assert h.captured["ok"] is True
    assert "metrics" in h.captured
    metrics = h.captured["metrics"]
    assert metrics["total_calls"] == 2
    assert metrics["failed_calls"] == 1
    assert metrics["total_tokens"] == 50
    assert "openai" in metrics["by_provider"]


# ========== 7. end-to-end: config 集成 ==========

def test_observability_config_in_settings():
    """Settings.observability 字段可达"""
    from config import get_settings
    s = get_settings()
    assert hasattr(s, "observability")
    assert s.observability.log_level in ("DEBUG", "INFO", "WARNING", "ERROR")
    assert s.observability.metrics_history_size > 0
