"""
沙箱管理器模块。

统一管理多个沙箱后端实例，支持注册、容量限制（FIFO 淘汰）和代理执行。
当沙箱数量超过上限时，自动暂停最早创建的沙箱以释放资源。
"""
from __future__ import annotations

import asyncio
import logging

_logger = logging.getLogger(__name__)


class SandboxManager:
    """沙箱管理器，管理多个沙箱后端的注册与生命周期。

    Attributes:
        _providers: 沙箱名称到后端实例的映射。
        _creation_order: 沙箱创建顺序列表，用于 FIFO 淘汰。
        max_sandboxes: 允许同时存在的最大沙箱数量。
    """

    def __init__(self, max_sandboxes: int = 5):
        self._providers: dict[str, object] = {}
        self._creation_order: list[str] = []
        self.max_sandboxes = max_sandboxes

    def register(self, name: str, provider) -> None:
        """注册一个沙箱后端。

        Args:
            name: 沙箱名称。
            provider: 沙箱后端实例，需具有 execute / start / stop 等方法。
        """
        self._providers[name] = provider
        if name not in self._creation_order:
            self._creation_order.append(name)

    def get(self, name: str):
        """按名称获取已注册的沙箱后端。"""
        return self._providers.get(name)

    def pause_old_sandboxes(self) -> list[str]:
        """当沙箱数量超过上限时，按 FIFO 策略暂停最早的沙箱。

        Returns:
            被暂停的沙箱名称列表。
        """
        paused = []
        while len(self._creation_order) >= self.max_sandboxes:
            oldest = self._creation_order.pop(0)
            provider = self._providers.get(oldest)
            if provider and hasattr(provider, 'stop'):
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(provider.stop())
                except RuntimeError:
                    pass
                paused.append(oldest)
            self._providers.pop(oldest, None)
        return paused

    async def execute(self, provider_name: str, code, language: str = "python", timeout: float = 30.0):
        """通过指定名称的沙箱后端执行代码。

        Args:
            provider_name: 沙箱后端名称。
            code: 要执行的代码。
            language: 编程语言，默认 "python"。
            timeout: 执行超时时间（秒）。

        Returns:
            执行结果。

        Raises:
            ValueError: 指定名称的沙箱后端不存在时。
        """
        provider = self._providers.get(provider_name)
        if not provider:
            raise ValueError(f"Sandbox provider '{provider_name}' not found")
        return await provider.execute(code, language=language, timeout=timeout)