"""
可选 OpenTelemetry 导出(P17)

默认关闭;设 OTEL_EXPORTER_OTLP_ENDPOINT(如 http://localhost:4318)且未设
OTEL_SDK_DISABLED=true 时,init_otel() 初始化 tracer + meter,把:
  - 每个 HTTP 请求 + 每次 LLM 调用 各生成一个 span(带 model/provider/latency/tokens/user_id)
  - LLM 调用延迟直方图 + 调用计数

依赖 opentelemetry-api / sdk / exporter-otlp(可选,未安装则优雅降级为 no-op)。
不阻塞主路径:任何异常都静默吞掉,只记录 warning。

启用步骤:
  pip install -r requirements-otel.txt
  export OTEL_EXPORTER_OTLP_ENDPOINT=http://<jaeger|tempo|datadog>:4318
  export OTEL_SERVICE_NAME=green-agent
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

_log = logging.getLogger("observability.otel")

_init_done = False
_tracer = None
_meter = None
_llm_hist = None
_llm_counter = None


def is_enabled() -> bool:
    """是否启用 OTel:有 endpoint 且未显式禁用"""
    if os.environ.get("OTEL_SDK_DISABLED", "").strip().lower() in ("1", "true", "yes", "on"):
        return False
    return bool(os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip())


def init_otel(service_name: Optional[str] = None) -> bool:
    """初始化 OTel(幂等)。返回是否成功启用。"""
    global _init_done, _tracer, _meter, _llm_hist, _llm_counter
    if _init_done:
        return _tracer is not None
    _init_done = True
    if not is_enabled():
        return False
    try:
        from opentelemetry import trace, metrics
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

        name = service_name or os.environ.get("OTEL_SERVICE_NAME", "green-agent")
        resource = Resource.create({"service.name": name})

        # Trace
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer(name)

        # Metrics
        reader = PeriodicExportingMetricReader(OTLPMetricExporter())
        metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[reader]))
        _meter = metrics.get_meter(name)
        _llm_hist = _meter.create_histogram("llm.latency_ms", "ms", "LLM 调用延迟")
        _llm_counter = _meter.create_counter("llm.calls", "1", "LLM 调用次数")

        _log.info("[otel] 已启用,service=%s endpoint=%s",
                  name, os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"))
        return True
    except Exception as e:
        _log.warning("[otel] 初始化失败(降级 no-op): %s", e)
        _tracer = None
        return False


def record_llm_call(
    model: str = "",
    provider: str = "",
    latency_ms: float = 0.0,
    usage: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
    user_id: Optional[str] = None,
) -> None:
    """记录一次 LLM 调用(span + metrics)。未启用/失败时静默。"""
    if _tracer is None and not _init_done:
        init_otel()
    if _tracer is None:
        return
    usage = usage or {}
    try:
        attrs = {
            "gen_ai.model": model or "unknown",
            "gen_ai.provider": provider or "unknown",
            "llm.latency_ms": latency_ms,
            "llm.prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
            "llm.completion_tokens": int(usage.get("completion_tokens", 0) or 0),
            "llm.error": bool(error),
        }
        if user_id:
            attrs["llm.user_id"] = str(user_id)
        with _tracer.start_as_current_span("llm.call", attributes=attrs) as span:
            if error:
                span.set_status(2, str(error)[:200])  # ERROR
        if _llm_hist is not None:
            _llm_hist.record(latency_ms, attrs)
        if _llm_counter is not None:
            _llm_counter.add(1, attrs)
    except Exception as e:
        _log.warning("[otel] record_llm_call 失败: %s", e)


def record_request(
    method: str = "",
    path: str = "",
    status: int = 0,
    user_id: Optional[str] = None,
) -> None:
    """记录一次 HTTP 请求 span。未启用/失败时静默。"""
    if _tracer is None and not _init_done:
        init_otel()
    if _tracer is None:
        return
    try:
        attrs = {"http.method": method, "http.path": path, "http.status": status or 0}
        if user_id:
            attrs["llm.user_id"] = str(user_id)
        with _tracer.start_as_current_span("http.request", attributes=attrs):
            pass
    except Exception as e:
        _log.warning("[otel] record_request 失败: %s", e)


__all__ = ["is_enabled", "init_otel", "record_llm_call", "record_request"]
