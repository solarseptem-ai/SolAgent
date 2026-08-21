"""重试策略模块。

为 LLM 调用提供指数退避重试机制，支持熔断器集成、按异常类型定制重试预算、
流式请求断点重试，以及从异常中解析 Retry-After 头进行智能等待。
"""
from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any, TypeVar

import httpx

from solagent.errors.llm import LLMError, RateLimitError, TokenLimitError
from solagent.llms.retry.circuit_breaker import CircuitBreaker, CircuitBreakerError

_logger = logging.getLogger(__name__)

T = TypeVar("T")

# 可重试的 HTTP 状态码集合
_RETRYABLE_STATUS_CODES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})

# 临时性错误关键词（中英文）
_TRANSIENT_ERROR_MARKERS = (
    "429", "rate limit", "500", "502", "503", "504",
    "overloaded", "timeout", "timed out", "connection",
    "server error", "temporarily unavailable",
    "负载较高", "服务繁忙", "稍后重试", "请稍后重试",
)

# 不可重试的错误关键词（认证、配额、欠费等）
_NON_RETRYABLE_MARKERS = (
    "insufficient_quota", "quota_exceeded", "quota_exhausted",
    "billing_hard_limit_reached", "insufficient_balance",
    "credit_balance_too_low", "billing_not_active", "payment_required",
    "authentication", "unauthorized", "invalid api key", "invalid_api_key",
    "permission", "forbidden", "access denied",
    "余额不足", "超出限额", "额度不足", "欠费", "无权", "未授权",
)

# 按异常类名覆盖的重试预算表
_PER_EXCEPTION_BUDGET: dict[str, int] = {}


def set_exception_budget(exception_class_name: str, max_attempts: int) -> None:
    """为指定异常类名设置重试预算上限。

    适用于那些重试代价很高的场景（例如流式 chunk 超时已经等待了 120-240 秒后才暴露），
    max_attempts 为绝对最大尝试次数（1 表示不重试）。
    """
    _PER_EXCEPTION_BUDGET[exception_class_name] = max(1, max_attempts)


def _extract_retry_after(exc: Exception) -> float | None:
    """从异常对象中解析 Retry-After 头值（秒），支持 OpenAI、Anthropic 和 httpx 的异常结构。"""
    headers = getattr(exc, "headers", None) or getattr(
        getattr(exc, "response", None), "headers", None
    )
    if headers:
        raw = (
            headers.get("retry-after-ms")
            or headers.get("Retry-After-Ms")
            or headers.get("retry-after")
            or headers.get("Retry-After")
        )
        if raw:
            try:
                return float(raw)
            except (TypeError, ValueError):
                pass
    ra = getattr(exc, "retry_after", None)
    if isinstance(ra, (int, float)):
        return float(ra)
    return None


def _is_retryable(exc: Exception) -> bool:
    """判断异常是否应触发重试。

    对已知临时性错误返回 True；对明确的不可重试错误（认证、配额、欠费）返回 False；
    未知异常默认视为可重试，以优先保障可用性。
    """
    status = getattr(exc, "status_code", None)
    if status is not None and status in _RETRYABLE_STATUS_CODES:
        return True
    detail = str(exc).lower()
    if any(marker in detail for marker in _NON_RETRYABLE_MARKERS):
        return False
    return True


class RetryPolicy:
    """重试策略，支持指数退避、抖动、熔断器和按异常定制预算。

    属性:
        max_retries: 最大重试次数。
        base_delay: 首次重试的基础延迟（秒）。
        max_delay: 延迟上限（秒）。
        jitter: 是否启用随机抖动。
        breaker: 可选的熔断器实例。
    """

    RETRYABLE_EXCEPTIONS = (
        LLMError,
        RateLimitError,
        TokenLimitError,
        httpx.HTTPError,
        httpx.TimeoutException,
        asyncio.TimeoutError,
        ConnectionError,
    )

    def __init__(self, max_retries: int = 3, base_delay: float = 1.0, max_delay: float = 60.0,
                 jitter: bool = True, breaker: CircuitBreaker | None = None) -> None:
        self.max_retries = max(0, max_retries)
        self.base_delay = max(0.1, base_delay)
        self.max_delay = max(0.1, max_delay)
        self.jitter = jitter
        self.breaker = breaker

    def delay(self, attempt: int) -> float:
        """根据尝试次数计算指数退避延迟，若启用 jitter 则加入随机因子。"""
        d = min(self.base_delay * (2 ** max(0, attempt)), self.max_delay)
        if self.jitter:
            d *= 0.5 + random.random()
        return d

    def _max_attempts_for(self, exc: Exception) -> int:
        """获取针对该异常的有效最大尝试次数，支持按异常类名覆盖。"""
        override = _PER_EXCEPTION_BUDGET.get(type(exc).__name__)
        if override is not None:
            return min(override, self.max_retries + 1)
        return self.max_retries + 1

    async def execute(
        self, fn: Callable[[], Awaitable[T]],
        on_retry: Callable[[int, Exception, float], Awaitable[None]] | None = None,
    ) -> T:
        """执行异步函数并在失败时按策略重试，支持熔断器保护。"""
        if self.breaker and not self.breaker.can_execute():
            raise CircuitBreakerError("Circuit breaker is open")
        last_error: Exception | None = None
        attempts = max(1, self.max_retries + 1)
        for attempt in range(attempts):
            try:
                result = await fn()
                if self.breaker:
                    self.breaker.record_success()
                return result
            except asyncio.CancelledError:
                if self.breaker:
                    self.breaker.clear_probe()
                raise
            except self.RETRYABLE_EXCEPTIONS as e:
                last_error = e
                if self.breaker:
                    self.breaker.record_failure()
                if not _is_retryable(e):
                    raise
                max_attempts = self._max_attempts_for(e)
                if attempt >= max_attempts - 1:
                    raise
                delay = self._compute_delay(attempt, e)
                if on_retry:
                    await on_retry(attempt + 1, e, delay)
                _logger.warning(
                    "LLM call failed (attempt %d/%d): %s. Retrying in %.1fs ...",
                    attempt + 1, max_attempts, e, delay,
                )
                await asyncio.sleep(delay)
        raise last_error  # type: ignore[misc]

    def _compute_delay(self, attempt: int, exc: Exception) -> float:
        """计算本次重试的等待时间：优先使用 Retry-After，否则使用指数退避。"""
        retry_after = _extract_retry_after(exc)
        if retry_after is not None and retry_after > 0:
            return min(retry_after, self.max_delay)
        return self.delay(attempt)

    async def execute_stream(
        self,
        fn: Callable[[], AsyncGenerator[T, None]],
    ) -> AsyncGenerator[T, None]:
        """执行流式异步生成器并在失败时整流重试，重试逻辑与 execute 一致。

        若流在输出若干 chunk 后中断，则从头重新请求并从新流 yield chunk。
        """
        if self.breaker and not self.breaker.can_execute():
            raise CircuitBreakerError("Circuit breaker is open")
        attempts = max(1, self.max_retries + 1)
        for attempt in range(attempts):
            stream = fn()
            try:
                async for chunk in stream:
                    yield chunk
                if self.breaker:
                    self.breaker.record_success()
                return
            except asyncio.CancelledError:
                await stream.aclose()  # type: ignore[attr-defined]
                if self.breaker:
                    self.breaker.clear_probe()
                raise
            except self.RETRYABLE_EXCEPTIONS as e:
                await _safe_aclose(stream)
                if self.breaker:
                    self.breaker.record_failure()
                if not _is_retryable(e):
                    raise
                max_attempts = self._max_attempts_for(e)
                if attempt >= max_attempts - 1:
                    raise
                delay = self._compute_delay(attempt, e)
                _logger.warning(
                    "LLM stream failed (attempt %d/%d): %s. Retrying in %.1fs ...",
                    attempt + 1, max_attempts, e, delay,
                )
                await asyncio.sleep(delay)
            except Exception:
                await _safe_aclose(stream)
                raise
        raise RuntimeError("Stream retry exhausted — unreachable")


async def _safe_aclose(stream: Any) -> None:
    """安全关闭异步生成器，忽略关闭过程中的异常。"""
    try:
        await stream.aclose()
    except Exception as e:
        _logger.warning("Retry policy stream aclose failed: %s", e, exc_info=True)