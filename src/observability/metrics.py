"""
LLM 调用指标收集 (P5-B)

设计:
- 单例 MetricsCollector,线程安全(RLock)
- 每次 LLM 调用后 record(provider, model, latency_ms, success, tokens, error)
- /api/metrics 端点消费聚合:总调用/错误率/P50/P95/token 用量/按 provider 分组
- 用 deque 保留最近 N=1000 条原始记录,够 P95 计算即可
"""
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


MAX_HISTORY = 1000  # 保留最近 1000 条


@dataclass
class CallRecord:
    provider: str
    model: str
    latency_ms: float
    success: bool
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="milliseconds"))


class MetricsCollector:
    """LLM 调用指标聚合器 (单例)"""

    def __init__(self, max_history: int = MAX_HISTORY):
        self._lock = threading.RLock()
        self._history: deque = deque(maxlen=max_history)

    def record(
        self,
        provider: str,
        model: str,
        latency_ms: float,
        success: bool,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        error: Optional[str] = None,
    ) -> None:
        """记录一次 LLM 调用"""
        with self._lock:
            self._history.append(CallRecord(
                provider=provider,
                model=model,
                latency_ms=latency_ms,
                success=success,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                error=error,
            ))

    def _percentile(self, values: List[float], p: float) -> float:
        """简单百分位(线性插值),values 必须已排序"""
        if not values:
            return 0.0
        if len(values) == 1:
            return values[0]
        k = (len(values) - 1) * p
        f = int(k)
        c = min(f + 1, len(values) - 1)
        if f == c:
            return values[f]
        return values[f] + (values[c] - values[f]) * (k - f)

    def summary(self) -> Dict:
        """聚合全局指标"""
        with self._lock:
            history = list(self._history)

        if not history:
            return {
                "total_calls": 0,
                "success_calls": 0,
                "failed_calls": 0,
                "error_rate": 0.0,
                "avg_latency_ms": 0.0,
                "p50_latency_ms": 0.0,
                "p95_latency_ms": 0.0,
                "p99_latency_ms": 0.0,
                "total_prompt_tokens": 0,
                "total_completion_tokens": 0,
                "total_tokens": 0,
                "by_provider": {},
            }

        total = len(history)
        success = sum(1 for r in history if r.success)
        failed = total - success

        latencies = sorted(r.latency_ms for r in history)
        avg_lat = sum(latencies) / total

        total_prompt = sum(r.prompt_tokens for r in history)
        total_completion = sum(r.completion_tokens for r in history)
        total_tokens = sum(r.total_tokens for r in history)

        # 按 provider 聚合
        by_provider: Dict[str, Dict] = {}
        for r in history:
            entry = by_provider.setdefault(r.provider, {
                "total_calls": 0,
                "success_calls": 0,
                "failed_calls": 0,
                "latencies": [],
                "total_tokens": 0,
            })
            entry["total_calls"] += 1
            if r.success:
                entry["success_calls"] += 1
            else:
                entry["failed_calls"] += 1
            entry["latencies"].append(r.latency_ms)
            entry["total_tokens"] += r.total_tokens

        for prov, entry in by_provider.items():
            lats = sorted(entry.pop("latencies"))
            entry["avg_latency_ms"] = round(sum(lats) / len(lats), 2) if lats else 0.0
            entry["p50_latency_ms"] = round(self._percentile(lats, 0.5), 2) if lats else 0.0
            entry["p95_latency_ms"] = round(self._percentile(lats, 0.95), 2) if lats else 0.0
            entry["error_rate"] = round(entry["failed_calls"] / entry["total_calls"], 4) if entry["total_calls"] else 0.0

        return {
            "total_calls": total,
            "success_calls": success,
            "failed_calls": failed,
            "error_rate": round(failed / total, 4) if total else 0.0,
            "avg_latency_ms": round(avg_lat, 2),
            "p50_latency_ms": round(self._percentile(latencies, 0.5), 2),
            "p95_latency_ms": round(self._percentile(latencies, 0.95), 2),
            "p99_latency_ms": round(self._percentile(latencies, 0.99), 2),
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "total_tokens": total_tokens,
            "by_provider": by_provider,
            "history_size": total,
        }

    def reset(self) -> None:
        """重置(测试用)"""
        with self._lock:
            self._history.clear()


# 单例
_collector: Optional[MetricsCollector] = None
_collector_lock = threading.Lock()


def get_metrics_collector() -> MetricsCollector:
    """获取全局 MetricsCollector (双检锁单例)"""
    global _collector
    if _collector is None:
        with _collector_lock:
            if _collector is None:
                _collector = MetricsCollector()
    return _collector


def reset_metrics_collector() -> None:
    """重置(仅供测试)"""
    global _collector
    _collector = None


__all__ = [
    "CallRecord",
    "MetricsCollector",
    "get_metrics_collector",
    "reset_metrics_collector",
]
