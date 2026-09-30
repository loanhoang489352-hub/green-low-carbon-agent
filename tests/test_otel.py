"""P17: OpenTelemetry 导出(可选)单元测试"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def _reset(otel):
    otel._init_done = False
    otel._tracer = None
    otel._meter = None
    otel._llm_hist = None
    otel._llm_counter = None


def test_disabled_without_endpoint(monkeypatch):
    import observability.otel as otel

    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    _reset(otel)
    assert otel.is_enabled() is False
    assert otel.init_otel() is False


def test_disabled_by_env_flag(monkeypatch):
    import observability.otel as otel

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    _reset(otel)
    assert otel.is_enabled() is False


def test_record_llm_call_is_noop_when_disabled(monkeypatch):
    import observability.otel as otel

    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    _reset(otel)
    otel.init_otel()
    # 未启用时不抛异常,静默返回
    otel.record_llm_call(model="gpt-4o", provider="openai", latency_ms=123.4,
                         usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                         error=None, user_id="alice")
    otel.record_request(method="GET", path="/api/health", status=200, user_id="alice")


def test_metrics_record_does_not_break_without_otel(monkeypatch):
    """即使没装 opentelemetry,metrics.record() 也要正常(OTel 调用被吞)"""
    from observability.metrics import MetricsCollector

    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    import observability.otel as otel

    _reset(otel)
    c = MetricsCollector()
    c.record(provider="openai", model="gpt-4o", latency_ms=100.0, success=True,
             prompt_tokens=10, completion_tokens=5, total_tokens=15)
    s = c.summary()
    assert s["total_calls"] == 1
    assert s["total_tokens"] == 15


if __name__ == "__main__":
    import os
    os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
    os.environ.pop("OTEL_SDK_DISABLED", None)
    test_disabled_without_endpoint(None)
    test_record_llm_call_is_noop_when_disabled(None)
    print("✅ OTel tests PASSED")
