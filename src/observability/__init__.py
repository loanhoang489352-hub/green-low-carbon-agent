"""
可观测性模块 (P5-B)

提供:
- trace_id 生成与上下文传递(observability.trace)
- JSON 结构化日志(observability.logger)
- LLM 调用指标聚合(observability.metrics)
"""
from observability.trace import (
    new_trace_id,
    get_trace_id,
    set_trace_id,
    reset_trace_id,
    with_trace,
)
from observability.logger import JSONFormatter, setup_logging, get_logger
from observability.metrics import (
    MetricsCollector,
    CallRecord,
    get_metrics_collector,
    reset_metrics_collector,
)

__all__ = [
    # trace
    "new_trace_id", "get_trace_id", "set_trace_id", "reset_trace_id", "with_trace",
    # logger
    "JSONFormatter", "setup_logging", "get_logger",
    # metrics
    "MetricsCollector", "CallRecord", "get_metrics_collector", "reset_metrics_collector",
]
