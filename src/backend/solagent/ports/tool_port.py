"""
工具调用端口 — 本地与远程工具执行的抽象接口。

封装工具的具体调用方式，使 Agent 无需关心工具的实现位置。
"""
from typing import Protocol

from solagent.schema.tools import ToolCall, ToolResult


class ToolPort(Protocol):
    """工具调用协议，定义工具执行和列举的接口。"""

    async def invoke(self, call: ToolCall) -> ToolResult:
        """调用指定工具。

        Args:
            call: 工具调用描述，包含工具名和参数。

        Returns:
            工具执行结果。
        """
        ...

    async def list_tools(self) -> list[str]:
        """列出当前可用的工具名称列表。"""
        ...