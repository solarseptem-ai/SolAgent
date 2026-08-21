"""本地事件适配器：将 EventBus 包装为 EventPort 的本地实现。

在单进程内直接通过内存中的 EventBus 分发事件，同时维护一份本地订阅列表，
支持基于通配符模式的事件匹配与回调。
"""
from __future__ import annotations

import fnmatch
from collections.abc import Awaitable, Callable

from solagent.events.types import AgentEvent
from solagent.events.bus import EventBus


class LocalEventAdapter:
    """本地事件端口适配器。

    属性:
        _bus: 内存中的 EventBus 实例。
        _subscriptions: 本地维护的 (模式, 处理器) 订阅列表。
    """

    def __init__(self, bus: EventBus):
        self._bus = bus
        self._subscriptions: list[tuple[str, Callable[[AgentEvent], Awaitable[None]]]] = []

    async def publish(self, event: AgentEvent) -> None:
        """发布事件：先通过 EventBus 广播，再触发本地匹配的订阅处理器。

        参数:
            event: 要发布的 AgentEvent。
        """
        self._bus.emit(event)
        for pattern, handler in self._subscriptions:
            if fnmatch.fnmatch(event.topic, pattern):
                await handler(event)

    async def subscribe(self, pattern: str, handler: Callable[[AgentEvent], Awaitable[None]]) -> None:
        """注册一个基于通配符模式的事件处理器。

        参数:
            pattern: 通配符匹配模式，例如 "agent.*.done"。
            handler: 异步事件处理回调。
        """
        self._subscriptions.append((pattern, handler))