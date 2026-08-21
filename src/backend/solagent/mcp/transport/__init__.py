"""
MCP 传输层聚合导出。

提供两种 MCP 通信传输实现：SSE（Server-Sent Events）和 Stdio（标准输入输出）。
"""
from solagent.mcp.transport.sse import SSETransport
from solagent.mcp.transport.stdio import StdioTransport

__all__ = ["SSETransport", "StdioTransport"]