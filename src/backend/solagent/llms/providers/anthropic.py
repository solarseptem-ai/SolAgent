"""Anthropic 提供商实现模块。

基于 Anthropic Python SDK 实现 LLMProvider 接口，支持 Messages API、
流式输出、工具调用、thinking 内容和多模态图片输入。
"""
from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator

_logger = logging.getLogger(__name__)

from solagent.agents.tools.validator import parse_and_repair_arguments
from solagent.core.token_counter import auto_counter
from solagent.llms.providers.base import LLMProvider
from solagent.llms.providers.profile import ProviderProfile
from solagent.schema.llm import LLMFinishReason, LLMRequest, LLMResponse, LLMStreamChunk, TokenUsage
from solagent.schema.messages import ImageBlock, Message, MessageRole, TextBlock, ThinkingBlock, ToolResultBlock
from solagent.schema.tools import ToolCall, ToolDefinition


class AnthropicProvider(LLMProvider):
    """Anthropic 提供商实现，封装了与 Anthropic Messages API 的交互。"""

    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.base_url = base_url or "https://api.anthropic.com"
        self._client = None
        self._token_counter = auto_counter("claude-3-5-sonnet")

    @property
    def profile(self) -> ProviderProfile:
        """返回 Anthropic 提供商的固定配置画像。"""
        return ProviderProfile(
            name="anthropic", display_name="Anthropic", api_mode="anthropic_messages",
            base_url=self.base_url, env_key="ANTHROPIC_API_KEY",
            default_model="claude-3-5-sonnet-20241022",
            models=["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022", "claude-3-opus-20240229"],
            supports_vision=True, supports_tools=True, supports_streaming=True, supports_thinking=True,
        )

    def _get_client(self):
        """延迟初始化并返回 AsyncAnthropic 客户端实例。"""
        if self._client is None:
            from anthropic import AsyncAnthropic
            self._client = AsyncAnthropic(api_key=self.api_key, base_url=self.base_url, max_retries=0)
        return self._client

    def _extract_system_prompt(self, messages: list[Message]) -> str:
        """从消息列表中提取所有 system 角色的文本内容，合并为 Anthropic 所需的 system 参数。"""
        parts = []
        for msg in messages:
            if msg.role == MessageRole.SYSTEM:
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        parts.append(block.text)
        return "\n".join(parts)

    def _messages_to_anthropic(self, messages: list[Message]) -> list[dict]:
        """将内部 Message 列表转换为 Anthropic Messages API 所需的格式。

        Anthropic 要求 system prompt 单独传入，因此在此过滤掉 system 消息；
        同时处理 tool_result、tool_use、image、thinking 等特殊内容块。
        """
        result: list[dict] = []
        for msg in messages:
            if msg.role == MessageRole.SYSTEM:
                continue
            role = "assistant" if msg.role == MessageRole.ASSISTANT else "user"

            if msg.role == MessageRole.TOOL:
                for block in msg.content:
                    if isinstance(block, ToolResultBlock):
                        result.append({
                            "role": "user",
                            "content": [{"type": "tool_result", "tool_use_id": block.tool_call_id, "content": block.content}],
                        })
                continue

            content_blocks: list[dict] = []
            for block in msg.content:
                if isinstance(block, TextBlock):
                    content_blocks.append({"type": "text", "text": block.text})
                elif isinstance(block, ImageBlock):
                    content_blocks.append({
                        "type": "image",
                        "source": {"type": "base64", "media_type": block.source.media_type or "image/png", "data": block.source.data or ""},
                    })
                elif isinstance(block, ThinkingBlock):
                    content_blocks.append({"type": "thinking", "thinking": block.thinking, "signature": block.signature or ""})

            if msg.role == MessageRole.ASSISTANT:
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        content_blocks.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments})
                if not content_blocks:
                    content_blocks.append({"type": "text", "text": ""})

            result.append({"role": role, "content": content_blocks})
        return result

    def _tools_to_anthropic(self, tools: list[ToolDefinition]) -> list[dict]:
        """将内部 ToolDefinition 列表转换为 Anthropic 工具声明格式。"""
        return [t.to_anthropic_schema() for t in tools]

    def _parse_finish_reason(self, raw: str) -> LLMFinishReason:
        """将 Anthropic 的 stop_reason 映射为内部 LLMFinishReason 枚举。"""
        mapping = {"end_turn": LLMFinishReason.STOP, "tool_use": LLMFinishReason.TOOL_CALLS,
                   "max_tokens": LLMFinishReason.LENGTH, "stop_sequence": LLMFinishReason.STOP}
        return mapping.get(raw, LLMFinishReason.STOP)

    async def chat(self, request: LLMRequest) -> LLMResponse:
        """发送非流式 Messages API 请求，返回完整的 LLMResponse。"""
        client = self._get_client()
        system = self._extract_system_prompt(request.messages)
        messages = self._messages_to_anthropic(request.messages)

        kwargs: dict = {"model": request.model, "messages": messages, "max_tokens": request.max_tokens}
        if system:
            kwargs["system"] = system
        if request.temperature > 0:
            kwargs["temperature"] = request.temperature
        if request.top_p < 1.0:
            kwargs["top_p"] = request.top_p
        if request.tools:
            kwargs["tools"] = self._tools_to_anthropic(request.tools)
        if request.stop:
            kwargs["stop_sequences"] = request.stop

        response = await client.messages.create(**kwargs)
        content = ""
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                content += block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, arguments=parse_and_repair_arguments(block.input)))

        finish_reason = self._parse_finish_reason(response.stop_reason or "end_turn")
        if tool_calls:
            finish_reason = LLMFinishReason.TOOL_CALLS

        usage = TokenUsage(input_tokens=response.usage.input_tokens, output_tokens=response.usage.output_tokens)
        return LLMResponse(content=content, finish_reason=finish_reason, usage=usage, tool_calls=tool_calls, model=request.model)

    async def chat_stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        """发送流式 Messages API 请求，通过 SDK 的 stream 事件逐块 yield 结果。"""
        client = self._get_client()
        system = self._extract_system_prompt(request.messages)
        messages = self._messages_to_anthropic(request.messages)

        kwargs: dict = {"model": request.model, "messages": messages, "max_tokens": request.max_tokens, "stream": True}
        if system:
            kwargs["system"] = system
        if request.temperature > 0:
            kwargs["temperature"] = request.temperature
        if request.tools:
            kwargs["tools"] = self._tools_to_anthropic(request.tools)

        async with client.messages.stream(**kwargs) as stream:
            tool_use_blocks: list[dict[str, str]] = []
            stream_usage: TokenUsage | None = None
            async for event in stream:
                if event.type == "content_block_start":
                    block = event.content_block
                    if block.type == "tool_use":
                        tool_use_blocks.append({"id": block.id, "name": block.name, "arguments": ""})
                        yield LLMStreamChunk(
                            content="",
                            tool_call_id=block.id,
                            tool_call_name=block.name,
                            tool_call_arguments="",
                            index=len(tool_use_blocks) - 1,
                            usage=stream_usage,
                        )
                elif event.type == "content_block_delta":
                    if event.delta.type == "text_delta":
                        yield LLMStreamChunk(content=event.delta.text, usage=stream_usage)
                    elif event.delta.type == "thinking_delta":
                        yield LLMStreamChunk(content=event.delta.thinking, is_thinking=True, usage=stream_usage)
                    elif event.delta.type == "input_json_delta":
                        if tool_use_blocks:
                            current = tool_use_blocks[-1]
                            current["arguments"] += event.delta.partial_json
                            yield LLMStreamChunk(
                                content="",
                                tool_call_id=current["id"],
                                tool_call_name=current["name"],
                                tool_call_arguments=event.delta.partial_json or "",
                                index=len(tool_use_blocks) - 1,
                                usage=stream_usage,
                            )
                elif event.type == "message_delta":
                    finish = event.delta.stop_reason or "end_turn"
                    if event.usage:
                        stream_usage = TokenUsage(
                            input_tokens=event.usage.input_tokens or 0,
                            output_tokens=event.usage.output_tokens or 0,
                            cache_read_tokens=getattr(event.usage, 'cache_read_input_tokens', 0) or 0,
                        )
                    yield LLMStreamChunk(content="", finish_reason=self._parse_finish_reason(finish), usage=stream_usage)

    def get_default_model(self) -> str:
        return self.profile.default_model

    @classmethod
    def _get_retryable_exceptions(cls) -> tuple[type[Exception], ...]:
        """返回 Anthropic SDK 中可重试的异常类型元组。"""
        try:
            from anthropic import (
                APIConnectionError,
                APITimeoutError,
                InternalServerError,
            )
            from anthropic import (
                RateLimitError as AnthropicRateLimitError,
            )
            return (APITimeoutError, APIConnectionError, InternalServerError, AnthropicRateLimitError)
        except ImportError:
            return ()

    def count_tokens(self, text: str, model: str = "") -> int:
        return self._token_counter.count_tokens(text, model or self.profile.default_model)

    async def list_models(self) -> list[str]:
        """Anthropic 暂无公开 /models 端点，返回配置中已知的模型列表。"""
        return list(self.profile.models)

    async def test_connection(self) -> dict:
        """测试与 Anthropic API 的连接健康状态。

        由于 /v1/messages 对 GET 请求会返回特定状态码，
        将 200/401/403 均视为可达，用于区分网络故障和权限问题。
        """
        import time

        import httpx
        start = time.monotonic()
        try:
            headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}
            async with httpx.AsyncClient(timeout=10.0) as c:
                resp = await c.get(f"{self.base_url}/v1/messages", headers=headers)
                latency_ms = int((time.monotonic() - start) * 1000)
                success = resp.status_code in (200, 401, 403)  # 401=密钥错误, 403=禁止访问，但服务可达
                return {"success": success, "latency_ms": latency_ms, "error": "" if success else f"HTTP {resp.status_code}"}
        except Exception as e:
            _logger.warning("Anthropic connection test failed: %s", e, exc_info=True)
            return {"success": False, "latency_ms": int((time.monotonic() - start) * 1000), "error": str(e)}