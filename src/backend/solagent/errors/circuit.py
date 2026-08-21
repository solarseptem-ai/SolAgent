"""三态熔断器，用于 LLM 错误处理和服务保护。

状态流转：
    closed（关闭）→ open（开启，失败阈值达到）
    → half_open（半开，恢复超时后）→ probe（探测）
        ├─ 探测成功 → closed
        └─ 探测失败 → open

熔断器在检测到连续失败达到阈值后打开，拒绝后续请求以保护下游服务；
经过 recovery_timeout 后进入半开状态，允许一个探测请求通过，根据结果决定关闭或重新打开。
"""
from __future__ import annotations

import asyncio
import logging
import time

_logger = logging.getLogger(__name__)


class CircuitBreaker:
    """三态熔断器，防止下游服务故障时持续发送请求导致雪崩。

    三种状态：
        - closed（关闭）：正常放行请求。
        - open（开启）：拒绝所有请求，等待恢复超时。
        - half_open（半开）：允许一个探测请求通过，测试服务是否恢复。
    """

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0):
        """
        Args:
            failure_threshold: 触发熔断的连续失败次数阈值。
            recovery_timeout: 熔断开启后到尝试恢复的时间间隔（秒）。
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._lock = asyncio.Lock()
        self._failure_count = 0       # 当前连续失败计数
        self._open_until: float = 0.0  # open 状态持续到该时间点
        self._state = "closed"        # 当前熔断器状态
        self._probe_in_flight = False  # half_open 状态下是否有探测请求在进行

    @property
    def state(self) -> str:
        """返回当前熔断器状态（closed/open/half_open）。"""
        return self._state

    async def allow_request(self) -> bool:
        """判断当前是否允许发送请求。

        Returns:
            True 表示允许请求通过；False 表示请求应被拒绝（熔断中）。
        """
        async with self._lock:
            now = time.monotonic()
            if self._state == "open":
                # 检查恢复超时是否已到
                if now < self._open_until:
                    return False
                self._state = "half_open"
                self._probe_in_flight = False
            if self._state == "half_open":
                # 半开状态下只允许一个探测请求
                if self._probe_in_flight:
                    return False
                self._probe_in_flight = True
                return True
            return True

    async def record_success(self) -> None:
        """记录一次成功响应，重置失败计数并关闭熔断器。"""
        async with self._lock:
            if self._state != "closed" or self._failure_count > 0:
                _logger.info("Circuit breaker reset (closed). LLM service recovered.")
            self._failure_count = 0
            self._open_until = 0.0
            self._state = "closed"
            self._probe_in_flight = False

    async def record_failure(self) -> None:
        """记录一次失败响应，更新失败计数并在达到阈值时开启熔断。"""
        async with self._lock:
            if self._state == "half_open":
                # 探测失败，重新打开熔断器
                self._open_until = time.monotonic() + self.recovery_timeout
                self._state = "open"
                self._probe_in_flight = False
                _logger.error(
                    "Circuit breaker probe failed (open). Will probe again after %ds.",
                    self.recovery_timeout,
                )
                return
            self._failure_count += 1
            if self._failure_count >= self.failure_threshold:
                self._open_until = time.monotonic() + self.recovery_timeout
                if self._state != "open":
                    self._state = "open"
                    self._probe_in_flight = False
                    _logger.error(
                        "Circuit breaker tripped (open). Threshold reached (%d). Will probe after %ds.",
                        self.failure_threshold,
                        self.recovery_timeout,
                    )

    async def reset(self) -> None:
        """手动重置熔断器到初始关闭状态。"""
        async with self._lock:
            self._failure_count = 0
            self._open_until = 0.0
            self._state = "closed"
            self._probe_in_flight = False