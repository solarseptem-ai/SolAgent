"""子代理运行时模块。

管理已注册的 SubagentProvider，并提供将任务委托给子代理执行的能力。
SubagentRun 作为子代理的执行句柄，支持异步获取结果和取消/清理操作。
"""

from __future__ import annotations

import asyncio
import logging

from solagent.cordis import Context
from solagent.subagent.types import SubagentProvider, SubagentResult, SubagentStartRequest

_logger = logging.getLogger(__name__)


class SubagentRun:
    """子代理执行句柄。

    封装一个正在运行的子代理任务及其 Cordis 子上下文，支持等待结果和释放资源。

    属性:
        ctx: 子代理运行时的 Cordis 上下文，用于隔离资源。
    """

    def __init__(self, result: asyncio.Task[SubagentResult], ctx: Context) -> None:
        self._task = result
        self.ctx = ctx

    async def result(self) -> SubagentResult:
        """等待子代理执行完成并返回结果。"""
        return await self._task

    async def dispose(self) -> None:
        """取消子代理任务（如果尚未完成）并释放子上下文资源。"""
        if not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self.ctx.dispose()


class SubagentRuntime:
    """子代理运行时，负责管理和调度已注册的子代理提供者。

    每个 SubagentProvider 以名称注册到 Runtime 中，主 Agent 通过名称选择
    合适的子代理并将任务委托给它执行。子代理运行在独立的 Cordis 子上下文中，
    确保资源隔离和可清理性。
    """

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self._providers: dict[str, SubagentProvider] = {}

    def register(self, provider: SubagentProvider) -> None:
        """注册一个子代理提供者。"""
        self._providers[provider.name] = provider

    def get(self, name: str) -> SubagentProvider | None:
        """按名称获取已注册的子代理提供者。"""
        return self._providers.get(name)

    def list_providers(self) -> list[str]:
        """返回所有已注册提供者的名称列表。"""
        return list(self._providers.keys())

    async def start(self, provider_name: str, request: SubagentStartRequest) -> SubagentRun:
        """启动指定名称的子代理执行一次任务。

        参数:
            provider_name: 要使用的子代理提供者名称。
            request: 子代理启动请求，包含任务描述、人格、工具等信息。

        返回:
            SubagentRun 句柄，可用于获取结果或取消任务。

        异常:
            ValueError: 指定的提供者未注册。
        """
        provider = self._providers.get(provider_name)
        if provider is None:
            raise ValueError(f"subagent provider '{provider_name}' not found. Available: {self.list_providers()}")

        # 创建子上下文并注入当前 Runtime，供子代理内部递归调用
        child = self.ctx.extend()
        child.provide("subagent", self)

        async def _run() -> SubagentResult:
            try:
                return await provider.start(request)
            except Exception as e:
                _logger.warning("subagent %s failed", provider_name, exc_info=True)
                return SubagentResult(error=str(e))

        task = asyncio.ensure_future(_run())
        return SubagentRun(task, child)