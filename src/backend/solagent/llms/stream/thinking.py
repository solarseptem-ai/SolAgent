"""推理内容解析器：统一处理 Anthropic thinking 与 DeepSeek reasoning_content。

不同模型对"推理过程"的表示方式不同：
- Anthropic 通过流式 chunk 的 is_thinking 标志区分思考内容与正式回复；
- DeepSeek 在 API 响应中提供独立的 reasoning_content 字段。

本模块将两种风格统一抽象，方便上层无差别地提取和展示模型的推理过程。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ThinkingState:
    """记录推理模型产生的各类内容片段。

    同时支持 Anthropic 和 DeepSeek 两种推理模式：
    - Anthropic: 以 ``is_thinking=True`` 标记的流式 chunk。
    - DeepSeek: API 响应中的 ``reasoning_content`` 字段。

    属性:
        thinking_content: Anthropic 风格的 thinking 内容累积。
        reasoning_content: DeepSeek 风格的 reasoning_content 累积。
        response_content: 正式的回复内容累积。
        is_thinking: 当前是否处于 thinking 阶段。
        thinking_signature: thinking 内容的签名（如适用）。
    """
    thinking_content: str = ""
    reasoning_content: str = ""
    response_content: str = ""
    is_thinking: bool = True
    thinking_signature: str = ""

    @property
    def all_reasoning(self) -> str:
        """返回所有推理内容的合并结果（Anthropic thinking + DeepSeek reasoning）。"""
        return self.thinking_content + self.reasoning_content


class ThinkingParser:
    """流式推理内容解析器，将 thinking 与正式回复分离。

    统一处理 Anthropic（is_thinking 标志）和 DeepSeek（reasoning_content 字段）两种风格。

    属性:
        _state: 内部 ThinkingState，用于累积各类内容。
    """

    def __init__(self):
        self._state = ThinkingState()

    def feed(self, chunk_text: str, is_thinking: bool = False) -> tuple[str, str]:
        """输入一个文本 chunk，根据 is_thinking 标志分类存储。

        参数:
            chunk_text: 当前 chunk 的文本内容。
            is_thinking: 是否为 thinking 内容（Anthropic 风格）。

        返回:
            (本次的 thinking_text, 本次的 response_text) 元组。
        """
        if is_thinking:
            self._state.thinking_content += chunk_text
            return (chunk_text, "")
        self._state.response_content += chunk_text
        return ("", chunk_text)

    def feed_reasoning(self, reasoning_content: str) -> tuple[str, str]:
        """输入 DeepSeek 风格的 reasoning_content。

        参数:
            reasoning_content: DeepSeek 返回的 reasoning_content 片段。

        返回:
            (reasoning_text, 空字符串) — reasoning 与 thinking 分开追踪。
        """
        self._state.reasoning_content += reasoning_content
        return (reasoning_content, "")

    @property
    def thinking(self) -> str:
        """返回已累积的 Anthropic 风格 thinking 内容。"""
        return self._state.thinking_content

    @property
    def reasoning(self) -> str:
        """返回已累积的 DeepSeek 风格 reasoning 内容。"""
        return self._state.reasoning_content

    @property
    def response(self) -> str:
        """返回已累积的正式回复内容。"""
        return self._state.response_content

    @property
    def all_reasoning(self) -> str:
        """返回所有推理内容的合并结果。"""
        return self._state.all_reasoning

    def reset(self) -> None:
        """清空所有累积内容，重置解析器状态。"""
        self._state = ThinkingState()