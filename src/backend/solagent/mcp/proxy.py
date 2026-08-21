"""
MCP 代理挂载模块。

通过命名空间为 MCP 工具名称添加前缀，实现多服务器工具名称隔离，
防止不同 MCP 服务器的同名工具产生冲突。
"""
from __future__ import annotations

from solagent.mcp.client import MCPServerConfig


class MCPProxy:
    """MCP 代理，为工具名称添加/移除命名空间前缀。

    Attributes:
        upstream: 上游 MCP 服务器配置。
        namespace: 命名空间标识，用于前缀隔离。
    """

    def __init__(self, upstream: MCPServerConfig, namespace: str):
        self.upstream = upstream
        self.namespace = namespace

    def _prefix_tool_name(self, name: str) -> str:
        """为工具名称添加命名空间前缀。

        Args:
            name: 原始工具名称。

        Returns:
            带前缀的工具名称，如 "namespace__tool_name"。
        """
        return f"{self.namespace}__{name}"

    def _strip_prefix(self, name: str) -> str:
        """从工具名称中移除命名空间前缀。

        Args:
            name: 带前缀的工具名称。

        Returns:
            原始工具名称；若未包含前缀则原样返回。
        """
        prefix = f"{self.namespace}__"
        if name.startswith(prefix):
            return name[len(prefix):]
        return name