"""LLM 提供商钩子模块。

定义一组可插拔的钩子接口，允许各提供商在消息发送前、请求体构造时、
API 参数补充时以及获取模型列表时注入自定义逻辑，实现差异化的适配行为。
"""
from __future__ import annotations

from collections.abc import Callable

from solagent.schema.llm import LLMRequest
from solagent.schema.messages import Message


class ProviderHooks:
    """提供商行为定制钩子集合。

    属性:
        prepare_messages: 在将消息发给 API 前调用的预处理钩子，签名: (messages: list[Message]) -> list[Message]。
        build_extra_body: 构造额外请求体字段的钩子，签名: (request: LLMRequest) -> dict。
        build_api_kwargs_extras: 构造额外 API 参数的钩子，签名: (request: LLMRequest) -> dict。
        fetch_models: 获取可用模型列表的钩子，签名: () -> list[str]。
    """

    def __init__(self):
        self.prepare_messages: Callable[[list[Message]], list[Message]] | None = None
        self.build_extra_body: Callable[[LLMRequest], dict] | None = None
        self.build_api_kwargs_extras: Callable[[LLMRequest], dict] | None = None
        self.fetch_models: Callable[[], list[str]] | None = None


def anthropic_hooks() -> ProviderHooks:
    """Anthropic 提供商的标准钩子（当前仅保留消息透传逻辑，供后续扩展）。"""
    hooks = ProviderHooks()

    def prepare_messages(messages: list[Message]) -> list[Message]:
        result = []
        for msg in messages:
            if msg.role.value == "system":
                result.append(msg)
            else:
                result.append(msg)
        return result

    hooks.prepare_messages = prepare_messages
    return hooks


def deepseek_thinking_hooks() -> ProviderHooks:
    """DeepSeek reasoning 模式的钩子占位（当前为空实现，后续可扩展 reasoning_content 相关逻辑）。"""
    hooks = ProviderHooks()

    def build_extra_body(request: LLMRequest) -> dict:
        if request.model == "deepseek-reasoner":
            return {}
        return {}

    hooks.build_extra_body = build_extra_body
    return hooks