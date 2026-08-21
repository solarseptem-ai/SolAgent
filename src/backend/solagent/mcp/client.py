"""
MCP 客户端模块。

实现基于 JSON-RPC 2.0 协议的 MCP 客户端基类，包含请求构建、响应解析、
会话初始化和基础工具调用能力。具体传输（stdio / SSE）由子类实现。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MCPServerConfig:
    """MCP 服务器配置。

    Attributes:
        name: 服务器名称标识。
        transport: 传输方式，默认 "stdio"，可选 "sse"。
        command: 启动命令（stdio 模式下使用）。
        args: 启动参数列表。
        url: 服务器 URL（sse 模式下使用）。
        env: 环境变量字典。
        headers: HTTP 请求头字典（sse 模式下使用）。
    """

    name: str
    transport: str = "stdio"
    command: str = ""
    args: list[str] = field(default_factory=list)
    url: str = ""
    env: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)


class MCPClient:
    """MCP 客户端基类。

    管理连接状态、会话 ID、请求 ID 自增，提供 JSON-RPC 请求构建和响应解析。
    _send_request 和 _send_notification 需由子类实现。

    Attributes:
        config: MCP 服务器配置。
        _connected: 是否已连接。
        _session_id: 当前会话 ID。
        _request_id: 请求 ID 计数器。
    """

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self._connected = False
        self._session_id: str | None = None
        self._request_id = 0

    @property
    def is_connected(self) -> bool:
        """客户端是否已连接。"""
        return self._connected

    def _next_id(self) -> int:
        """生成下一个请求 ID。"""
        self._request_id += 1
        return self._request_id

    def _build_request(self, method: str, params: dict) -> dict:
        """构建 JSON-RPC 请求对象。"""
        return {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params,
        }

    def _build_notification(self, method: str, params: dict | None = None) -> dict:
        """构建 JSON-RPC 通知对象（无 id）。"""
        return {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        }

    def _parse_response(self, response: dict) -> dict:
        """解析 JSON-RPC 响应，若包含 error 则抛出 MCPError。

        Args:
            response: 原始响应字典。

        Returns:
            响应中的 result 字段。

        Raises:
            MCPError: 响应中包含错误信息时。
        """
        if "error" in response:
            error = response["error"]
            raise MCPError(error.get("message", "Unknown MCP error"), code=error.get("code", -1))
        return response.get("result", {})

    async def connect(self) -> None:
        """建立连接。子类可覆盖以添加实际连接逻辑。"""
        self._connected = True

    async def disconnect(self) -> None:
        """断开连接并清理会话。"""
        self._connected = False
        self._session_id = None

    async def _initialize(self) -> None:
        """发送 initialize 请求并通知 initialized，完成 MCP 握手。"""
        request = self._build_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "solagent", "version": "0.1.0"},
        })
        response = await self._send_request(request)
        self._parse_response(response)
        notification = self._build_notification("notifications/initialized")
        await self._send_notification(notification)

    async def _send_request(self, request: dict) -> dict:
        """发送 JSON-RPC 请求，由子类实现具体传输逻辑。"""
        raise NotImplementedError

    async def _send_notification(self, notification: dict) -> None:
        """发送 JSON-RPC 通知，由子类实现具体传输逻辑。"""
        raise NotImplementedError

    async def list_tools(self) -> list[dict]:
        """获取 MCP 服务器上可用的工具列表。

        若未初始化会话，则自动发起 initialize 握手。

        Returns:
            工具定义字典列表。
        """
        if not self._session_id:
            if self._connected:
                await self._initialize()
            else:
                return []
        request = self._build_request("tools/list", {})
        response = await self._send_request(request)
        result = self._parse_response(response)
        return result.get("tools", [])

    async def call_tool(self, name: str, arguments: dict):
        """调用指定的 MCP 工具。

        若未初始化会话，则自动发起 initialize 握手。

        Args:
            name: 工具名称。
            arguments: 工具参数字典。

        Returns:
            工具执行结果。
        """
        if not self._session_id:
            if self._connected:
                await self._initialize()
            else:
                return f"MCP tool '{name}' called with {arguments}"
        request = self._build_request("tools/call", {"name": name, "arguments": arguments})
        response = await self._send_request(request)
        return self._parse_response(response)


class MCPError(Exception):
    """MCP 协议错误异常。

    Attributes:
        code: 错误代码，默认 -1。
    """

    def __init__(self, message: str, code: int = -1):
        super().__init__(message)
        self.code = code