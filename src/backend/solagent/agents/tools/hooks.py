"""Tool hooks system. 对标 grok-build hooks：before/after/error 三段式。"""
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from solagent.schema.messages import ToolCallBlock
from solagent.schema.tools import ToolResult


@dataclass
class BeforeResult:
    allowed: bool = True
    reason: str = ""
    modified_params: Any = None


@dataclass
class ToolHooks:
    before: list[Callable[..., Awaitable[BeforeResult]]] = field(default_factory=list)
    after: list[Callable[..., Awaitable[ToolResult]]] = field(default_factory=list)
    on_error: list[Callable[..., Awaitable[ToolResult | None]]] = field(default_factory=list)

    def add_before(self, hook):
        self.before.append(hook)

    def add_after(self, hook):
        self.after.append(hook)

    def add_error(self, hook):
        self.on_error.append(hook)