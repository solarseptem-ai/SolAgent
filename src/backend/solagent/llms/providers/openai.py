"""OpenAI 提供商实现模块。

基于 OpenAI Python SDK 实现 LLMProvider 接口，支持标准对话、流式输出、
工具调用和连接健康检查，兼容 OpenAI 官方 API 及所有 OpenAI 兼容端点。
"""
from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator

_logger = logging.getLogger(__name__)

from solagent.agents.tools.validator import parse_and_repair_arguments
from solagent.core.token_counter import auto_counter
from solagent.llms.format.converter import FormatConverter
from solagent.llms.providers.base import LLMProvider
from solagent.llms.providers.profile import ProviderProfile
from solagent.schema.llm import LLMFinishReason, LLMRequest, LLMResponse, LLMStreamChunk, TokenUsage
from solagent.schema.tools import ToolCall


class OpenAIProvider(LLMProvider):
    """OpenAI 提供商实现，封装了与 OpenAI API 的交互逻辑。"""

    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.base_url = base_url or "https://api.openai.com/v1"
        self._client = None
        self._token_counter = auto_counter("gpt-4o")

    @property
    def profile(self) -> ProviderProfile:
        """返回 OpenAI 提供商的固定配置画像。"""
        return ProviderProfile(
            name="openai",
            display_name="OpenAI",
            api_mode="chat_completions",
            base_url=self.base_url,
            env_key="OPENAI_API_KEY",
            default_model="gpt-4o",
            models=["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo", "o1", "o3-mini"],
            supports_vision=True,
            supports_tools=True,
            supports_streaming=True,
            supports_thinking=True,
        )

    def _get_client(self):
        """延迟初始化并返回 AsyncOpenAI 客户端实例。"""
        if self._client is None:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url, max_retries=0)
        return self._client

    def _parse_finish_reason(self, raw: str) -> LLMFinishReason:
        """将 OpenAI 的 finish_reason 字符串映射为内部枚举值。"""
        mapping = {
            "stop": LLMFinishReason.STOP,
            "tool_calls": LLMFinishReason.TOOL_CALLS,
            "length": LLMFinishReason.LENGTH,
            "content_filter": LLMFinishReason.CONTENT_FILTER,
        }
        return mapping.get(raw, LLMFinishReason.STOP)

    async def chat(self, request: LLMRequest) -> LLMResponse:
        """发送非流式对话请求，返回完整的 LLMResponse。"""
        client = self._get_client()
        kwargs: dict = {
            "model": request.model,
            "messages": FormatConverter.to_openai_messages(request.messages),
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "top_p": request.top_p,
        }
        if request.tools:
            kwargs["tools"] = FormatConverter.tools_to_openai(request.tools)
        if request.stop:
            kwargs["stop"] = request.stop
        if request.extra_headers:
            kwargs["extra_headers"] = request.extra_headers

        response = await client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        finish = choice.finish_reason or "stop"
        finish_reason = self._parse_finish_reason(finish)

        content = choice.message.content or ""
        tool_calls: list[ToolCall] = []
        if choice.message.tool_calls:
            finish_reason = LLMFinishReason.TOOL_CALLS
            for tc in choice.message.tool_calls:
                raw_args = tc.function.arguments
                arguments = parse_and_repair_arguments(raw_args if isinstance(raw_args, str) else (raw_args if isinstance(raw_args, dict) else {}))
                tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=arguments))

        usage = TokenUsage(
            input_tokens=response.usage.prompt_tokens if response.usage else 0,
            output_tokens=response.usage.completion_tokens if response.usage else 0,
        )

        return LLMResponse(content=content, finish_reason=finish_reason, usage=usage, tool_calls=tool_calls, model=request.model)

    async def chat_stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        """发送流式对话请求，逐块 yield LLMStreamChunk。"""
        client = self._get_client()
        kwargs: dict = {
            "model": request.model,
            "messages": FormatConverter.to_openai_messages(request.messages),
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "top_p": request.top_p,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if request.tools:
            kwargs["tools"] = FormatConverter.tools_to_openai(request.tools)

        stream = await client.chat.completions.create(**kwargs)
        tool_calls_map: dict[int, dict[str, str]] = {}
        stream_usage: TokenUsage | None = None
        async for chunk in stream:
            if chunk.usage:
                stream_usage = TokenUsage(
                    input_tokens=chunk.usage.prompt_tokens or 0,
                    output_tokens=chunk.usage.completion_tokens or 0,
                )
            if not chunk.choices or not chunk.choices[0].delta:
                continue
            delta = chunk.choices[0].delta
            finish = chunk.choices[0].finish_reason or ""

            if delta.tool_calls:
                # 累加流式工具调用片段，按 index 分组管理
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index if tc_delta.index is not None else 0
                    if idx not in tool_calls_map:
                        tool_calls_map[idx] = {"id": "", "name": "", "arguments": ""}
                    entry = tool_calls_map[idx]
                    if tc_delta.id:
                        entry["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            entry["name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            entry["arguments"] += tc_delta.function.arguments
                    yield LLMStreamChunk(
                        content="",
                        tool_call_id=entry["id"],
                        tool_call_name=entry["name"],
                        tool_call_arguments=tc_delta.function.arguments or "",
                        index=idx,
                        usage=stream_usage if stream_usage else None,
                    )
            else:
                content = delta.content or ""
                reasoning = getattr(delta, "reasoning_content", None)
                if isinstance(reasoning, str) and reasoning:
                    yield LLMStreamChunk(
                        content="",
                        reasoning_content=reasoning,
                        index=chunk.choices[0].index,
                        usage=stream_usage if stream_usage else None,
                    )
                yield LLMStreamChunk(
                    content=content,
                    finish_reason=self._parse_finish_reason(finish) if finish else None,
                    index=chunk.choices[0].index,
                    usage=stream_usage if stream_usage else None,
                )

    def get_default_model(self) -> str:
        return self.profile.default_model

    @classmethod
    def _get_retryable_exceptions(cls) -> tuple[type[Exception], ...]:
        """返回 OpenAI SDK 中可重试的异常类型元组。"""
        try:
            from openai import (
                APIConnectionError,
                APITimeoutError,
                InternalServerError,
            )
            from openai import (
                RateLimitError as OpenAIRateLimitError,
            )
            return (APITimeoutError, APIConnectionError, InternalServerError, OpenAIRateLimitError)
        except ImportError:
            return ()

    def count_tokens(self, text: str, model: str = "") -> int:
        return self._token_counter.count_tokens(text, model or self.profile.default_model)

    async def list_models(self) -> list[str]:
        """通过 HTTP 调用 OpenAI /v1/models 端点获取可用模型列表。"""
        import httpx
        try:
            headers = {"Authorization": f"Bearer {self.api_key}"}
            async with httpx.AsyncClient(timeout=10.0) as client_http:
                resp = await client_http.get(f"{self.base_url}/models", headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    return sorted([m["id"] for m in data.get("data", [])])
                return []
        except Exception as e:
            _logger.warning("OpenAI list_models failed: %s", e, exc_info=True)
            return []

    async def test_connection(self) -> dict:
        """测试与 OpenAI API 的连接健康状态，返回包含 success、latency_ms、error 的字典。"""
        import time

        import httpx
        start = time.monotonic()
        try:
            headers = {"Authorization": f"Bearer {self.api_key}"}
            async with httpx.AsyncClient(timeout=10.0) as client_http:
                resp = await client_http.get(f"{self.base_url}/models", headers=headers)
                latency_ms = int((time.monotonic() - start) * 1000)
                if resp.status_code in (200, 401, 403):
                    success = resp.status_code == 200
                    return {"success": success, "latency_ms": latency_ms, "error": "" if success else f"HTTP {resp.status_code}: {resp.text[:200]}"}
                return {"success": False, "latency_ms": latency_ms, "error": f"HTTP {resp.status_code}"}
        except Exception as e:
            _logger.warning("OpenAI connection test failed: %s", e, exc_info=True)
            latency_ms = int((time.monotonic() - start) * 1000)
            return {"success": False, "latency_ms": latency_ms, "error": str(e)}