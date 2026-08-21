"""
防护规则注册中心模块。

管理输入和输出两类 Guardrail 规则的注册与批量执行。
当规则触发时，可通过 EventBus 发出 GUARDRAIL_TRIGGERED 事件。
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from solagent.events.types import AgentEventType

if TYPE_CHECKING:
    from solagent.events.bus import EventBus

_logger = logging.getLogger(__name__)


class GuardrailRegistry:
    """防护规则注册中心。

    分别维护输入和输出两类规则列表，支持批量审查并上报触发事件。

    Attributes:
        _input_guardrails: 输入审查规则列表。
        _output_guardrails: 输出审查规则列表。
        _event_bus: 可选的事件总线，用于上报规则触发事件。
    """

    def __init__(self, event_bus: EventBus | None = None):
        self._input_guardrails: list = []
        self._output_guardrails: list = []
        self._event_bus = event_bus

    def register_input(self, guardrail) -> None:
        """注册一个输入防护规则。"""
        self._input_guardrails.append(guardrail)

    def register_output(self, guardrail) -> None:
        """注册一个输出防护规则。"""
        self._output_guardrails.append(guardrail)

    async def check_input(self, text: str) -> list:
        """按顺序执行所有输入防护规则。

        Args:
            text: 用户输入文本。

        Returns:
            各规则的审查结果列表。
        """
        results = []
        for g in self._input_guardrails:
            result = await g.check_input(text)
            results.append(result)
            # 若规则拒绝且存在事件总线，则上报 GUARDRAIL_TRIGGERED 事件
            if not result.allowed and self._event_bus:
                from solagent.events.types import AgentEvent as _AgentEvent
                self._event_bus.emit(_AgentEvent(
                    event_type=AgentEventType.GUARDRAIL_TRIGGERED,
                    data={"stage": "input", "guardrail": type(g).__name__,
                          "reason": result.reason, "text": text[:200]},
                ))
        return results

    async def check_output(self, text: str) -> list:
        """按顺序执行所有输出防护规则。

        Args:
            text: 模型输出文本。

        Returns:
            各规则的审查结果列表。
        """
        results = []
        for g in self._output_guardrails:
            result = await g.check_output(text)
            results.append(result)
            # 若规则拒绝且存在事件总线，则上报 GUARDRAIL_TRIGGERED 事件
            if not result.allowed and self._event_bus:
                from solagent.events.types import AgentEvent as _AgentEvent
                self._event_bus.emit(_AgentEvent(
                    event_type=AgentEventType.GUARDRAIL_TRIGGERED,
                    data={"stage": "output", "guardrail": type(g).__name__,
                          "reason": result.reason, "text": text[:200]},
                ))
        return results