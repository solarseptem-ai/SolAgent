"""MCP extension. 对标 grok-build MCP adapter：透明转换。"""
import logging

_logger = logging.getLogger(__name__)


class MCPExtension:
    name = "mcp"
    version = "1.0"

    def __init__(self, mcp_manager):
        self._mcp = mcp_manager

    async def activate(self, ctx) -> None:
        await self._mcp.connect_all()
        await self._mcp.discover()
        for adapter in self._mcp.get_tools():
            ctx.api.register_tool(adapter)
            _logger.info("MCP extension: registered tool '%s'", adapter.name)

    async def deactivate(self) -> None:
        await self._mcp.disconnect_all()
