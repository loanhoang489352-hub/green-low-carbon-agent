"""
简单 IP 限流中间件(P5-I.B)

策略:固定时间窗 + 内存 deque
- 默认 60 req / 60s / IP
- 时间窗内计数超过阈值 → 429
- 不持久化(进程重启清空,避免磁盘 I/O 拖累主路径)
- 信任代理头 X-Forwarded-For(若有 nginx / 反代前置)
- 不在白名单内的内网 IP 仍受保护(白名单按需扩)

设计取舍:
- 选 deque 滑动窗而非令牌桶:实现简单、内存可控(每个 IP 上限 60 timestamps)
- 不用 Redis:单机部署,跨进程不是目标
- 失败安全:任何异常都不阻塞主路径
"""
from __future__ import annotations

import os
import threading
import time
from collections import deque
from typing import Dict, Optional, Tuple


_DEFAULT_WINDOW_SECONDS = 60
_DEFAULT_MAX_REQUESTS = 60


class RateLimiter:
    """IP-based 限流(滑动时间窗)"""

    def __init__(
        self,
        max_requests: int = _DEFAULT_MAX_REQUESTS,
        window_seconds: int = _DEFAULT_WINDOW_SECONDS,
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._buckets: Dict[str, deque] = {}
        self._lock = threading.Lock()
        # 周期清理:超过 1k 个不同 IP 时,清掉 5 分钟无活动 IP
        self._last_cleanup = time.time()

    def _client_ip(self, handler) -> str:
        """从 handler 提取客户端 IP(支持反代头)"""
        try:
            xff = handler.headers.get("X-Forwarded-For") if hasattr(handler, "headers") else None
            if xff:
                return xff.split(",")[0].strip()
            return handler.client_address[0] if handler.client_address else "unknown"
        except Exception:
            return "unknown"

    def check(self, handler) -> Tuple[bool, int]:
        """检查是否允许此次请求

        Returns:
            (allowed, retry_after_seconds)
            - allowed=True: 正常通过
            - allowed=False: 超限,retry_after_seconds 提示客户端等多久
        """
        ip = self._client_ip(handler)
        now = time.time()
        cutoff = now - self.window_seconds

        with self._lock:
            bucket = self._buckets.get(ip)
            if bucket is None:
                bucket = deque()
                self._buckets[ip] = bucket

            # 弹出过期的
            while bucket and bucket[0] < cutoff:
                bucket.popleft()

            if len(bucket) >= self.max_requests:
                # 最早的过期时间 = 多久后能再发
                oldest = bucket[0]
                retry_after = max(1, int(oldest + self.window_seconds - now) + 1)
                return False, retry_after

            bucket.append(now)

            # 周期清理(每 5 分钟一次,只在 bucket 数大时触发)
            if len(self._buckets) > 1000 and (now - self._last_cleanup) > 300:
                self._cleanup_locked(cutoff)
                self._last_cleanup = now

            return True, 0

    def _cleanup_locked(self, cutoff: float) -> None:
        """清掉过期的 IP bucket(持锁状态下调用)"""
        stale = []
        for ip, bucket in self._buckets.items():
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if not bucket:
                stale.append(ip)
        for ip in stale:
            del self._buckets[ip]

    def reset(self) -> None:
        """清空状态(测试用)"""
        with self._lock:
            self._buckets.clear()
            self._last_cleanup = time.time()


# 单例
_default_limiter: Optional[RateLimiter] = None
_limiter_lock = threading.Lock()


def get_rate_limiter() -> RateLimiter:
    """获取限流单例(环境变量配置)"""
    global _default_limiter
    if _default_limiter is None:
        with _limiter_lock:
            if _default_limiter is None:
                max_r = int(os.environ.get("RATE_LIMIT_MAX", _DEFAULT_MAX_REQUESTS))
                window = int(os.environ.get("RATE_LIMIT_WINDOW", _DEFAULT_WINDOW_SECONDS))
                _default_limiter = RateLimiter(max_r, window)
    return _default_limiter


def reset_rate_limiter() -> None:
    """重置单例(测试用)"""
    global _default_limiter
    with _limiter_lock:
        _default_limiter = None
