"""
LLM 端口 — 大语言模型推理的抽象接口。

定义与 LLM 交互的核心能力：普通对话和流式对话。
"""
from collections.abc import AsyncIterator
from typing import Protocol

from solagent.schema.llm import LLMRequest, LLMResponse, LLMStreamChunk


class LLMPort(Protocol):
    """LLM 推理协议，封装不同提供商的聊天接口。"""

    async def chat(self, request: LLMRequest) -> LLMResponse:
        """发送非流式聊天请求。

        Args:
            request: LLM 请求对象，包含消息、工具、模型参数等。

        Returns:
            LLM 响应对象，包含生成的内容、工具调用等。
        """
        ...

    async def chat_stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        """发送流式聊天请求，按块返回生成内容。

        Args:
            request: LLM 请求对象。

        Yields:
            流式响应块，包含增量生成的文本内容。
        """
        ...