"""LLM 调用追踪器模块。

记录每次 LLM 调用的模型、延迟、token 消耗和成功/失败状态，
支持注册 before/after 回调以对接 Langfuse、LangSmith 等外部可观测平台。
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from solagent.schema.llm import TokenUsage

_logger = logging.getLogger(__name__)


@dataclass
class LLMCallRecord:
    """单次 LLM 调用的追踪记录。

    属性:
        model: 使用的模型名称。
        request_id: 请求唯一标识。
        start_time: 调用开始时间（monotonic 时钟）。
        success: 调用是否成功。
        latency_ms: 调用延迟（毫秒）。
        input_tokens: 输入 token 数量。
        output_tokens: 输出 token 数量。
        error: 错误描述，成功时为空。
    """
    model: str = ""
    request_id: str = ""
    start_time: float = 0.0
    success: bool = True
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    error: str = ""

    def record_success(self, usage: TokenUsage) -> None:
        """标记本次调用成功，并记录 token 消耗和延迟。"""
        self.success = True
        self.latency_ms = int((time.monotonic() - self.start_time) * 1000)
        self.input_tokens = usage.input_tokens
        self.output_tokens = usage.output_tokens

    def record_error(self, error: str) -> None:
        """标记本次调用失败，并记录延迟和错误信息。"""
        self.success = False
        self.latency_ms = int((time.monotonic() - self.start_time) * 1000)
        self.error = error


class LLMTracer:
    """LLM 调用追踪器，支持内部记录与外部可观测钩子。

    属性:
        _records: 所有 LLMCallRecord 的列表。
        _before_callbacks: 每次调用前触发的回调列表。
        _after_callbacks: 每次调用后触发的回调列表。
    """

    def __init__(self):
        self._records: list[LLMCallRecord] = []
        self._before_callbacks: list[Callable[[dict], None]] = []
        self._after_callbacks: list[Callable[[dict], None]] = []

    def on_before_call(self, callback: Callable[[dict], None]) -> None:
        """注册一个在每次 LLM 调用前触发的回调。回调签名: callback(context: dict)。"""
        self._before_callbacks.append(callback)

    def on_after_call(self, callback: Callable[[dict], None]) -> None:
        """注册一个在每次 LLM 调用后触发的回调。回调签名: callback(context: dict)。"""
        self._after_callbacks.append(callback)

    def start_call(self, model: str, request_id: str = "") -> LLMCallRecord:
        """开始追踪一次 LLM 调用，触发 before 回调并返回初始化的记录对象。"""
        context = {"model": model, "request_id": request_id, "timestamp": time.time()}
        for cb in self._before_callbacks:
            try:
                cb(context)
            except Exception:
                _logger.warning("Tracing before-call callback failed", exc_info=True)
        return LLMCallRecord(model=model, request_id=request_id, start_time=time.monotonic())

    def record_success(self, record: LLMCallRecord, usage: TokenUsage) -> None:
        """记录调用成功，追加到记录列表并触发 after 回调。"""
        record.record_success(usage)
        self._records.append(record)
        context = {"model": record.model, "request_id": record.request_id, "duration_ms": record.latency_ms,
                   "input_tokens": record.input_tokens, "output_tokens": record.output_tokens, "success": True}
        for cb in self._after_callbacks:
            try:
                cb(context)
            except Exception:
                _logger.warning("Tracing after-call callback failed", exc_info=True)

    def record_error(self, record: LLMCallRecord, error: str) -> None:
        """记录调用失败，追加到记录列表并触发 after 回调。"""
        record.record_error(error)
        self._records.append(record)
        context = {"model": record.model, "request_id": record.request_id, "duration_ms": record.latency_ms, "success": False, "error": error}
        for cb in self._after_callbacks:
            try:
                cb(context)
            except Exception:
                _logger.warning("Tracing after-call error callback failed", exc_info=True)

    @property
    def total_calls(self) -> int:
        """总调用次数。"""
        return len(self._records)

    @property
    def total_tokens(self) -> TokenUsage:
        """累计输入/输出 token 总数。"""
        return TokenUsage(input_tokens=sum(r.input_tokens for r in self._records),
                          output_tokens=sum(r.output_tokens for r in self._records))

    @property
    def success_rate(self) -> float:
        """调用成功率（无记录时默认 1.0）。"""
        if not self._records:
            return 1.0
        return sum(1 for r in self._records if r.success) / len(self._records)

    @property
    def avg_latency_ms(self) -> float:
        """平均调用延迟（毫秒）。"""
        if not self._records:
            return 0.0
        return sum(r.latency_ms for r in self._records) / len(self._records)

    def get_records(self, limit: int = 100) -> list[LLMCallRecord]:
        """获取最近的 limit 条调用记录。"""
        return self._records[-limit:]

    def reset(self) -> None:
        """清空所有追踪记录。"""
        self._records.clear()