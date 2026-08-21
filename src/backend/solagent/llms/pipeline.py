"""LLM 请求预处理管道模块。

提供可插拔的中间件机制，允许在请求到达 LLM 提供商之前对其进行检查和修改，
例如注入缺失的 reasoning_content 字段或清洗空内容，以兼容不同提供商的 API 要求。
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from solagent.schema.llm import LLMRequest

# 预处理中间件类型别名：接收 LLMRequest 并返回异步处理后的 LLMRequest
PreprocessMiddleware = Callable[[LLMRequest], Awaitable[LLMRequest]]


class RequestPipeline:
    """LLM 请求预处理中间件链。

    通过依次注册多个中间件，在请求真正发给 LLM 提供商之前逐层处理请求内容。
    模块级别提供了一个默认的单例管道，供各提供商选择性使用。

    典型用法::

        pipeline = RequestPipeline()
        pipeline.add(reasoning_content_injector)
        pipeline.add(empty_content_sanitizer)
        request = await pipeline.process(request)
    """

    def __init__(self) -> None:
        self._middlewares: list[PreprocessMiddleware] = []

    def add(self, middleware: PreprocessMiddleware) -> None:
        """向管道末尾添加一个中间件。"""
        self._middlewares.append(middleware)

    def remove(self, middleware: PreprocessMiddleware) -> None:
        """从管道中移除指定中间件。"""
        self._middlewares.remove(middleware)

    def clear(self) -> None:
        """清空管道中的所有中间件。"""
        self._middlewares.clear()

    async def process(self, request: LLMRequest) -> LLMRequest:
        """按注册顺序依次执行所有中间件，返回最终处理后的请求。"""
        for mw in self._middlewares:
            request = await mw(request)
        return request


# 模块级默认管道单例
_default_pipeline = RequestPipeline()


def get_default_pipeline() -> RequestPipeline:
    """获取模块级别的默认请求预处理管道。"""
    return _default_pipeline


async def reasoning_content_injector(request: LLMRequest) -> LLMRequest:
    """为缺少 reasoning_content 的 assistant 消息注入空值。

    DeepSeek 的 reasoning 模式要求每条 assistant 消息都必须携带 reasoning_content 字段。
    当对话历史由非 reasoning 模型生成时，该字段会缺失，导致 DeepSeek API 返回 400 错误。
    此中间件在请求发送前自动补齐该字段，避免兼容性问题。
    """
    messages = getattr(request, "messages", None)
    if not messages:
        return request
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        if msg.get("role") == "assistant" and "reasoning_content" not in msg:
            msg["reasoning_content"] = " "
    return request


async def empty_content_sanitizer(request: LLMRequest) -> LLMRequest:
    """清洗消息中的空 content 字段。

    某些提供商拒绝接受空字符串的 assistant 消息 content。
    对于包含 tool_calls 的 assistant 消息，将空内容替换为 None；
    其他情况则替换为 "(empty)" 占位文本，以保证请求能通过提供商校验。
    """
    messages = getattr(request, "messages", None)
    if not messages:
        return request
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if isinstance(content, str) and not content.strip():
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                msg["content"] = None
            else:
                msg["content"] = "(empty)"
    return request