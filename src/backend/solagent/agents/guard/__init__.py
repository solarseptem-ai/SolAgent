"""Tool guard system — 5-layer security for tool execution."""
from solagent.agents.guard.base import CompositeGuard, Guard, GuardContext, GuardResult, ToolHistoryEntry
from solagent.agents.guard.bash_scanner import BashCommandScanner
from solagent.agents.guard.file_safety import FileSafetyGuard
from solagent.agents.guard.loop_detector import IDEMPOTENT_TOOLS, MUTATING_TOOLS, LoopDetector
from solagent.agents.guard.rate_guard import RateGuard
from solagent.agents.guard.ssl_guard import SSLGuard

__all__ = [
    "Guard", "GuardResult", "GuardContext", "ToolHistoryEntry", "CompositeGuard",
    "BashCommandScanner", "FileSafetyGuard", "LoopDetector", "RateGuard", "SSLGuard",
    "IDEMPOTENT_TOOLS", "MUTATING_TOOLS",
]