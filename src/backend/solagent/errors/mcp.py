"""MCP（Model Context Protocol）服务器相关的异常类型。"""

from solagent.errors.base import AgentError


class MCPError(AgentError):
    """MCP 相关错误的基类。"""


class MCPConnectionError(MCPError):
    """与 MCP 服务器的连接失败。

    Attributes:
        server_name: 目标 MCP 服务器名称。
    """

    def __init__(self, server_name: str, message: str):
        super().__init__(f"MCP connection to '{server_name}' failed: {message}")
        self.server_name = server_name