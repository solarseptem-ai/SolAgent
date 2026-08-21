"""Permission engine. Reference: AgentScope permission_engine.py (729 lines) — 5 modes + per-tool rules."""
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class PermissionMode(str, Enum):
    """Reference: AgentScope PermissionMode — 5 modes."""
    DEFAULT = "default"        # Ask for every action unless explicitly allowed
    ACCEPT_EDITS = "accept_edits"  # Auto-allow file edits within workspace
    EXPLORE = "explore"        # Read-only, deny any modifications
    BYPASS = "bypass"          # Skip all permission checks (sandbox)
    DONT_ASK = "dont_ask"      # Convert all ASK to DENY (unattended)


class PermissionDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


@dataclass
class PermissionRule:
    """A single permission rule. Reference: AgentScope allow_rules/deny_rules/ask_rules."""
    tool_name: str
    decision: PermissionDecision
    pattern: str = "*"  # Glob pattern for tool args matching
    description: str = ""


@dataclass
class PermissionResult:
    decision: PermissionDecision
    reason: str = ""
    bypass_immune: bool = False  # Reference: AgentScope bypass_immune — always ask regardless of mode


class PermissionEngine:
    """Permission engine with 5 modes and per-tool rules. Reference: AgentScope PermissionEngine."""

    def __init__(self, mode: PermissionMode = PermissionMode.DEFAULT, workspace_dir: str = "."):
        self.mode = mode
        self.workspace_dir = Path(workspace_dir)
        self._allow_rules: dict[str, list[PermissionRule]] = {}
        self._deny_rules: dict[str, list[PermissionRule]] = {}
        self._ask_rules: dict[str, list[PermissionRule]] = {}

    def allow(self, tool_name: str, pattern: str = "*", description: str = "") -> None:
        self._add_rule(self._allow_rules, tool_name, PermissionDecision.ALLOW, pattern, description)

    def deny(self, tool_name: str, pattern: str = "*", description: str = "") -> None:
        self._add_rule(self._deny_rules, tool_name, PermissionDecision.DENY, pattern, description)

    def ask(self, tool_name: str, pattern: str = "*", description: str = "") -> None:
        self._add_rule(self._ask_rules, tool_name, PermissionDecision.ASK, pattern, description)

    def _add_rule(self, rules: dict, tool_name: str, decision: PermissionDecision, pattern: str, description: str) -> None:
        if tool_name not in rules:
            rules[tool_name] = []
        rules[tool_name].append(PermissionRule(tool_name=tool_name, decision=decision, pattern=pattern, description=description))

    def check(self, tool_name: str, tool_args: dict[str, Any], is_read_only: bool = False,
              is_bypass_immune: bool = False) -> PermissionResult:
        """Check if a tool call should be allowed. Reference: AgentScope PermissionEngine.evaluate()."""
        if is_bypass_immune:
            return PermissionResult(decision=PermissionDecision.ASK, reason="bypass_immune: critical operation", bypass_immune=True)

        if self.mode == PermissionMode.BYPASS:
            return PermissionResult(decision=PermissionDecision.ALLOW, reason="bypass mode")

        if self.mode == PermissionMode.EXPLORE and not is_read_only:
            return PermissionResult(decision=PermissionDecision.DENY, reason="explore mode: read-only only")

        if self.mode == PermissionMode.EXPLORE:
            return PermissionResult(decision=PermissionDecision.ALLOW, reason="explore mode: read operation allowed")

        # Check deny rules first
        if tool_name in self._deny_rules:
            for rule in self._deny_rules[tool_name]:
                if self._match_pattern(tool_args, rule.pattern):
                    return PermissionResult(decision=PermissionDecision.DENY, reason=f"deny rule: {rule.description or rule.pattern}")

        # Check allow rules
        if tool_name in self._allow_rules:
            for rule in self._allow_rules[tool_name]:
                if self._match_pattern(tool_args, rule.pattern):
                    return PermissionResult(decision=PermissionDecision.ALLOW, reason=f"allow rule: {rule.description or rule.pattern}")

        # Check ask rules
        if tool_name in self._ask_rules:
            for rule in self._ask_rules[tool_name]:
                if self._match_pattern(tool_args, rule.pattern):
                    if self.mode == PermissionMode.DONT_ASK:
                        return PermissionResult(decision=PermissionDecision.DENY, reason="dont_ask mode: converting ask to deny")
                    return PermissionResult(decision=PermissionDecision.ASK, reason=f"ask rule: {rule.description or rule.pattern}")

        # ACCEPT_EDITS mode: auto-allow file edits and shell within workspace
        if self.mode == PermissionMode.ACCEPT_EDITS and tool_name in ("write_file", "edit_file", "apply_patch", "shell"):
            path = tool_args.get("path", tool_args.get("command", ""))
            if path and os.path.normpath(str(self.workspace_dir)) in os.path.normpath(str(path)):
                return PermissionResult(decision=PermissionDecision.ALLOW, reason="accept_edits: within workspace")

        # Default behavior
        if self.mode == PermissionMode.DEFAULT:
            return PermissionResult(decision=PermissionDecision.ASK, reason="default: ask for confirmation")
        if self.mode == PermissionMode.DONT_ASK:
            return PermissionResult(decision=PermissionDecision.DENY, reason="dont_ask mode")

        return PermissionResult(decision=PermissionDecision.ASK, reason="default")

    def _match_pattern(self, tool_args: dict[str, Any], pattern: str) -> bool:
        import fnmatch
        if pattern == "*":
            return True
        for value in tool_args.values():
            if fnmatch.fnmatch(str(value), pattern):
                return True
        return False

    def set_mode(self, mode: PermissionMode) -> None:
        self.mode = mode

    def clear_rules(self) -> None:
        self._allow_rules.clear()
        self._deny_rules.clear()
        self._ask_rules.clear()