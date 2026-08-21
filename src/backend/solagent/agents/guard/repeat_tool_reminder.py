"""重复工具调用提醒守卫。

检测 Agent 是否连续使用完全相同的参数调用同一工具，防止陷入无进展循环。
采用渐进式策略：首次达到较低阈值时发出温和提醒，达到最高阈值时才硬阻止执行。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from solagent.agents.guard.base import GuardContext, GuardResult


class RepeatToolReminder:
    """重复工具调用检测与提醒守卫。

    属性:
        thresholds: 触发提醒和阻止的连续调用次数阈值元组，默认 (3, 5, 8)。
        max_args_preview: 提醒信息中参数预览的最大字符数。
        consecutive: 维护最近连续调用的 (tool_name, args_hash) 列表。
    """

    def __init__(self, thresholds: tuple[int, ...] = (3, 5, 8), max_args_preview: int = 500):
        self._thresholds = thresholds
        self._max_args_preview = max_args_preview
        self._consecutive: list[tuple[str, str]] = []

    def _hash_args(self, tool_args: dict[str, Any]) -> str:
        """对工具参数进行 SHA256 哈希，用于精确比对参数是否完全相同。"""
        return hashlib.sha256(
            json.dumps(tool_args, sort_keys=True, default=str).encode()
        ).hexdigest()

    def _preview_args(self, tool_args: dict[str, Any]) -> str:
        """生成参数预览文本，过长时截断并追加省略号。"""
        text = json.dumps(tool_args, sort_keys=True, default=str)
        if len(text) > self._max_args_preview:
            return text[: self._max_args_preview] + "..."
        return text

    async def check(self, tool_name: str, tool_args: dict[str, Any], context: GuardContext) -> GuardResult:
        """检查当前调用是否与最近连续调用链完全相同，按阈值返回提醒或阻止结果。"""
        args_hash = self._hash_args(tool_args)
        self._consecutive.append((tool_name, args_hash))

        count = 0
        for t, h in reversed(self._consecutive):
            if t == tool_name and h == args_hash:
                count += 1
            else:
                break

        if count < self._thresholds[0]:
            return GuardResult()

        if count >= self._thresholds[-1]:
            return GuardResult(
                blocked=True,
                risk_level="medium",
                code="repeat_tool",
                reason=(
                    f"Tool '{tool_name}' called with identical arguments {count} times consecutively "
                    f"({self._preview_args(tool_args)}). Consider a different approach."
                ),
            )

        return GuardResult(
            blocked=False,
            risk_level="low",
            code="repeat_tool_reminder",
            reason=f"Tool '{tool_name}' called with identical arguments {count} times consecutively.",
        )
