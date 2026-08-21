"""工具调用速率限制守卫。

对高频工具（如 shell、write、web_search 等）按名称实施滑动窗口速率限制，
防止 Agent 在短时间内过度调用某一工具导致资源耗尽或触发外部 API 限流。
"""

from __future__ import annotations

import time
from typing import Any, ClassVar

from solagent.agents.guard.base import GuardContext, GuardResult

# 默认各工具的每分钟调用上限
DEFAULT_TOOL_RATE_LIMITS: ClassVar[dict[str, int]] = {
    "shell": 30,
    "write": 60,
    "edit": 60,
    "apply_patch": 30,
    "read": 300,
    "ls": 300,
    "glob": 300,
    "grep": 300,
    "web_search": 20,
    "web_fetch": 20,
}


class RateGuard:
    """按工具名称进行滑动窗口速率限制的守卫。

    属性:
        limits: 工具名到每分钟最大调用次数的映射。
        counters: 每个工具最近调用时间戳的滑动窗口列表。
    """

    def __init__(self, limits: dict[str, int] | None = None):
        """初始化速率限制守卫。

        参数:
            limits: 自定义速率限制表；None 则使用默认配置。
        """
        self._limits = limits or DEFAULT_TOOL_RATE_LIMITS
        self._counters: dict[str, list[float]] = {}

    async def check(self, tool_name: str, tool_args: dict[str, Any], context: GuardContext) -> GuardResult:
        """检查当前工具调用是否超出速率限制，超限则阻止执行。"""
        limit = self._limits.get(tool_name)
        if limit is None:
            return GuardResult()

        now = time.monotonic()
        if tool_name not in self._counters:
            self._counters[tool_name] = []

        window = 60.0
        self._counters[tool_name] = [t for t in self._counters[tool_name] if now - t < window]
        self._counters[tool_name].append(now)

        if len(self._counters[tool_name]) > limit:
            return GuardResult(
                blocked=True, risk_level="medium", code="rate_limited",
                reason=f"Tool '{tool_name}' rate limited ({limit}/min)",
            )

        return GuardResult()