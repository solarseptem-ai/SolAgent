"""全局速率限制器模块。

按模型维度管理并发数和 QPM（每分钟请求数），当某个模型收到 429 响应时，
统一暂停该模型下的所有调用者，避免重试风暴导致更严重的速率限制。
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field

_logger = logging.getLogger(__name__)

# 最大暂停时长（24 小时），超过此值视为账户级限制，不再重试
MAX_PAUSE_SECONDS = 86_400


@dataclass
class _ModelSlot:
    """单个模型的限流槽，维护信号量、暂停状态和 QPM 窗口。

    属性:
        max_concurrent: 最大并发请求数。
        max_qpm: 每分钟最大请求数（0 表示不限制）。
        default_pause_seconds: 收到 429 后的默认暂停时长。
        jitter_range: 随机抖动范围，用于打散重试时间。
    """

    max_concurrent: int = 10
    max_qpm: int = 0
    default_pause_seconds: float = 5.0
    jitter_range: float = 2.0

    _semaphore: asyncio.Semaphore | None = field(default=None, repr=False, compare=False)
    _pause_until: float = 0.0
    _pause_set_at: float = 0.0
    _qpm_window: list[float] = field(default_factory=list, repr=False, compare=False)
    _qpm_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, compare=False)

    def ensure_semaphore(self) -> None:
        """确保信号量已初始化。"""
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrent)

    async def acquire(self, timeout: float | None = None) -> float:
        """获取一个执行令牌，遵守暂停期和 QPM 限制，返回获取时间。"""
        self.ensure_semaphore()
        assert self._semaphore is not None
        now = time.monotonic()
        if self._pause_until > now:
            remaining = self._pause_until - now
            if remaining > MAX_PAUSE_SECONDS:
                raise TimeoutError(
                    f"Global rate limiter: pause exceeds {MAX_PAUSE_SECONDS}s, "
                    f"likely a billing/account limit — not retrying"
                )
            jitter = random.uniform(0, self.jitter_range)
            await asyncio.sleep(remaining + jitter)
        if self.max_qpm > 0:
            await self._qpm_wait()
        if timeout is not None:
            await asyncio.wait_for(
                self._semaphore.acquire(), timeout=timeout
            )
        else:
            await self._semaphore.acquire()
        return time.monotonic()

    def release(self) -> None:
        """释放一个执行令牌。"""
        if self._semaphore is not None:
            self._semaphore.release()

    async def report_rate_limit(self, retry_after: float | None) -> None:
        """报告收到 429 响应，设置该模型下的全局暂停期。"""
        now = time.monotonic()
        pause_duration = (
            min(retry_after, MAX_PAUSE_SECONDS)
            if retry_after is not None
            else self.default_pause_seconds
        )
        if pause_duration >= MAX_PAUSE_SECONDS and retry_after is not None:
            return
        self._pause_until = now + pause_duration
        self._pause_set_at = now
        _logger.warning(
            "Global rate limiter: pausing all callers for %.1fs (429 received)",
            pause_duration,
        )

    async def on_success(self, acquired_at: float) -> None:
        """调用成功后清除过期的暂停状态。"""
        if self._pause_set_at > 0 and self._pause_set_at <= acquired_at:
            self._pause_until = 0.0
            self._pause_set_at = 0.0
            _logger.debug("Global rate limiter: cleared stale pause")

    async def _qpm_wait(self) -> None:
        """等待直到当前滑动窗口内的请求数低于 max_qpm。"""
        now = time.monotonic()
        async with self._qpm_lock:
            self._qpm_window = [t for t in self._qpm_window if t > now - 60.0]
            if len(self._qpm_window) >= self.max_qpm:
                wait_until = self._qpm_window[0] + 60.0
                await asyncio.sleep(max(0, wait_until - now))
                self._qpm_window = [t for t in self._qpm_window if t > time.monotonic() - 60.0]
            self._qpm_window.append(time.monotonic())


# 模块级模型槽字典和锁
_slots: dict[str, _ModelSlot] = {}
_slots_lock = asyncio.Lock()


async def get_global_limiter(
    limiter_key: str,
    max_concurrent: int = 10,
    max_qpm: int = 0,
    default_pause_seconds: float = 5.0,
    jitter_range: float = 2.0,
) -> _ModelSlot:
    """获取或创建指定模型的全局限流槽。"""
    async with _slots_lock:
        if limiter_key not in _slots:
            _slots[limiter_key] = _ModelSlot(
                max_concurrent=max_concurrent,
                max_qpm=max_qpm,
                default_pause_seconds=default_pause_seconds,
                jitter_range=jitter_range,
            )
        return _slots[limiter_key]