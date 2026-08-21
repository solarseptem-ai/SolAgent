"""Composable termination conditions. Reference: AutoGen TerminationCondition system."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from solagent.agents.base import AgentContext, AgentStep


class TerminatedError(Exception):
    """Raised when a termination condition triggers."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class TerminationCondition(Protocol):
    """协议：实现此协议即可接入 Agent 执行循环。"""

    async def should_stop(self, ctx: AgentContext, step: AgentStep) -> bool: ...

    def reset(self) -> None: ...


class MaxIterationsTermination:
    def __init__(self, max_iterations: int):
        self._max = max_iterations
        self._count = 0

    async def should_stop(self, ctx: AgentContext, step: AgentStep) -> bool:
        self._count = step.iteration
        return self._count >= self._max

    def reset(self) -> None:
        self._count = 0


class TimeoutTermination:
    def __init__(self, timeout_seconds: float):
        self._timeout = timeout_seconds
        self._start: float = 0.0

    async def should_stop(self, ctx: AgentContext, step: AgentStep) -> bool:
        if self._start == 0.0:
            self._start = time.monotonic()
        return time.monotonic() - self._start >= self._timeout

    def reset(self) -> None:
        self._start = 0.0


class TextMentionTermination:
    def __init__(self, texts: list[str]):
        self._texts = texts

    async def should_stop(self, ctx: AgentContext, step: AgentStep) -> bool:
        content_lower = (step.content or "").lower()
        return any(t.lower() in content_lower for t in self._texts)

    def reset(self) -> None:
        pass


class TokenBudgetTermination:
    def __init__(self, max_total_tokens: int):
        self._max = max_total_tokens

    async def should_stop(self, ctx: AgentContext, step: AgentStep) -> bool:
        return ctx.total_usage.total_tokens >= self._max

    def reset(self) -> None:
        pass


class ExternalTermination:
    def __init__(self):
        self._terminated = False

    def set_terminated(self) -> None:
        self._terminated = True

    async def should_stop(self, ctx: AgentContext, step: AgentStep) -> bool:
        return self._terminated

    def reset(self) -> None:
        self._terminated = False


class CompositeTermination:
    def __init__(self, conditions: list[TerminationCondition], mode: Literal["any", "all"] = "any"):
        self._conditions = conditions
        self._mode = mode

    async def should_stop(self, ctx: AgentContext, step: AgentStep) -> bool:
        if not self._conditions:
            return False
        results = [await c.should_stop(ctx, step) for c in self._conditions]
        return all(results) if self._mode == "all" else any(results)

    def reset(self) -> None:
        for c in self._conditions:
            c.reset()