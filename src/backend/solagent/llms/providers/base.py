"""LLM 提供商抽象基类模块。

定义所有 LLM 提供商必须实现的通用接口，同时内置了重试策略、错误分类、
消息清洗、成本追踪和流式处理等共享能力，是各具体提供商实现的基础。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from abc import ABC, abstractmethod

_logger = logging.getLogger(__name__)
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, Any, Self

from solagent.llms.cost import CostTracker
from solagent.schema.llm import (
    GenerationSettings,
    LLMFinishReason,
    LLMRequest,
    LLMResponse,
    LLMStreamChunk,
    TokenUsage,
)
from solagent.schema.messages import ImageBlock, Message, MessageRole, TextBlock, ToolCallBlock, ToolResultBlock

if TYPE_CHECKING:
    from solagent.llms.providers.profile import ProviderProfile


class LLMProvider(ABC):
    """LLM 提供商抽象基类，内置重试、错误分类和消息清洗等通用能力。

    子类需实现 chat、chat_stream、count_tokens 等抽象方法，
    基类则提供安全调用包装、重试循环、消息格式修正等共享逻辑。
    """

    _CHAT_RETRY_DELAYS = (1, 2, 4)
    _PERSISTENT_MAX_DELAY = 60
    _PERSISTENT_IDENTICAL_ERROR_LIMIT = 10
    _RETRY_HEARTBEAT_CHUNK = 30

    _TRANSIENT_ERROR_MARKERS = (
        "429", "rate limit", "500", "502", "503", "504",
        "overloaded", "timeout", "timed out", "connection",
        "server error", "temporarily unavailable",
        "负载较高", "服务繁忙", "稍后重试", "请稍后重试",
    )
    _RETRYABLE_STATUS_CODES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
    _TRANSIENT_ERROR_KINDS = frozenset({"timeout", "connection"})
    _NON_RETRYABLE_429_ERROR_TOKENS = frozenset({
        "insufficient_quota", "quota_exceeded", "quota_exhausted",
        "billing_hard_limit_reached", "insufficient_balance",
        "credit_balance_too_low", "billing_not_active", "payment_required",
    })
    _RETRYABLE_429_ERROR_TOKENS = frozenset({
        "rate_limit_exceeded", "rate_limit_error", "too_many_requests",
        "request_limit_exceeded", "requests_limit_exceeded", "overloaded_error",
    })
    _NON_RETRYABLE_429_TEXT_MARKERS = (
        "insufficient_quota", "insufficient quota", "quota exceeded",
        "quota exhausted", "billing hard limit", "billing_hard_limit_reached",
        "billing not active", "insufficient balance", "insufficient_balance",
        "credit balance too low", "payment required", "out of credits",
        "out of quota", "exceeded your current quota",
    )
    _RETRYABLE_429_TEXT_MARKERS = (
        "rate limit", "rate_limit", "too many requests",
        "retry after", "try again in", "temporarily unavailable",
        "overloaded", "concurrency limit",
    )

    def __init__(self, api_key: str | None = None, base_url: str | None = None,
                 cost_tracker: CostTracker | None = None) -> None:
        """初始化提供商基类，配置 API 密钥、重试策略和成本追踪器。"""
        self.api_key = api_key
        self.base_url = base_url
        self._cost_tracker = cost_tracker or CostTracker()
        self.generation = GenerationSettings()
        self._current_model: str | None = None

    @abstractmethod
    async def chat(self, request: LLMRequest) -> LLMResponse:
        """子类必须实现：发送非流式对话请求并返回完整响应。"""
        ...

    @abstractmethod
    async def chat_stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        """子类必须实现：发送流式对话请求并逐块 yield 结果。"""
        ...

    @abstractmethod
    def count_tokens(self, text: str, model: str = "") -> int:
        """子类必须实现：估算指定文本在目标模型下的 token 数量。"""
        ...

    @property
    @abstractmethod
    def profile(self) -> ProviderProfile:
        """子类必须实现：返回该提供商的配置画像。"""
        ...

    @abstractmethod
    def get_default_model(self) -> str:
        """子类必须实现：返回默认使用的模型名称。"""
        ...

    @classmethod
    def _get_retryable_exceptions(cls) -> tuple[type[Exception], ...]:
        """返回当前提供商 SDK 中可重试的异常类型，子类可覆盖。"""
        return ()

    async def _safe_chat(self, request: LLMRequest) -> LLMResponse:
        """安全调用 chat 方法，捕获异常并包装为 ERROR 状态的 LLMResponse。"""
        try:
            return await self.chat(request)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _logger.warning("LLM provider chat failed: %s", exc, exc_info=True)
            return LLMResponse(
                content=f"Error calling LLM: {exc}",
                finish_reason=LLMFinishReason.ERROR,
            )

    async def _safe_chat_stream(self, request: LLMRequest, *,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
        on_thinking_delta: Callable[[str], Awaitable[None]] | None = None,
        on_tool_call_delta: Callable[[dict], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        """安全调用流式 chat，收集所有 chunk 并聚合为 LLMResponse，同时触发外部回调。"""
        try:
            content_parts = []
            finish_reason = LLMFinishReason.STOP
            async for chunk in self.chat_stream(request):
                if chunk.is_thinking and on_thinking_delta:
                    await on_thinking_delta(chunk.content)
                elif chunk.content:
                    content_parts.append(chunk.content)
                    if on_content_delta:
                        await on_content_delta(chunk.content)
                if chunk.tool_call_name and on_tool_call_delta:
                    await on_tool_call_delta({
                        "id": chunk.tool_call_id,
                        "name": chunk.tool_call_name,
                        "arguments": chunk.tool_call_arguments,
                    })
                if chunk.finish_reason:
                    finish_reason = chunk.finish_reason
            return LLMResponse(
                content="".join(content_parts),
                finish_reason=finish_reason,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _logger.warning("LLM provider stream failed: %s", exc, exc_info=True)
            return LLMResponse(
                content=f"Error calling LLM: {exc}",
                finish_reason=LLMFinishReason.ERROR,
            )

    @classmethod
    def _is_transient_error(cls, content: str | None) -> bool:
        """判断错误内容中是否包含临时性故障的关键词（如 rate limit、timeout 等）。"""
        err = (content or "").lower()
        return any(marker in err for marker in cls._TRANSIENT_ERROR_MARKERS)

    @classmethod
    def _is_transient_response(cls, response: LLMResponse) -> bool:
        """综合判断响应是否代表临时性错误，决定是否应触发重试。"""
        if response.error_should_retry is not None:
            return bool(response.error_should_retry)
        if response.error_status_code is not None:
            status = int(response.error_status_code)
            if status == 429:
                return cls._is_retryable_429_response(response)
            if status in cls._RETRYABLE_STATUS_CODES or status >= 500:
                return True
        kind = (response.error_kind or "").strip().lower()
        if kind in cls._TRANSIENT_ERROR_KINDS:
            return True
        return cls._is_transient_error(response.content)

    @classmethod
    def _is_retryable_429_response(cls, response: LLMResponse) -> bool:
        """针对 429 状态码的细粒度判断：区分配额耗尽（不可重试）与速率限制（可重试）。"""
        type_token = cls._normalize_error_token(response.error_type)
        code_token = cls._normalize_error_token(response.error_code)
        semantic_tokens = {token for token in (type_token, code_token) if token is not None}
        if any(token in cls._NON_RETRYABLE_429_ERROR_TOKENS for token in semantic_tokens):
            return False
        content = (response.content or "").lower()
        if any(marker in content for marker in cls._NON_RETRYABLE_429_TEXT_MARKERS):
            return False
        if any(token in cls._RETRYABLE_429_ERROR_TOKENS for token in semantic_tokens):
            return True
        if any(marker in content for marker in cls._RETRYABLE_429_TEXT_MARKERS):
            return True
        return True

    @classmethod
    def is_arrearage_response(cls, response: LLMResponse) -> bool:
        """判断响应是否因欠费/配额耗尽导致，用于上游业务做账户状态提示。"""
        if response.error_status_code is not None and int(response.error_status_code) == 402:
            return True
        type_token = cls._normalize_error_token(response.error_type)
        code_token = cls._normalize_error_token(response.error_code)
        if any(token in cls._NON_RETRYABLE_429_ERROR_TOKENS for token in (type_token, code_token) if token is not None):
            return True
        content = (response.content or "").lower()
        return any(marker in content for marker in cls._NON_RETRYABLE_429_TEXT_MARKERS)

    @classmethod
    def _extract_error_type_code(cls, payload: Any) -> tuple[str | None, str | None]:
        data = None
        if isinstance(payload, dict):
            data = payload
        elif isinstance(payload, str):
            try:
                data = json.loads(payload)
            except Exception:
                _logger.warning("LLM error payload JSON parse failed", exc_info=True)
        if not isinstance(data, dict):
            return None, None
        error_obj = data.get("error")
        type_value = data.get("type")
        code_value = data.get("code")
        if isinstance(error_obj, dict):
            type_value = error_obj.get("type") or type_value
            code_value = error_obj.get("code") or code_value
        return cls._normalize_error_token(type_value), cls._normalize_error_token(code_value)

    @staticmethod
    def _normalize_error_token(value: Any) -> str | None:
        if value is None:
            return None
        token = str(value).strip().lower()
        return token or None

    @classmethod
    def _extract_retry_after(cls, content: str | None) -> float | None:
        """从错误文本中提取建议的重试等待时间（秒）。"""
        text = (content or "").lower()
        patterns = (
            (r"retry after\s+(\d+(?:\.\d+)?)\s*(ms|milliseconds|s|sec|secs|seconds|m|min|minutes)?", 0),
            (r"try again in\s+(\d+(?:\.\d+)?)\s*(ms|milliseconds|s|sec|secs|seconds|m|min|minutes)", 1),
            (r"wait\s+(\d+(?:\.\d+)?)\s*(ms|milliseconds|s|sec|secs|seconds|m|min|minutes)\s*before retry", 2),
            (r"retry[_-]?after[\"'\s:=]+(\d+(?:\.\d+)?)", 3),
        )
        for pattern, idx in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            value = float(match.group(1))
            unit = match.group(2) if idx < 3 and match.lastindex and match.lastindex >= 2 else "s"
            return cls._to_retry_seconds(value, unit)
        return None

    @classmethod
    def _extract_retry_after_from_headers(cls, headers: Any) -> float | None:
        """从 HTTP 响应头中提取 Retry-After 值并转为秒。"""
        if not headers:
            return None
        get = getattr(headers, "get", lambda k, d=None: None)
        with suppress(TypeError, ValueError):
            retry_ms = get("retry-after-ms", None) or get("Retry-After-Ms", None)
            if retry_ms is not None:
                value = float(retry_ms) / 1000.0
                if value > 0:
                    return value
        retry_after = get("retry-after", None) or get("Retry-After", None)
        if retry_after is None:
            return None
        text = str(retry_after).strip()
        if not text:
            return None
        if re.fullmatch(r"\d+(?:\.\d+)?", text):
            return cls._to_retry_seconds(float(text), "s")
        try:
            retry_at = parsedate_to_datetime(text)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=UTC)
            remaining = (retry_at - datetime.now(retry_at.tzinfo)).total_seconds()
            return max(0.1, remaining)
        except Exception:
            _logger.warning("Failed to parse retry-after from headers", exc_info=True)
            return None

    @classmethod
    def _extract_retry_after_from_response(cls, response: LLMResponse) -> float | None:
        """综合从响应对象、响应头和内容中提取重试等待时间。"""
        if response.error_retry_after_s is not None and response.error_retry_after_s > 0:
            return response.error_retry_after_s
        if response.retry_after is not None and response.retry_after > 0:
            return response.retry_after
        return cls._extract_retry_after(response.content)

    @classmethod
    def _to_retry_seconds(cls, value: float, unit: str | None = None) -> float:
        unit = (unit or "s").lower()
        if unit in {"ms", "milliseconds"}:
            return max(0.1, value / 1000.0)
        if unit in {"m", "min", "minutes"}:
            return max(0.1, value * 60.0)
        return max(0.1, value)

    @staticmethod
    def _sanitize_empty_content(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """清洗消息列表中的空 content 字段，避免某些提供商拒绝空字符串。"""
        result: list[dict[str, Any]] = []
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, str) and not content:
                clean = dict(msg)
                clean["content"] = None if (msg.get("role") == "assistant" and msg.get("tool_calls")) else "(empty)"
                result.append(clean)
                continue
            if isinstance(content, list):
                new_items: list[Any] = []
                changed = False
                for item in content:
                    if isinstance(item, dict) and item.get("type") in ("text", "input_text", "output_text") and not item.get("text"):
                        changed = True
                        continue
                    if isinstance(item, dict) and "_meta" in item:
                        new_items.append({k: v for k, v in item.items() if k != "_meta"})
                        changed = True
                    else:
                        new_items.append(item)
                if changed:
                    clean = dict(msg)
                    if new_items:
                        clean["content"] = new_items
                    elif msg.get("role") == "assistant" and msg.get("tool_calls"):
                        clean["content"] = None
                    else:
                        clean["content"] = "(empty)"
                    result.append(clean)
                    continue
            result.append(msg)
        return result

    @staticmethod
    def _enforce_role_alternation(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """强制消息列表满足 user/assistant 交替规则，合并连续同角色消息并修正边界情况。"""
        if not messages:
            return messages
        merged: list[dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role")
            if (merged and role != "system" and role not in ("tool",)
                and merged[-1].get("role") == role and role in ("user", "assistant")):
                prev = merged[-1]
                if role == "assistant":
                    prev_has_tools = bool(prev.get("tool_calls"))
                    curr_has_tools = bool(msg.get("tool_calls"))
                    if curr_has_tools:
                        merged[-1] = dict(msg)
                        continue
                    if prev_has_tools:
                        continue
                prev_content = prev.get("content") or ""
                curr_content = msg.get("content") or ""
                if isinstance(prev_content, str) and isinstance(curr_content, str):
                    prev["content"] = (prev_content + "\n\n" + curr_content).strip()
                else:
                    merged[-1] = dict(msg)
            else:
                merged.append(dict(msg))
        last_popped = None
        while merged and merged[-1].get("role") == "assistant":
            last_popped = merged.pop()
        if (merged and last_popped is not None
            and not any(m.get("role") in ("user", "tool") for m in merged)):
            recovered = dict(last_popped)
            recovered["role"] = "user"
            merged.append(recovered)
        for i, msg in enumerate(merged):
            if msg.get("role") != "system":
                if msg.get("role") == "assistant" and not msg.get("tool_calls"):
                    merged.insert(i, {"role": "user", "content": "(conversation continued)"})
                break
        return merged

    async def _sleep_with_heartbeat(
        self, delay: float, *, attempt: int, persistent: bool,
        on_retry_wait: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        """带心跳通知的异步等待，在长时间重试期间定期触发 on_retry_wait 回调。"""
        remaining = max(0.0, delay)
        while remaining > 0:
            if on_retry_wait:
                kind = "persistent retry" if persistent else "retry"
                await on_retry_wait(
                    f"Model request failed, {kind} in {max(1, int(round(remaining)))}s "
                    f"(attempt {attempt})."
                )
            chunk = min(remaining, self._RETRY_HEARTBEAT_CHUNK)
            await asyncio.sleep(chunk)
            remaining -= chunk

    async def _run_with_retry(
        self,
        call: Callable[..., Awaitable[LLMResponse]],
        kw: dict[str, Any],
        original_messages: list[Message],
        *,
        retry_mode: str = "standard",
        on_retry_wait: Callable[[str], Awaitable[None]] | None = None,
        should_retry_guard: Callable[[], bool] | None = None,
        on_stream_recover: Callable[[], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        """通用重试执行器，支持标准重试和持久重试两种模式，自动识别临时性错误并退避。"""
        attempt = 0
        delays = list(self._CHAT_RETRY_DELAYS)
        persistent = retry_mode == "persistent"
        last_response: LLMResponse | None = None
        last_error_key: str | None = None
        identical_error_count = 0
        while True:
            attempt += 1
            response = await call(**kw)
            if response.finish_reason != LLMFinishReason.ERROR:
                return response
            last_response = response
            if should_retry_guard is not None and not should_retry_guard():
                is_timeout = (response.error_kind or "").lower() == "timeout"
                if is_timeout:
                    if on_stream_recover:
                        await on_stream_recover()
                    else:
                        kw["on_content_delta"] = None
                        kw["on_thinking_delta"] = None
                        kw["on_tool_call_delta"] = None
                        should_retry_guard = None
                else:
                    return response
            error_key = (response.content or "").strip().lower() or None
            if error_key and error_key == last_error_key:
                identical_error_count += 1
            else:
                last_error_key = error_key
                identical_error_count = 1 if error_key else 0
            if not self._is_transient_response(response):
                return response
            if persistent and identical_error_count >= self._PERSISTENT_IDENTICAL_ERROR_LIMIT:
                return response
            if not persistent and attempt > len(delays):
                break
            base_delay = delays[min(attempt - 1, len(delays) - 1)]
            delay = self._extract_retry_after_from_response(response) or base_delay
            if persistent:
                delay = min(delay, self._PERSISTENT_MAX_DELAY)
            await self._sleep_with_heartbeat(delay, attempt=attempt, persistent=persistent, on_retry_wait=on_retry_wait)
        return last_response if last_response is not None else await call(**kw)

    async def chat_with_retry(
        self, request: LLMRequest,
        retry_mode: str = "standard",
        on_retry_wait: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        """带重试机制的非流式对话调用入口。"""
        return await self._run_with_retry(
            self._safe_chat, {"request": request}, request.messages,
            retry_mode=retry_mode, on_retry_wait=on_retry_wait,
        )

    async def chat_stream_with_retry(
        self, request: LLMRequest,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
        on_thinking_delta: Callable[[str], Awaitable[None]] | None = None,
        on_tool_call_delta: Callable[[dict], Awaitable[None]] | None = None,
        on_stream_recover: Callable[[], Awaitable[None]] | None = None,
        retry_mode: str = "standard",
        on_retry_wait: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        """带重试机制的流式对话调用入口，支持内容增量、思考增量和工具调用增量回调。"""
        has_streamed_content = False

        async def _tracking_delta(text: str) -> None:
            nonlocal has_streamed_content
            if text:
                has_streamed_content = True
            if on_content_delta:
                await on_content_delta(text)

        async def _recover_stream() -> None:
            nonlocal has_streamed_content
            if on_stream_recover:
                await on_stream_recover()
            has_streamed_content = False

        return await self._run_with_retry(
            self._safe_chat_stream,
            {
                "request": request,
                "on_content_delta": _tracking_delta if on_content_delta else None,
                "on_thinking_delta": on_thinking_delta,
                "on_tool_call_delta": on_tool_call_delta,
            },
            request.messages,
            retry_mode=retry_mode,
            on_retry_wait=on_retry_wait,
            should_retry_guard=lambda: not has_streamed_content,
            on_stream_recover=_recover_stream if on_stream_recover else None,
        )

    async def aask(
        self, msg: str,
        system_msgs: list[str] | None = None,
        stream: bool = False,
    ) -> str:
        """简易单轮对话接口：自动构造 system + user 消息并返回文本回复。"""
        messages = []
        if system_msgs:
            for sm in system_msgs:
                messages.append(Message.system(sm))
        else:
            messages.append(Message.system("You are a helpful assistant."))
        messages.append(Message.user(msg))
        request = LLMRequest(messages=messages, model=self.get_default_model())
        response = await self.chat_with_retry(request)
        return response.content

    async def aask_batch(self, msgs: list[str]) -> str:
        """批量多轮对话接口：依次将每个消息加入上下文并获取回复，最后汇总所有 assistant 回复。"""
        messages = [Message.system("You are a helpful assistant.")]
        for msg in msgs:
            messages.append(Message.user(msg))
            response = await self.chat_with_retry(
                LLMRequest(messages=list(messages), model=self.get_default_model())
            )
            messages.append(Message.assistant(response.content))
        return "\n".join(
            "".join(b.text for b in m.content if isinstance(b, TextBlock))
            for m in messages if m.role == MessageRole.ASSISTANT
        )

    def format_msg(self, messages: Any) -> list[dict]:
        """将多种类型的输入（字符串、Message、字典、列表）统一转换为 OpenAI 格式的消息字典列表。"""
        from solagent.llms.format.converter import FormatConverter
        if isinstance(messages, str):
            return [{"role": "user", "content": messages}]
        if isinstance(messages, Message):
            return FormatConverter.to_openai_messages([messages])
        if isinstance(messages, dict):
            return [messages]
        if isinstance(messages, list):
            if all(isinstance(m, dict) for m in messages):
                return messages
            if all(isinstance(m, Message) for m in messages):
                return FormatConverter.to_openai_messages(messages)
        raise ValueError(f"Unsupported message type: {type(messages)}")

    def with_model(self, model: str) -> Self:
        """设置当前会话使用的模型并返回 self，支持链式调用。"""
        self._current_model = model
        return self

    def _update_costs(self, usage: TokenUsage, model: str | None = None) -> None:
        """将本次调用的 token 消耗记录到成本追踪器中。"""
        self._cost_tracker.record(model or self.get_default_model(), usage)

    def get_costs(self) -> CostTracker:
        """返回当前累计的成本追踪器实例。"""
        return self._cost_tracker

    def count_tokens_full(self, messages: list[Message], tools: list[dict] | None = None) -> int:
        """估算完整请求（含消息、图片、工具声明）的大致 token 数量。

        图片按每张 2000 token 估算，文本按 UTF-8 字节数除以 4 估算。
        """
        cnt = 0
        data_blocks = 0
        acc_texts = []
        for msg in messages:
            for block in msg.content:
                if isinstance(block, TextBlock):
                    acc_texts.append(block.text)
                elif isinstance(block, ToolCallBlock):
                    acc_texts.append(json.dumps(block.arguments, ensure_ascii=False))
                elif isinstance(block, ToolResultBlock):
                    output = block.content
                    if isinstance(output, str):
                        acc_texts.append(output)
                elif isinstance(block, ImageBlock):
                    data_blocks += 1
        if tools:
            acc_texts.append(json.dumps(tools, ensure_ascii=False))
        cnt += data_blocks * 2000
        acc_text_str = "".join(acc_texts)
        cnt += int(len(acc_text_str.encode("utf-8")) / 4 + 0.5)
        return cnt

    def _validate_tool_choice(self, tool_choice: str | None, tools: list[dict] | None) -> None:
        """校验 tool_choice 参数是否合法：只能是 auto/none/required 或工具名称之一。"""
        if tool_choice is None or tools is None:
            return
        valid_modes = {"auto", "none", "required"}
        if tool_choice not in valid_modes:
            valid_names = [t.get("function", {}).get("name", "") for t in tools]
            if tool_choice not in valid_names:
                raise ValueError(
                    f"Invalid tool_choice '{tool_choice}'. "
                    f"Valid modes: {valid_modes}, available tools: {valid_names}"
                )