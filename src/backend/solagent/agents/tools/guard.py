"""Tool guard. Reference: QwenPaw ToolGuard multi-level security (OFF->AUTO->STRICT)."""
from dataclasses import dataclass
from enum import Enum

from solagent.agents.tools.defs import ToolDef
from solagent.schema.messages import ToolCallBlock


class GuardLevel(str, Enum):
    OFF = "off"
    AUTO = "auto"
    STRICT = "strict"


@dataclass
class GuardDecision:
    allowed: bool
    reason: str = ""
    requires_approval: bool = False


class ToolGuard:
    def __init__(self, level: GuardLevel = GuardLevel.AUTO):
        self.level = level
        self._denied_tools: set[str] = set()
        self._allowlisted_tools: set[str] = set()

    def deny(self, tool_name: str) -> None:
        self._denied_tools.add(tool_name)

    def allow(self, tool_name: str) -> None:
        self._allowlisted_tools.add(tool_name)

    def check(self, tool: ToolDef, call: ToolCallBlock) -> GuardDecision:
        if self.level == GuardLevel.OFF:
            return GuardDecision(allowed=True)
        if call.name in self._denied_tools:
            return GuardDecision(allowed=False, reason=f"Tool '{call.name}' is denied")
        if call.name in self._allowlisted_tools:
            return GuardDecision(allowed=True)
        if self.level == GuardLevel.STRICT:
            return GuardDecision(allowed=False, reason=f"Tool '{call.name}' not in allowlist (strict mode)")
        return GuardDecision(allowed=True)