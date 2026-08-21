"""
事件端口 — Agent 事件发布与订阅的抽象接口。

支持按模式匹配订阅事件，以及向事件总线发布事件。
"""
from collections.abc import Awaitable, Callable
from typing import Protocol

from solagent.events.types import AgentEvent


class EventPort(Protocol):
    """事件总线协议，提供发布/订阅能力。"""

    async def publish(self, event: AgentEvent) -> None:
        """发布一个 Agent 事件到事件总线。

        Args:
            event: 要发布的事件对象。
        """
        ...

    async def subscribe(self, pattern: str, handler: Callable[[AgentEvent], Awaitable[None]]) -> None:
        """订阅匹配指定模式的事件。

        Args:
            pattern: 事件类型匹配模式，如 "tool.call.*"。
            handler: 事件处理回调函数。
        """
        ...