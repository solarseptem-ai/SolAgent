"""令牌桶限流器，用于平滑控制对 LLM API 的请求速率。

基于令牌桶算法：以恒定速率向桶中补充令牌，每次请求消耗一枚令牌；
当桶为空时，请求需等待或被拒绝。适用于避免触发上游服务的 429 限流。
"""
import asyncio
import logging
import time

_logger = logging.getLogger(__name__)


class RateLimiter:
    """异步令牌桶限流器。

    属性:
        max_requests: 桶的容量（即最大突发请求数）。
        per_seconds: 补充完整一桶令牌所需的时间（秒）。
        _tokens: 当前桶中剩余的令牌数量。
        _last_refill: 上次补充令牌的时间戳。
        _lock: 保护令牌状态与事件标志的异步锁。
        _event: 用于通知等待者令牌已可用的异步事件。
    """

    def __init__(self, max_requests: int = 60, per_seconds: float = 60.0):
        self.max_requests = max_requests
        self.per_seconds = per_seconds
        self._tokens = float(max_requests)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()
        self._event = asyncio.Event()
        self._event.set()

    def _refill(self) -> None:
        """根据距上次补充的时间差，按比例增加桶内令牌数量。"""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(
            float(self.max_requests),
            self._tokens + elapsed * (self.max_requests / self.per_seconds),
        )
        self._last_refill = now

    async def acquire(self, timeout: float | None = None) -> float:
        """从桶中获取一枚令牌；若桶为空则等待，直到有可用令牌或超时。

        参数:
            timeout: 最长等待时间（秒），None 表示无限等待。

        返回:
            成功获取令牌时的单调时间戳，可用于计算请求停顿时间。

        异常:
            TimeoutError: 当设置了 timeout 且在指定时间内未获得令牌时抛出。
        """
        deadline = time.monotonic() + timeout if timeout is not None else None
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= 1:
                    self._tokens -= 1
                    self._event.set()
                    return time.monotonic()
                # 令牌不足，清除事件标志，等待补充后再试
                self._event.clear()

            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"RateLimiter acquire timed out after {timeout}s"
                    )
                try:
                    await asyncio.wait_for(self._event.wait(), timeout=remaining)
                except TimeoutError:
                    raise TimeoutError(
                        f"RateLimiter acquire timed out after {timeout}s"
                    )
            else:
                await self._event.wait()
