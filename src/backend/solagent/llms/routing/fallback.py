"""故障转移链：当主 LLM 提供商不可用时，按顺序切换到备用提供商。

适用于高可用场景，确保即使某个服务商出现网络故障或限流，
整体请求仍有机会被后续备用节点成功处理。
"""
import logging
from collections.abc import AsyncIterator

from solagent.errors.llm import LLMError
from solagent.llms.providers.base import LLMProvider
from solagent.schema.llm import LLMRequest, LLMResponse, LLMStreamChunk

_logger = logging.getLogger(__name__)


class FallbackChain:
    """按优先级排列的 LLM 提供商故障转移链。

    属性:
        _providers: 按优先级排序的 LLMProvider 列表，索引越小优先级越高。
    """

    def __init__(self, providers: list[LLMProvider]):
        self._providers = providers

    async def chat(self, request: LLMRequest) -> LLMResponse:
        """执行普通对话请求，依次尝试每个提供商直到成功。

        参数:
            request: LLM 请求对象。

        返回:
            第一个成功响应的 LLMResponse。

        异常:
            LLMError: 当所有提供商均失败时抛出，并携带最后一次异常。
        """
        last_error = None
        for provider in self._providers:
            try:
                return await provider.chat(request)
            except Exception as e:
                _logger.warning("LLM fallback provider '%s' chat failed: %s", provider.profile.name, e, exc_info=True)
                last_error = e
        raise LLMError(f"All {len(self._providers)} providers failed") from last_error

    async def chat_stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        """执行流式对话请求，依次尝试每个提供商直到成功。

        流式回退需要先将备用提供商的全部 chunk 缓冲到内存，
        确认无异常后再逐块 yield，避免客户端收到中断的流。

        参数:
            request: LLM 流式请求对象。

        异常:
            LLMError: 当所有提供商均失败时抛出，并携带最后一次异常。
        """
        last_error = None
        for provider in self._providers:
            try:
                # 先将流内容完整缓冲，确保不抛出异常后再向客户端输出
                buffer: list[LLMStreamChunk] = []
                async for chunk in provider.chat_stream(request):
                    buffer.append(chunk)
                for chunk in buffer:
                    yield chunk
                return
            except Exception as e:
                _logger.warning("LLM fallback provider '%s' stream failed: %s", provider.profile.name, e, exc_info=True)
                last_error = e
        raise LLMError(f"All {len(self._providers)} providers failed") from last_error
