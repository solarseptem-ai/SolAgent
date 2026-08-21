"""
MCP 管理器模块。

统一管理多个 MCP 服务器的连接、发现、刷新和熔断。
将 MCP 工具转换为 SolAgent 内部可识别的 MCPToolAdapter，
并支持工具注册、冲突检测和自动重连。
"""
from __future__ import annotations

import asyncio
import logging
import time

from solagent.mcp.adapter import MCPToolAdapter
from solagent.mcp.client import MCPClient, MCPServerConfig
from solagent.mcp.proxy import MCPProxy
from solagent.schema.tools import ToolParameter, ToolParameterType

_logger = logging.getLogger(__name__)

# MCP JSON Schema 类型到 SolAgent ToolParameterType 的映射
_MCP_TYPE_MAP: dict[str, ToolParameterType] = {
    "string": ToolParameterType.STRING,
    "number": ToolParameterType.NUMBER,
    "integer": ToolParameterType.NUMBER,
    "boolean": ToolParameterType.BOOLEAN,
    "object": ToolParameterType.OBJECT,
    "array": ToolParameterType.ARRAY,
}

# 熔断器常量：连续失败 3 次后断开 30 秒
_CIRCUIT_MAX_FAILURES = 3
_CIRCUIT_TIMEOUT_SECONDS = 30.0
# 重连退避常量：指数退避，最大延迟 30 秒，最多重试 5 次
_RECONNECT_BASE_DELAY = 1.0
_RECONNECT_MAX_DELAY = 30.0
_RECONNECT_MAX_RETRIES = 5


def _mcp_schema_to_params(input_schema: dict) -> list[ToolParameter]:
    """将 MCP JSON Schema 的 properties 转换为 ToolParameter 列表。"""
    params = []
    properties = input_schema.get("properties", {})
    required_set = set(input_schema.get("required", []))
    for name, prop in properties.items():
        prop_type = prop.get("type", "string")
        param_type = _MCP_TYPE_MAP.get(prop_type, ToolParameterType.STRING)
        params.append(ToolParameter(
            name=name,
            type=param_type,
            description=prop.get("description", ""),
            required=name in required_set,
            enum=prop.get("enum"),
        ))
    return params


class _CircuitBreaker:
    """单服务器熔断器：连续失败 3 次后熔断 30 秒。

    Attributes:
        _failures: 每个服务器的连续失败次数。
        _opened_at: 熔断开启的时间戳。
    """

    def __init__(self):
        self._failures: dict[str, int] = {}
        self._opened_at: dict[str, float] = {}

    def record_success(self, server_name: str) -> None:
        """记录成功，重置失败计数。"""
        self._failures[server_name] = 0
        self._opened_at.pop(server_name, None)

    def record_failure(self, server_name: str) -> None:
        """记录失败，增加失败计数。"""
        self._failures[server_name] = self._failures.get(server_name, 0) + 1

    def is_open(self, server_name: str) -> bool:
        """检查指定服务器的熔断器是否处于开启状态。

        若连续失败达到阈值，则开启熔断；30 秒后自动恢复半开状态。
        """
        failures = self._failures.get(server_name, 0)
        if failures < _CIRCUIT_MAX_FAILURES:
            return False
        opened = self._opened_at.get(server_name, 0)
        if opened == 0:
            self._opened_at[server_name] = time.monotonic()
            return True
        if time.monotonic() - opened > _CIRCUIT_TIMEOUT_SECONDS:
            self._opened_at.pop(server_name, None)
            self._failures[server_name] = 0
            return False
        return True


class MCPManager:
    """MCP 管理器，统筹多服务器的连接、发现、刷新和熔断保护。

    Attributes:
        _clients: 服务器名称到 MCPClient 的映射。
        _tools: 已发现的 MCPToolAdapter 列表。
        _proxies: 命名空间到 MCPProxy 的映射。
        _circuit: 熔断器实例。
    """

    def __init__(self):
        self._clients: dict[str, MCPClient] = {}
        self._tools: list[MCPToolAdapter] = []
        self._proxies: dict[str, MCPProxy] = {}
        self._circuit = _CircuitBreaker()

    def add_server(self, config: MCPServerConfig) -> MCPClient:
        """添加并返回一个新的 MCP 服务器客户端。

        Args:
            config: MCP 服务器配置。

        Returns:
            创建的 MCPClient 实例。
        """
        client = MCPClient(config)
        self._clients[config.name] = client
        return client

    def get_client(self, name: str) -> MCPClient | None:
        """按名称获取已注册的 MCP 客户端。"""
        return self._clients.get(name)

    def proxy_mount(self, config: MCPServerConfig, namespace: str) -> MCPProxy:
        """挂载一个带命名空间代理的 MCP 服务器。

        Args:
            config: MCP 服务器配置。
            namespace: 命名空间，用于工具名称前缀隔离。

        Returns:
            创建的 MCPProxy 实例。
        """
        proxy = MCPProxy(config, namespace)
        self._proxies[namespace] = proxy
        self.add_server(config)
        return proxy

    def get_proxy(self, namespace: str) -> MCPProxy | None:
        """按命名空间获取代理。"""
        return self._proxies.get(namespace)

    async def connect_all(self) -> None:
        """尝试连接所有已注册的服务器，跳过熔断中的服务器。"""
        for name, client in self._clients.items():
            if self._circuit.is_open(name):
                _logger.warning("MCP server '%s' circuit open, skipping connect", name)
                continue
            await self._reconnect_client(name, client)

    async def _reconnect_client(self, name: str, client: MCPClient) -> None:
        """自动重连，采用指数退避策略。"""
        for attempt in range(_RECONNECT_MAX_RETRIES):
            try:
                await client.connect()
                self._circuit.record_success(name)
                _logger.info("MCP server '%s' connected", name)
                return
            except Exception as e:
                _logger.warning("MCP manager connect failed", exc_info=True)
                self._circuit.record_failure(name)
                if attempt < _RECONNECT_MAX_RETRIES - 1:
                    # 指数退避计算延迟
                    delay = min(_RECONNECT_BASE_DELAY * (2 ** attempt), _RECONNECT_MAX_DELAY)
                    _logger.warning("MCP server '%s' connect failed (attempt %d/%d): %s, retrying in %.1fs",
                                    name, attempt + 1, _RECONNECT_MAX_RETRIES, e, delay)
                    await asyncio.sleep(delay)
                else:
                    _logger.error("MCP server '%s' connect failed after %d attempts: %s",
                                  name, _RECONNECT_MAX_RETRIES, e)

    async def disconnect_all(self) -> None:
        """断开所有已连接的服务器。"""
        for client in self._clients.values():
            try:
                await client.disconnect()
            except Exception:
                _logger.warning("MCP manager disconnect failed", exc_info=True)

    async def discover(self) -> list[MCPToolAdapter]:
        """从所有已连接的 MCP 服务器发现工具。

        熔断保护：跳过连续失败 3 次以上的服务器，30 秒后自动重试。

        Returns:
            已发现的 MCPToolAdapter 列表。
        """
        self._tools = []
        for server_name, client in self._clients.items():
            if self._circuit.is_open(server_name):
                _logger.info("MCP server '%s' circuit open, skipping discovery", server_name)
                continue

            try:
                tools = await client.list_tools()
                self._circuit.record_success(server_name)
            except Exception as e:
                _logger.warning("MCP manager discover failed", exc_info=True)
                self._circuit.record_failure(server_name)
                _logger.warning("MCP server '%s' list_tools failed: %s", server_name, e)
                continue

            for tool_def in tools:
                tool_name = tool_def.get("name", "")
                description = tool_def.get("description", "")
                input_schema = tool_def.get("inputSchema", {})

                # 为工具名称添加服务器前缀，避免不同服务器间冲突
                prefixed_name = f"mcp_{server_name}_{tool_name}"
                params = _mcp_schema_to_params(input_schema)
                adapter = MCPToolAdapter(client, tool_name, description, params)
                adapter._display_name = prefixed_name
                self._tools.append(adapter)
                _logger.info("MCP discovered: %s → %s", prefixed_name, description[:80])

        return self._tools

    async def refresh(self, registry) -> int:
        """回合间刷新：重新发现工具并更新注册表。

        新增的工具会被注册，已失效的工具（服务器已移除）会被注销。

        Args:
            registry: 工具注册表实例。

        Returns:
            新增和移除的工具总数。
        """
        old_names = set()
        for adapter in self._tools:
            display_name = getattr(adapter, "_display_name", adapter.name)
            old_names.add(display_name)

        await self.discover()

        new_names = set()
        for adapter in self._tools:
            display_name = getattr(adapter, "_display_name", adapter.name)
            new_names.add(display_name)

        added = 0
        for adapter in self._tools:
            display_name = getattr(adapter, "_display_name", adapter.name)
            if display_name not in old_names:
                if not registry.has(display_name):
                    registry.register(adapter)
                    adapter._tool_name = display_name
                    added += 1
                    _logger.info("MCP refresh: added tool '%s'", display_name)

        removed = 0
        for name in old_names - new_names:
            if registry.has(name):
                registry.unregister(name)
                removed += 1
                _logger.info("MCP refresh: removed tool '%s'", name)

        return added + removed

    def register_to_registry(self, registry) -> int:
        """将所有已发现的 MCP 工具注册到工具注册表。

        若与内置工具冲突（同名），则优先保留内置工具并跳过 MCP 工具。

        Args:
            registry: 工具注册表实例。

        Returns:
            成功注册的工具数量。
        """
        count = 0
        existing = set(registry.list())
        for adapter in self._tools:
            display_name = getattr(adapter, "_display_name", adapter.name)
            if display_name in existing:
                _logger.info("MCP tool '%s' skipped (conflicts with builtin)", display_name)
                continue
            registry.register(adapter)
            adapter._tool_name = display_name
            count += 1
        return count

    def get_tools(self) -> list[MCPToolAdapter]:
        """获取当前已发现的所有 MCP 工具适配器。"""
        return self._tools