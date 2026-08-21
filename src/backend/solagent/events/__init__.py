"""SolAgent 事件系统模块。

提供 Agent 运行时的发布/订阅事件总线、事件作用域管理和事件类型定义。
EventBus 支持通配符订阅和背压控制；EventScope 提供基于上下文变量的作用域栈；
AgentEvent 定义了 CloudEvents 兼容的标准事件结构。
"""

from solagent.events.bus import EventBus, EventListener
from solagent.events.scope import EventScope
from solagent.events.types import AgentEvent, AgentEventType

__all__ = [
    "AgentEvent",
    "AgentEventType",
    "EventBus",
    "EventListener",
    "EventScope",
]