"""
MCP 工具适配器模块。

将 MCP 服务器暴露的工具封装为 SolAgent 内部可识别的 BaseTool，
使 Agent 能够像调用本地工具一样调用远程 MCP 工具。
"""

import logging

from solagent.agents.tools.base import BaseTool

_logger = logging.getLogger(__name__)
from solagent.schema.messages import ToolCallBlock
from solagent.schema.tools import ToolParameter, ToolResult


class MCPToolAdapter(BaseTool):
    """MCP 工具适配器，将远程 MCP 工具代理为本地工具接口。

    Attributes:
        _client: MCP 客户端实例，用于发起 JSON-RPC 调用。
        _tool_name: 工具在 MCP 服务器上的原始名称。
        _description: 工具描述。
        _parameters: 工具参数列表。
    """

    def __init__(self, client, tool_name: str, description: str = "", parameters: list[ToolParameter] | None = None):
        self._client = client
        self._tool_name = tool_name
        self._description = description
        self._parameters = parameters or []

    @property
    def name(self) -> str:
        """工具名称。"""
        return self._tool_name

    @property
    def description(self) -> str:
        """工具描述。"""
        return self._description

    @property
    def parameters(self) -> list[ToolParameter]:
        """工具参数定义列表。"""
        return self._parameters

    async def execute(self, call: ToolCallBlock) -> ToolResult:
        """执行 MCP 工具调用。

        Args:
            call: 工具调用块，包含参数。

        Returns:
            工具执行结果；若调用失败则返回包含错误信息的结果。
        """
        try:
            result = await self._client.call_tool(self._tool_name, call.arguments)
            return ToolResult(call_id=call.id, name=self.name, output=result)
        except Exception as e:
            _logger.warning("MCP adapter failed", exc_info=True)
            return ToolResult(call_id=call.id, name=self.name, output=str(e), is_error=True)