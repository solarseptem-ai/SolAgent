"""
MCP 会话池模块。

管理多个 MCP 服务器客户端实例的生命周期，支持复用已有连接、按需创建和批量断开。
"""
from __future__ import annotations

from solagent.mcp.client import MCPClient, MCPServerConfig


class MCPSessionPool:
    """MCP 会话池，按服务器名称复用客户端连接。

    Attributes:
        _clients: 服务器名称到 MCPClient 的映射字典。
    """

    def __init__(self):
        self._clients: dict[str, MCPClient] = {}

    def get_or_create(self, config: MCPServerConfig) -> MCPClient:
        """获取已有客户端，若不存在则根据配置创建并缓存。

        Args:
            config: MCP 服务器配置。

        Returns:
            MCPClient 实例。
        """
        if config.name in self._clients:
            return self._clients[config.name]
        client = MCPClient(config)
        self._clients[config.name] = client
        return client

    def get(self, name: str) -> MCPClient | None:
        """按名称获取已缓存的客户端。"""
        return self._clients.get(name)

    def remove(self, name: str) -> None:
        """移除指定名称的客户端缓存。"""
        self._clients.pop(name, None)

    async def disconnect_all(self) -> None:
        """断开所有已缓存的客户端连接并清空池。"""
        for client in self._clients.values():
            await client.disconnect()
        self._clients.clear()