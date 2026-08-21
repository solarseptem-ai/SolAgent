"""
MCP SSE 传输模块。

基于 Server-Sent Events 的 MCP 传输实现，通过 HTTP SSE 建立长连接，
接收服务端推送的消息端点，然后通过 POST 发送 JSON-RPC 请求。
"""
from __future__ import annotations

import asyncio
import json
import logging

import httpx

from solagent.mcp.client import MCPServerConfig

_logger = logging.getLogger(__name__)


class SSETransport:
    """MCP SSE 传输层。

    先通过 SSE 连接获取消息端点，然后通过 HTTP POST 发送请求和通知。

    Attributes:
        _config: MCP 服务器配置。
        _timeout: HTTP 请求超时时间。
        _client: httpx 异步客户端。
        _endpoint: SSE 握手后获取到的 POST 端点 URL。
        _pending: 待处理请求的字典（id -> asyncio.Future）。
        _reader_task: SSE 读取任务。
        _session_id: 会话 ID。
    """

    def __init__(self, config: MCPServerConfig, timeout: float = 30.0):
        self._config = config
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._endpoint: str | None = None
        self._pending: dict[int, asyncio.Future] = {}
        self._reader_task: asyncio.Task | None = None
        self._session_id: str | None = None

    async def start(self) -> None:
        """启动 SSE 传输，连接服务器并解析消息端点。

        通过 GET 请求建立 SSE 连接，从 data 行中提取 POST 端点。
        若未提取到端点，则根据 URL 模式自动推断。
        """
        self._client = httpx.AsyncClient(timeout=self._timeout, headers=self._config.headers)
        try:
            sse_response = await self._client.get(self._config.url)
            sse_response.raise_for_status()
            self._endpoint = None
            # 逐行读取 SSE 数据，寻找端点信息
            async for line in sse_response.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data.startswith("http"):
                        self._endpoint = data
                        break
                    if "endpoint" in data:
                        try:
                            self._endpoint = json.loads(data).get("endpoint", data)
                        except json.JSONDecodeError:
                            pass
                        break
            # 若服务端未提供端点，则基于 URL 自动推断
            if not self._endpoint:
                parts = self._config.url.split("/sse")
                self._endpoint = parts[0] + "/messages" if len(parts) > 1 else self._config.url
        except Exception:
            if self._client:
                await self._client.aclose()
            raise

    async def stop(self) -> None:
        """停止 SSE 传输，取消读取任务并关闭客户端。"""
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self._client:
            await self._client.aclose()
            self._client = None

    async def send_request(self, request: dict) -> dict:
        """通过 POST 发送 JSON-RPC 请求并返回响应。

        Args:
            request: JSON-RPC 请求字典。

        Returns:
            JSON-RPC 响应字典。

        Raises:
            RuntimeError: 传输未启动或响应包含错误时。
        """
        if not self._client or not self._endpoint:
            raise RuntimeError("Transport not started")
        response = await self._client.post(
            self._endpoint,
            json=request,
            params={"session_id": self._session_id} if self._session_id else None,
        )
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            error = data["error"]
            raise RuntimeError(f"MCP error: {error.get('message', 'Unknown')}")
        return data

    async def send_notification(self, notification: dict) -> None:
        """通过 POST 发送 JSON-RPC 通知（无需响应）。

        Args:
            notification: JSON-RPC 通知字典。

        Raises:
            RuntimeError: 传输未启动时。
        """
        if not self._client or not self._endpoint:
            raise RuntimeError("Transport not started")
        await self._client.post(
            self._endpoint,
            json=notification,
            params={"session_id": self._session_id} if self._session_id else None,
        )