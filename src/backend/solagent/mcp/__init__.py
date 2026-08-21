"""
MCP（Model Context Protocol）模块聚合导出。

提供与外部 MCP 服务器交互的完整能力：客户端、管理器、适配器、代理、
会话池、安全校验和传输层实现。
"""
from solagent.mcp.adapter import MCPToolAdapter
from solagent.mcp.client import MCPClient, MCPError, MCPServerConfig
from solagent.mcp.manager import MCPManager
from solagent.mcp.proxy import MCPProxy
from solagent.mcp.security import validate_mcp_url
from solagent.mcp.session import MCPSessionPool

__all__ = [
    "MCPClient",
    "MCPError",
    "MCPManager",
    "MCPProxy",
    "MCPServerConfig",
    "MCPSessionPool",
    "MCPToolAdapter",
    "validate_mcp_url",
]