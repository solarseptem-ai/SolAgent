"""工具调用循环检测守卫。

检测 Agent 是否陷入无意义的重复工具调用循环，包括：
- 相同参数连续失败多次（exact_failure_block）
- 同一工具连续失败多次（same_tool_block）
- 幂等工具多次返回相同结果（no_progress_block）

适用于防止 Agent 在错误参数或错误思路上无限重试。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from solagent.agents.guard.base import GuardContext, GuardResult

# 幂等工具集合：多次调用结果应相同，若结果不变则认为无进展
IDEMPOTENT_TOOLS = frozenset({
    "read", "ls", "glob", "grep", "web_search", "web_fetch",
    "get_current_time", "get_token_usage",
})

# 可变工具集合：可能改变系统状态，需特别关注循环调用
MUTATING_TOOLS = frozenset({
    "write", "edit", "shell", "apply_patch", "remember", "forget",
    "subagent", "skill_view",
})


class LoopDetector:
    """循环检测守卫，基于工具调用历史识别无进展重复调用。

    属性:
        exact_failure_block: 相同参数连续失败达到此阈值则阻止。
        same_tool_block: 同一工具连续失败达到此阈值则阻止。
        no_progress_block: 幂等工具无进展重复调用达到此阈值则阻止。
    """

    def __init__(self, exact_failure_block: int = 5, same_tool_block: int = 8,
                 no_progress_block: int = 5):
        self._exact_failure_block = exact_failure_block
        self._same_tool_block = same_tool_block
        self._no_progress_block = no_progress_block

    def _hash_args(self, tool_args: dict[str, Any]) -> str:
        """对工具参数进行 SHA256 哈希，用于比对参数是否完全相同。"""
        return hashlib.sha256(
            json.dumps(tool_args, sort_keys=True, default=str).encode()
        ).hexdigest()

    async def check(self, tool_name: str, tool_args: dict[str, Any], context: GuardContext) -> GuardResult:
        """检查当前工具调用是否构成循环，必要时阻止执行。"""
        args_hash = self._hash_args(tool_args)

        exact_failures = sum(
            1 for h in context.tool_history
            if h.tool_name == tool_name and h.tool_args_hash == args_hash and not h.success
        )
        if exact_failures >= self._exact_failure_block:
            return GuardResult(
                blocked=True, risk_level="high", code="exact_failure",
                reason=f"Same call '{tool_name}' failed {exact_failures} times",
            )

        same_tool_failures = sum(
            1 for h in context.tool_history
            if h.tool_name == tool_name and not h.success
        )
        if same_tool_failures >= self._same_tool_block:
            return GuardResult(
                blocked=True, risk_level="high", code="same_tool",
                reason=f"Tool '{tool_name}' failed {same_tool_failures} times",
            )

        if tool_name in IDEMPOTENT_TOOLS:
            no_progress = sum(
                1 for h in context.tool_history
                if h.tool_name == tool_name and h.result_hash == args_hash
            )
            if no_progress >= self._no_progress_block:
                return GuardResult(
                    blocked=True, risk_level="medium", code="no_progress",
                    reason=f"Idempotent tool '{tool_name}' made no progress for {no_progress} calls",
                )

        return GuardResult()