"""对话 consolidator，用于将长对话压缩为带标签的摘要。

当对话历史超过 token 预算时，通过 LLM 对对话进行总结，并为每个事实打上
[permanent]、[durable]、[ephemeral]、[correction]、[skip] 标签，
便于后续记忆系统按重要性分层存储和检索。
"""

from __future__ import annotations

import inspect

from solagent.schema.messages import Message


class Consolidator:
    """对话摘要与标签化处理器。

    使用预设的提示词模板驱动 LLM，将多轮对话提炼为结构化摘要。
    若对话长度未超过预算，则直接返回原始格式化文本。

    属性:
        provider: LLM 提供者，用于执行摘要生成。
        max_tokens: 触发摘要的 token 阈值（按字符数估算）。
    """

    CONSOLIDATION_PROMPT = (
        "Summarize the following conversation, tagging each fact with one of:\n"
        "[permanent] — core strategies, rules, never changes\n"
        "[durable] — long-term useful patterns\n"
        "[ephemeral] — transient, may become outdated\n"
        "[correction] — user-corrected mistakes\n"
        "[skip] — not worth remembering\n\n"
        "Conversation:\n{conversation}"
    )

    def __init__(self, provider, max_tokens: int = 2000):
        """初始化 Consolidator。

        参数:
            provider: LLM 提供者实例。
            max_tokens: 触发摘要生成的字符长度阈值。
        """
        self._provider = provider
        self._max_tokens = max_tokens

    async def consolidate(self, messages: list[Message]) -> str:
        """将消息列表格式化为文本，若超过预算则生成带标签的摘要。

        参数:
            messages: 原始对话消息列表。

        返回:
            格式化后的对话文本或 LLM 生成的摘要文本。
        """
        text = self._format_messages(messages)
        if self._estimate_tokens(text) <= self._max_tokens:
            return text
        result = self._provider.chat(
            self.CONSOLIDATION_PROMPT.format(conversation=text)
        )
        if inspect.isawaitable(result):
            result = await result
        return result.content if hasattr(result, "content") else str(result)

    def _format_messages(self, messages: list[Message]) -> str:
        """将消息列表转换为统一的纯文本格式，便于 LLM 处理。

        参数:
            messages: 消息列表。

        返回:
            每条消息按 '[ROLE] content' 格式拼接后的文本。
        """
        from solagent.schema.messages import TextBlock, ThinkingBlock

        parts: list[str] = []
        for msg in messages:
            role = msg.role.upper() if hasattr(msg.role, "upper") else str(msg.role)
            text_parts = []
            for block in msg.content:
                if isinstance(block, TextBlock):
                    if block.text:
                        text_parts.append(block.text)
                elif isinstance(block, ThinkingBlock):
                    if block.thinking:
                        text_parts.append(block.thinking)
            content = " ".join(text_parts) if text_parts else ""
            parts.append(f"[{role}] {content}")
        return "\n".join(parts)

    def _estimate_tokens(self, text: str) -> int:
        """粗略估算文本的 token 数量（按字符数近似）。"""
        return len(text)
