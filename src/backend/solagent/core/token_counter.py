"""Token 计数模块，提供多种策略的文本 Token 估算能力。

本模块支持基于 tiktoken 的精确计数（适用于 OpenAI 等兼容模型）
以及基于字符数的粗略估算（适用于未知模型或 tiktoken 不可用的场景）。
通过统一的 TokenCounter 协议和 auto_counter 工厂函数，上层代码可以
根据模型名称自动选择最合适的计数策略。
"""
from __future__ import annotations

from typing import ClassVar, Protocol

import tiktoken

# 模型名称到 tiktoken 编码器名称的映射表
_TIKTOKEN_MODEL_MAP: dict[str, str] = {
    "gpt-4o": "o200k_base",
    "gpt-4o-mini": "o200k_base",
    "gpt-4": "cl100k_base",
    "gpt-4-32k": "cl100k_base",
    "gpt-4-turbo": "cl100k_base",
    "gpt-4-vision-preview": "cl100k_base",
    "gpt-3.5-turbo": "cl100k_base",
    "gpt-3.5-turbo-16k": "cl100k_base",
    "gpt-3.5-turbo-instruct": "cl100k_base",
    "text-embedding-ada-002": "cl100k_base",
    "text-embedding-3-small": "cl100k_base",
    "text-embedding-3-large": "cl100k_base",
    "claude-3-opus": "cl100k_base",
    "claude-3-sonnet": "cl100k_base",
    "claude-3-haiku": "cl100k_base",
    "claude-3.5-sonnet": "cl100k_base",
    "claude-3.5-haiku": "cl100k_base",
}


class TokenCounter(Protocol):
    """Token 计数协议，定义了统一的文本 Token 估算接口。

    实现类需根据具体模型或算法提供 count_tokens 方法，
    返回给定文本在该模型下大致消耗的 Token 数量。
    """
    def count_tokens(self, text: str, model: str = "") -> int: ...


class CharTokenCounter:
    """基于字符数的粗略 Token 计数器。

    采用经验公式：Token 数 ≈ 字符数 / 4。适用于 tiktoken 不支持的模型
    或需要快速估算的场景，精度较低但零依赖。
    """

    def count_tokens(self, text: str, model: str = "") -> int:
        """按字符数除以 4 估算 Token 数，至少返回 1。"""
        return max(1, len(text) // 4)


class TiktokenCounter:
    """基于 tiktoken 库的精确 Token 计数器。

    使用 tiktoken 的 Encoding 对象对文本进行分词，获得准确的 Token 数量。
    通过类级缓存（_encoders）避免重复创建编码器实例，提升性能。
    """
    _encoders: ClassVar[dict[str, tiktoken.Encoding]] = {}

    def count_tokens(self, text: str, model: str = "") -> int:
        """使用 tiktoken 编码器精确计算文本的 Token 数量。

        若模型不在映射表中，则回退到 CharTokenCounter 进行粗略估算。

        Args:
            text: 待计数的文本内容。
            model: 模型名称，用于选择对应的 tiktoken 编码器。

        Returns:
            文本的 Token 数量估算值。
        """
        encoding_name = _TIKTOKEN_MODEL_MAP.get(model)
        if encoding_name is None:
            return CharTokenCounter().count_tokens(text, model)
        # 缓存编码器实例，避免重复初始化
        if encoding_name not in self._encoders:
            self._encoders[encoding_name] = tiktoken.get_encoding(encoding_name)
        encoder = self._encoders[encoding_name]
        return len(encoder.encode(text))


def auto_counter(model: str = "") -> TokenCounter:
    """根据模型名称自动选择合适的 Token 计数器。

    若模型在 tiktoken 映射表中，返回 TiktokenCounter 以获得精确计数；
    否则返回 CharTokenCounter 作为兜底方案。

    Args:
        model: 模型名称。

    Returns:
        适配该模型的 TokenCounter 实例。
    """
    if model in _TIKTOKEN_MODEL_MAP:
        return TiktokenCounter()
    return CharTokenCounter()