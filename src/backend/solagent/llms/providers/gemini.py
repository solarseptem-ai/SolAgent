"""Google Gemini 提供商占位模块。

当前尚未实现完整的 Gemini SDK 集成，建议暂时通过 CustomProvider 配合 Gemini 兼容端点使用。
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from solagent.llms.providers.base import LLMProvider
from solagent.llms.providers.profile import ProviderProfile
from solagent.schema.llm import LLMRequest, LLMResponse, LLMStreamChunk


class GeminiProvider(LLMProvider):
    """Gemini 提供商占位类，所有方法均抛出 NotImplementedError。"""

    def __init__(self, api_key: str | None = None) -> None:
        raise NotImplementedError("GeminiProvider is not yet implemented. Use CustomProvider with a Gemini-compatible endpoint.")

    @property
    def profile(self) -> ProviderProfile:
        raise NotImplementedError("GeminiProvider is not yet implemented.")

    async def chat(self, request: LLMRequest) -> LLMResponse:
        raise NotImplementedError("GeminiProvider is not yet implemented.")

    async def chat_stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        raise NotImplementedError("GeminiProvider is not yet implemented.")

    def get_default_model(self) -> str:
        raise NotImplementedError("GeminiProvider is not yet implemented.")

    @classmethod
    def _get_retryable_exceptions(cls) -> tuple[type[Exception], ...]:
        return ()

    def count_tokens(self, text: str, model: str = "") -> int:
        raise NotImplementedError("GeminiProvider is not yet implemented.")