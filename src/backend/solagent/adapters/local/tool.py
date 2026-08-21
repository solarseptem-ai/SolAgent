"""本地工具适配器：将 ToolRegistry 包装为 ToolPort 的本地实现。

在同进程内直接从工具注册表中查找并执行工具调用，
参数会自动反序列化为工具定义的 Pydantic 模型实例。
"""
from __future__ import annotations

from solagent.agents.tools.registry import ToolRegistry
from solagent.schema.tools import ToolCall, ToolCallContext, ToolResult


class LocalToolAdapter:
    """本地工具端口适配器。

    属性:
        _tools: 本地 ToolRegistry 实例，包含所有已注册的工具。
    """

    def __init__(self, tools: ToolRegistry):
        self._tools = tools

    async def invoke(self, call: ToolCall) -> ToolResult:
        """根据 ToolCall 查找对应工具并执行。

        参数:
            call: 包含工具名称、参数和调用 ID 的 ToolCall。

        返回:
            工具执行后的 ToolResult。
        """
        tool = self._tools.get(call.name)
        # 将参数字典反序列化为工具定义的 Pydantic 模型
        params = tool.params_model(**call.arguments)
        ctx = ToolCallContext(tool_call_id=call.id)
        return await tool.execute(params, ctx)

    async def list_tools(self) -> list[str]:
        """返回当前注册表中所有工具的名称列表。"""
        return self._tools.list()