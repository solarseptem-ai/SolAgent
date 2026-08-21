"""熔断器模块。

实现经典的断路器模式，防止 LLM 服务故障时的级联失效：
当连续失败次数达到阈值后自动断开，经过恢复超时后进入半开状态探测，
成功后关闭，失败则重新打开。
"""
import logging
import time
from enum import Enum

_logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    """熔断器三种状态枚举。"""
    CLOSED = "closed"      # 关闭：正常通过请求
    OPEN = "open"          # 打开：拒绝请求，防止故障扩散
    HALF_OPEN = "half_open"  # 半开：允许单个探测请求通过


class CircuitBreakerError(Exception):
    """当熔断器处于 OPEN 状态且请求被阻止时抛出此异常。"""


class CircuitBreaker:
    """熔断器，用于在 LLM 服务异常时快速失败并避免雪崩效应。

    属性:
        failure_threshold: 触发熔断的连续失败次数阈值。
        recovery_timeout: 从 OPEN 到 HALF_OPEN 的恢复等待时间（秒）。
    """

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._probe_in_flight = False

    @property
    def state(self) -> CircuitState:
        """当前熔断器状态。"""
        return self._state

    def record_success(self) -> None:
        """记录一次成功调用，重置失败计数并关闭熔断器。"""
        if self._state != CircuitState.CLOSED or self._failure_count > 0:
            _logger.info("Circuit breaker reset (Closed). LLM service recovered.")
        self._failure_count = 0
        self._state = CircuitState.CLOSED
        self._probe_in_flight = False

    def record_failure(self) -> None:
        """记录一次失败调用，根据当前状态决定是否熔断或递增计数。"""
        if self._state == CircuitState.HALF_OPEN:
            # 探测失败：重新打开熔断器
            self._state = CircuitState.OPEN
            self._last_failure_time = time.time()
            self._probe_in_flight = False
            _logger.error(
                "Circuit breaker probe failed (Open). Will probe again after %ds.",
                self.recovery_timeout,
            )
            return
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            _logger.error(
                "Circuit breaker tripped (Open). Threshold reached (%d). Will probe after %ds.",
                self.failure_threshold,
                self.recovery_timeout,
            )

    def can_execute(self) -> bool:
        """判断当前是否允许执行请求，同时处理状态转换逻辑。"""
        if self._state == CircuitState.CLOSED:
            return True
        if self._state == CircuitState.OPEN:
            if time.time() - self._last_failure_time >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._probe_in_flight = False
                return self._check_half_open()
            return False
        if self._state == CircuitState.HALF_OPEN:
            return self._check_half_open()
        return True

    def _check_half_open(self) -> bool:
        """半开状态下只允许一个探测请求通过，防止大量请求同时涌入。"""
        if self._probe_in_flight:
            return False
        self._probe_in_flight = True
        return True

    def clear_probe(self) -> None:
        """当探测请求被取消时释放探测标志，避免阻塞后续探测。"""
        if self._state == CircuitState.HALF_OPEN:
            self._probe_in_flight = False
