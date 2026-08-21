"""
MCP Stdio 传输模块。

基于子进程标准输入输出的 MCP 传输实现，通过启动外部命令创建子进程，
使用 JSON Lines 协议在 stdin/stdout 上进行双向通信。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os

from solagent.mcp.client import MCPServerConfig

_logger = logging.getLogger(__name__)


class StdioTransport:
    """MCP Stdio 传输层。

    启动子进程并通过 stdin 发送 JSON-RPC 消息，从 stdout 读取响应。

    Attributes:
        _config: MCP 服务器配置（command + args 用于启动子进程）。
        _timeout: 请求等待超时时间。
        _process: 子进程对象。
        _pending: 待处理请求的字典（id -> asyncio.Future）。
        _reader_task: stdout 读取循环任务。
    """

    def __init__(self, config: MCPServerConfig, timeout: float = 30.0):
        self._config = config
        self._timeout = timeout
        self._process: asyncio.subprocess.Process | None = None
        self._pending: dict[int, asyncio.Future] = {}
        self._reader_task: asyncio.Task | None = None

    async def start(self) -> None:
        """启动子进程并创建 stdout 读取任务。"""
        self._process = await asyncio.create_subprocess_exec(
            self._config.command,
            *self._config.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, **self._config.env},
        )
        self._reader_task = asyncio.create_task(self._read_loop())

    async def stop(self) -> None:
        """停止传输，取消读取任务并终止子进程。"""
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self._process:
            self._process.stdin.close()
            try:
                self._process.terminate()
            except ProcessLookupError:
                pass
            await self._process.wait()

    async def send_request(self, request: dict) -> dict:
        """发送 JSON-RPC 请求并等待响应。

        Args:
            request: JSON-RPC 请求字典，必须包含 "id" 字段。

        Returns:
            JSON-RPC 响应字典。

        Raises:
            RuntimeError: 传输未启动或子进程已退出时。
        """
        if not self._process or self._process.returncode is not None:
            raise RuntimeError("Transport not started or process exited")
        request_id = request["id"]
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[request_id] = future
        try:
            line = json.dumps(request) + "\n"
            self._process.stdin.write(line.encode())
            await self._process.stdin.drain()
            return await asyncio.wait_for(future, timeout=self._timeout)
        finally:
            self._pending.pop(request_id, None)

    async def send_notification(self, notification: dict) -> None:
        """发送 JSON-RPC 通知（无需等待响应）。

        Args:
            notification: JSON-RPC 通知字典。

        Raises:
            RuntimeError: 传输未启动或子进程已退出时。
        """
        if not self._process or self._process.returncode is not None:
            raise RuntimeError("Transport not started or process exited")
        line = json.dumps(notification) + "\n"
        self._process.stdin.write(line.encode())
        await self._process.stdin.drain()

    async def _read_loop(self) -> None:
        """后台读取循环，从 stdout 逐行解析 JSON-RPC 响应并唤醒对应的 Future。"""
        try:
            while self._process and self._process.stdout and not self._process.stdout.at_eof():
                line = await self._process.stdout.readline()
                if not line:
                    break
                try:
                    response = json.loads(line.decode().strip())
                    request_id = response.get("id")
                    # 将响应结果设置到对应的 Future，唤醒等待方
                    if request_id is not None and request_id in self._pending:
                        self._pending[request_id].set_result(response)
                except json.JSONDecodeError as e:
                    _logger.warning("Failed to parse JSON-RPC response: %s", e)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            _logger.warning("MCP stdio transport failed", exc_info=True)
            _logger.error("Stdio read loop error: %s", e)
            # 读取异常时，将所有挂起的 Future 标记为异常，避免永久等待
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(e)