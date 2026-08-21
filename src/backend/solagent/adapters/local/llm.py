"""本地 LLM 适配器：将 Provider 包装为 LLMPort 的本地实现。

在同进程内直接调用 LLMProvider 的 chat / chat_stream 方法，
无需网络序列化开销，适用于本地直连模型或测试环境。
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from solagent.schema.llm import LLMRequest, LLMResponse, LLMStreamChunk


class LocalLLMAdapter:
    """本地 LLM 端口适配器。

    属性:
        _provider: 被包装的 LLMProvider 实例。
    """

    def __init__(self, provider):
        self._provider = provider

    async def chat(self, request: LLMRequest) -> LLMResponse:
        """执行本地同步对话请求。

        参数:
            request: LLM 请求对象。

        返回:
            LLM 的完整响应结果。
        """
        return await self._provider.chat(request)

    async def chat_stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        """执行本地流式对话请求，透传 chunk 流。

        参数:
            request: LLM 流式请求对象。
        """
        async for chunk in self._provider.chat_stream(request):
            yield chunk