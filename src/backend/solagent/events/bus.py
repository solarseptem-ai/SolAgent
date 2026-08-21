"""发布/订阅事件总线，支持通配符订阅、背压控制和会话追踪。"""

import asyncio
import fnmatch
import logging
import re
from collections.abc import Awaitable, Callable

from solagent.events.types import AgentEvent, AgentEventType

_logger = logging.getLogger(__name__)

EventListener = Callable[[AgentEvent], Awaitable[None]]  # 事件监听器类型别名

_WILDCARD_PATTERN = re.compile(r"[*?\[\]]")


class EventBus:
    """发布/订阅事件总线，支持通配符订阅、背压控制和会话追踪。

    功能特性：
        - 精确类型订阅：bus.subscribe(AgentEventType.AGENT_START, handler)
        - 通配符订阅：bus.subscribe("llm.*", handler) 或 bus.subscribe("tool.*", handler)
        - 即发即弃：bus.emit(event) —— 非阻塞，带背压保护
        - 可等待发送：await bus.emit_async(event) —— 阻塞直到所有监听器完成
        - 会话追踪：bus.set_session_id(id) —— 自动为发出的事件填充 session_id
    """

    def __init__(self, max_pending: int = 100):
        """初始化事件总线。

        Args:
            max_pending: 最大并发待处理事件数，超出则丢弃事件。
        """
        self._listeners: dict[AgentEventType, list[EventListener]] = {}
        self._wildcard_listeners: list[tuple[re.Pattern, EventListener]] = []
        self._session_id: str = ""
        self._max_pending = max_pending
        self._pending: int = 0

    def set_session_id(self, session_id: str) -> None:
        """设置当前会话 ID，后续发出的事件会自动填充该值。"""
        self._session_id = session_id

    def subscribe(self, event_type: AgentEventType | str, listener: EventListener) -> None:
        """订阅指定类型的事件。

        Args:
            event_type: 事件类型枚举或通配符字符串（如 "llm.*"）。
            listener: 异步事件处理函数。
        """
        if isinstance(event_type, str):
            pattern = re.compile(fnmatch.translate(event_type))
            self._wildcard_listeners.append((pattern, listener))
        else:
            if event_type not in self._listeners:
                self._listeners[event_type] = []
            self._listeners[event_type].append(listener)

    def unsubscribe(self, event_type: AgentEventType | str, listener: EventListener) -> None:
        """取消订阅指定的事件监听器。"""
        if isinstance(event_type, str):
            pattern = re.compile(fnmatch.translate(event_type))
            self._wildcard_listeners = [
                (p, l) for p, l in self._wildcard_listeners
                if not (p.pattern == pattern.pattern and l is listener)
            ]
        else:
            if event_type in self._listeners:
                self._listeners[event_type] = [l for l in self._listeners[event_type] if l is not listener]

    def emit(self, event: AgentEvent) -> None:
        """即发即弃方式触发事件（非阻塞）。

        若当前待处理事件数超过 max_pending，则丢弃该事件并记录警告。
        """
        if self._pending >= self._max_pending:
            _logger.warning("EventBus backpressure: dropping event %s (pending=%d)", event.event_type, self._pending)
            return
        self._pending += 1
        # 若事件未指定 session_id 且总线已设置，则自动填充
        if not event.session_id and self._session_id:
            event = event.model_copy(update={"session_id": self._session_id})
        asyncio.create_task(self._safe_invoke(event))

    async def emit_async(self, event: AgentEvent) -> None:
        """同步方式触发事件（阻塞直到所有监听器完成）。"""
        if not event.session_id and self._session_id:
            event = event.model_copy(update={"session_id": self._session_id})
        await self._safe_invoke(event)

    async def _safe_invoke(self, event: AgentEvent) -> None:
        """安全调用所有匹配的监听器，捕获异常避免一个监听器失败影响其他监听器。"""
        try:
            exact_listeners = self._listeners.get(event.event_type, [])
            for listener in exact_listeners:
                try:
                    await listener(event)
                except Exception:
                    _logger.debug("Event listener error for %s", event.event_type, exc_info=True)

            for pattern, listener in self._wildcard_listeners:
                if pattern.match(event.event_type.value):
                    try:
                        await listener(event)
                    except Exception:
                        _logger.debug("Wildcard listener error for %s", event.event_type, exc_info=True)
        finally:
            self._pending = max(0, self._pending - 1)

    def clear(self) -> None:
        """清空所有监听器和待处理计数。"""
        self._listeners.clear()
        self._wildcard_listeners.clear()
        self._pending = 0