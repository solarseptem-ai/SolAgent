"""Bash 命令安全扫描器。

针对 shell、execute、bash 等可执行系统命令的工具调用，使用正则表达式匹配高危和中危命令模式，
阻止潜在的破坏性操作（如删根目录、写系统文件、反弹 shell 等）。
支持对复合命令（分号、管道、与或连接）进行拆分后逐条检测。
"""

from __future__ import annotations

import re
from typing import Any

from solagent.agents.guard.base import GuardContext, GuardResult

# 高危命令正则模式：匹配可能导致系统损坏或安全漏洞的操作
_HIGH_RISK_PATTERNS: list[re.Pattern] = [
    re.compile(r"rm\s+-[^\s]*r[^\s]*\s+(/\*?|~/?\*?|/home\b|/root\b)\s*$"),
    re.compile(r"dd\s+if="),
    re.compile(r"mkfs"),
    re.compile(r"cat\s+/etc/shadow"),
    re.compile(r">+\s*/etc/"),
    re.compile(r"\|\s*(ba)?sh\b"),
    re.compile(r"[`$]\(?\s*(curl|wget|bash|sh|python|ruby|perl|base64)"),
    re.compile(r"base64\s+.*-d.*\|"),
    re.compile(r">+\s*(/usr/bin/|/bin/|/sbin/)"),
    re.compile(r">+\s*~/?\.(bashrc|profile|zshrc|bash_profile)"),
    re.compile(r"/proc/[^/]+/environ"),
    re.compile(r"\b(LD_PRELOAD|LD_LIBRARY_PATH)\s*="),
    re.compile(r"/dev/tcp/"),
    re.compile(r"\S+\(\)\s*\{[^}]*\|\s*\S+\s*&"),
    re.compile(r"while\s+true.*&\s*done"),
]

# 中危命令正则模式：匹配需要关注但未必立即阻止的操作
_MEDIUM_RISK_PATTERNS: list[re.Pattern] = [
    re.compile(r"chmod\s+777"),
    re.compile(r"pip3?\s+install"),
    re.compile(r"apt(-get)?\s+install"),
    re.compile(r"\b(sudo|su)\b"),
    re.compile(r"\bPATH\s*="),
]


class BashCommandScanner:
    """Bash 命令扫描守卫，检测并阻止危险 shell 命令。

    属性:
        block_high: 是否阻止高危命令（默认 True）。
        block_medium: 是否阻止中危命令（默认 False，仅警告）。
    """

    def __init__(self, block_high: bool = True, block_medium: bool = False):
        self._block_high = block_high
        self._block_medium = block_medium

    async def check(self, tool_name: str, tool_args: dict[str, Any], context: GuardContext) -> GuardResult:
        """检查工具调用中的命令参数是否包含危险模式。

        仅对 shell / execute / bash 类工具生效，其他工具直接放行。
        """
        if tool_name not in ("shell", "execute", "bash"):
            return GuardResult()

        command = tool_args.get("command", tool_args.get("cmd", ""))
        if not command:
            return GuardResult()

        for pattern in _HIGH_RISK_PATTERNS:
            if pattern.search(command):
                return GuardResult(
                    blocked=True, risk_level="high", code="bash_high_risk",
                    reason=f"High-risk command detected: {pattern.pattern[:60]}",
                )

        for sub_cmd in self._split_compound(command):
            for pattern in _HIGH_RISK_PATTERNS:
                if pattern.search(sub_cmd):
                    return GuardResult(
                        blocked=True, risk_level="high", code="bash_high_risk",
                        reason=f"High-risk command detected: {pattern.pattern[:60]}",
                    )

            for pattern in _MEDIUM_RISK_PATTERNS:
                if pattern.search(sub_cmd):
                    if self._block_medium:
                        return GuardResult(
                            blocked=True, risk_level="medium", code="bash_medium_risk",
                            reason=f"Medium-risk command detected: {pattern.pattern[:60]}",
                        )

        return GuardResult()

    @staticmethod
    def _split_compound(command: str) -> list[str]:
        parts: list[str] = []
        current: list[str] = []
        in_single = False
        in_double = False
        escaping = False

        for ch in command:
            if escaping:
                current.append(ch)
                escaping = False
                continue
            if ch == "\\":
                escaping = True
                current.append(ch)
                continue
            if ch == "'" and not in_double:
                in_single = not in_single
                current.append(ch)
                continue
            if ch == '"' and not in_single:
                in_double = not in_double
                current.append(ch)
                continue
            if not in_single and not in_double and ch in (";", "|", "&"):
                if ch == "&" and command[command.index(ch) + 1:command.index(ch) + 2] == "&":
                    parts.append("".join(current).strip())
                    current = []
                    continue
                parts.append("".join(current).strip())
                current = []
                continue
            current.append(ch)

        if current:
            parts.append("".join(current).strip())

        return [p for p in parts if p]