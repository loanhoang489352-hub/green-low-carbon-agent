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
    timestamp: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="milliseconds")
    )


class MetricsCollector:
    """LLM 调用指标聚合器 (单例) — P6.S.20 加 tool call + endpoint latency"""

    def __init__(self, max_history: int = MAX_HISTORY):
        self._lock = threading.RLock()
        self._history: deque = deque(maxlen=max_history)
        # P6.S.20: 工具调用计数 + 端点延迟
        self._tool_calls: Dict[str, int] = {}  # tool_name -> count
        self._endpoint_latencies: Dict[str, List[float]] = {}  # path -> recent ms
        self._intent_counts: Dict[str, int] = {}  # intent -> count
        self._active_users: set = set()  # 当前活跃 user_id

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
            self._history.append(
                CallRecord(
                    provider=provider,
                    model=model,
                    latency_ms=latency_ms,
                    success=success,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    error=error,
                )
            )

    def record_tool_call(self, tool_name: str) -> None:
        """P6.S.20: 记录 tool 调用"""
        with self._lock:
            self._tool_calls[tool_name] = self._tool_calls.get(tool_name, 0) + 1

    def record_endpoint_latency(self, path: str, latency_ms: float) -> None:
        """P6.S.20: 记录端点延迟(保留最近 100 个)"""
        with self._lock:
            arr = self._endpoint_latencies.setdefault(path, [])
            arr.append(latency_ms)
            if len(arr) > 100:
                del arr[0]

    def record_intent(self, intent: str) -> None:
        """P6.S.20: 记录意图分布"""
        with self._lock:
            self._intent_counts[intent] = self._intent_counts.get(intent, 0) + 1

    def record_user_activity(self, user_id: str) -> None:
        """P6.S.20: 记录活跃 user(无锁版,O(1))"""
        if user_id:
            self._active_users.add(user_id)

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
            # P6.S.20: 即使无 LLM 调用,也返 tool_calls / endpoint_latencies 等 P6.S.20 新字段
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
                "tool_calls": dict(self._tool_calls),
                "tool_calls_total": sum(self._tool_calls.values()),
                "endpoint_latencies": {
                    p: {
                        "count": len(arr),
                        "avg_ms": round(sum(arr) / len(arr), 2) if arr else 0,
                        "p95_ms": round(self._percentile(sorted(arr), 0.95), 2) if arr else 0,
                    }
                    for p, arr in self._endpoint_latencies.items()
                },
                "intent_counts": dict(self._intent_counts),
                "active_users_count": len(self._active_users),
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
            entry = by_provider.setdefault(
                r.provider,
                {
                    "total_calls": 0,
                    "success_calls": 0,
                    "failed_calls": 0,
                    "latencies": [],
                    "total_tokens": 0,
                },
            )
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
            entry["error_rate"] = (
                round(entry["failed_calls"] / entry["total_calls"], 4)
                if entry["total_calls"]
                else 0.0
            )

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
            # P6.S.20 新增:tool call / endpoint latency / intent 分布
            "tool_calls": dict(self._tool_calls),
            "tool_calls_total": sum(self._tool_calls.values()),
            "endpoint_latencies": {
                p: {
                    "count": len(arr),
                    "avg_ms": round(sum(arr) / len(arr), 2) if arr else 0,
                    "p95_ms": round(self._percentile(sorted(arr), 0.95), 2) if arr else 0,
                }
                for p, arr in self._endpoint_latencies.items()
            },
            "intent_counts": dict(self._intent_counts),
            "active_users_count": len(self._active_users),
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
