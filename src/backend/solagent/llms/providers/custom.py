"""自定义 LLM 提供商模块。

为任意 OpenAI 兼容端点提供通用适配实现，通过 ProviderProfile 动态配置基础地址、
模型列表和 API 密钥，无需为每个端点单独编写提供商类。
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


class CustomProvider(LLMProvider):
    """自定义提供商，适配任何 OpenAI 兼容的 LLM 端点。

    通过传入 ProviderProfile 即可动态配置 API 地址、模型列表和功能开关，
    内部使用 AsyncOpenAI 客户端与端点通信。
    """

    def __init__(self, profile: ProviderProfile, api_key: str | None = None) -> None:
        self._profile = profile
        self.api_key = api_key or os.getenv(profile.env_key, "")
        self._client = None
        self._token_counter = auto_counter(profile.default_model or "gpt-4o")

    @property
    def profile(self) -> ProviderProfile:
        return self._profile

    def _get_client(self):
        """延迟初始化并返回 AsyncOpenAI 客户端实例。"""
        if self._client is None:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(api_key=self.api_key, base_url=self.profile.base_url, max_retries=0)
        return self._client

    def _parse_finish_reason(self, raw: str) -> LLMFinishReason:
        """将 OpenAI 兼容端点的 finish_reason 映射为内部枚举值。"""
        mapping = {"stop": LLMFinishReason.STOP, "tool_calls": LLMFinishReason.TOOL_CALLS,
                   "length": LLMFinishReason.LENGTH, "content_filter": LLMFinishReason.CONTENT_FILTER}
        return mapping.get(raw, LLMFinishReason.STOP)

    async def chat(self, request: LLMRequest) -> LLMResponse:
        """发送非流式对话请求，内部使用流式接口收集完整响应以统一处理工具调用。"""
        client = self._get_client()
        kwargs = {"model": request.model, "messages": FormatConverter.to_openai_messages(request.messages),
                  "temperature": request.temperature, "max_tokens": request.max_tokens, "top_p": request.top_p,
                  "stream": True, "stream_options": {"include_usage": True}}
        if request.tools:
            kwargs["tools"] = FormatConverter.tools_to_openai(request.tools)
        if request.stop:
            kwargs["stop"] = request.stop

        content_parts = []
        tool_calls_map: dict[int, dict] = {}
        finish_reason = LLMFinishReason.STOP
        total_usage = TokenUsage()

        stream = await client.chat.completions.create(**kwargs)
        async for chunk in stream:
            if chunk.usage:
                total_usage = TokenUsage(
                    input_tokens=chunk.usage.prompt_tokens or 0,
                    output_tokens=chunk.usage.completion_tokens or 0,
                )
            if chunk.choices and chunk.choices[0].delta:
                delta = chunk.choices[0].delta
                if delta.content:
                    content_parts.append(delta.content)
                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in tool_calls_map:
                            tool_calls_map[idx] = {"id": tc_delta.id or "", "name": "", "arguments": ""}
                        if tc_delta.id:
                            tool_calls_map[idx]["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                tool_calls_map[idx]["name"] = tc_delta.function.name
                            if tc_delta.function.arguments:
                                tool_calls_map[idx]["arguments"] += tc_delta.function.arguments
                finish = chunk.choices[0].finish_reason or ""
                if finish:
                    finish_reason = self._parse_finish_reason(finish)

        content = "".join(content_parts)
        tool_calls = []
        for idx in sorted(tool_calls_map.keys()):
            tc = tool_calls_map[idx]
            args = tc["arguments"]
            parsed_args = parse_and_repair_arguments(args) if args else {}
            tool_calls.append(ToolCall(id=tc["id"], name=tc["name"], arguments=parsed_args))

        if tool_calls:
            finish_reason = LLMFinishReason.TOOL_CALLS

        return LLMResponse(content=content, finish_reason=finish_reason, usage=total_usage, tool_calls=tool_calls, model=request.model)

    async def chat_stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        """发送流式对话请求，逐块 yield LLMStreamChunk。"""
        client = self._get_client()
        kwargs = {"model": request.model, "messages": FormatConverter.to_openai_messages(request.messages),
                  "temperature": request.temperature, "max_tokens": request.max_tokens, "top_p": request.top_p,
                  "stream": True, "stream_options": {"include_usage": True}}
        if request.tools:
            kwargs["tools"] = FormatConverter.tools_to_openai(request.tools)
        stream = await client.chat.completions.create(**kwargs)
        tool_calls_map: dict[int, dict] = {}
        stream_usage: TokenUsage | None = None
        chunk_count = 0
        async for chunk in stream:
            if chunk.usage:
                stream_usage = TokenUsage(
                    input_tokens=chunk.usage.prompt_tokens or 0,
                    output_tokens=chunk.usage.completion_tokens or 0,
                )
            if chunk.choices and chunk.choices[0].delta:
                delta = chunk.choices[0].delta
                finish = chunk.choices[0].finish_reason or ""
                chunk_count += 1
                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index or 0
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
                            usage=stream_usage,
                        )
                content = delta.content or ""
                reasoning = getattr(delta, "reasoning_content", None)
                if isinstance(reasoning, str) and reasoning:
                    yield LLMStreamChunk(content="", reasoning_content=reasoning, index=chunk.choices[0].index, usage=stream_usage)
                if content:
                    yield LLMStreamChunk(content=content, index=chunk.choices[0].index, usage=stream_usage)
                if finish:
                    yield LLMStreamChunk(content="", finish_reason=self._parse_finish_reason(finish), index=chunk.choices[0].index, usage=stream_usage)
        if chunk_count == 0:
            # 若流式接口未返回任何 chunk，回退到非流式调用保证有输出
            response = await self.chat(request)
            yield LLMStreamChunk(content=response.content,
                finish_reason=response.finish_reason,
                index=0)

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
        """通过 HTTP GET 请求获取端点支持的模型列表。"""
        import httpx
        try:
            headers = {"Authorization": f"Bearer {self.api_key}"}
            async with httpx.AsyncClient(timeout=10.0) as client_http:
                resp = await client_http.get(f"{self.profile.base_url}/models", headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    return sorted([m["id"] for m in data.get("data", [])])
                return []
        except Exception as e:
            _logger.warning("Custom provider '%s' list_models failed: %s", self.profile.name, e, exc_info=True)
            return []

    async def test_connection(self) -> dict:
        """测试与自定义端点的连接健康状态。"""
        import time

        import httpx
        start = time.monotonic()
        try:
            headers = {"Authorization": f"Bearer {self.api_key}"}
            async with httpx.AsyncClient(timeout=10.0) as client_http:
                resp = await client_http.get(f"{self.profile.base_url}/models", headers=headers)
                latency_ms = int((time.monotonic() - start) * 1000)
                if resp.status_code in (200, 401, 403):
                    success = resp.status_code == 200
                    return {"success": success, "latency_ms": latency_ms, "error": "" if success else f"HTTP {resp.status_code}: {resp.text[:200]}"}
                return {"success": False, "latency_ms": latency_ms, "error": f"HTTP {resp.status_code}"}
        except Exception as e:
            _logger.warning("Custom provider '%s' connection test failed: %s", self.profile.name, e, exc_info=True)
            latency_ms = int((time.monotonic() - start) * 1000)
            return {"success": False, "latency_ms": latency_ms, "error": str(e)}