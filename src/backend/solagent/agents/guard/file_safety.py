"""文件操作安全守卫。

阻止对敏感文件和目录的读写操作，包括 SSH 密钥、凭据文件、系统配置文件等。
区分写操作（write/edit/apply_patch）和读操作（read）采用不同的阻断策略，
保护用户隐私和系统安全。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, ClassVar

from solagent.agents.guard.base import GuardContext, GuardResult

# 禁止写入的敏感文件路径集合
_BLOCKED_WRITE_PATHS: ClassVar[set[str]] = {
    ".ssh/authorized_keys", ".ssh/id_rsa", ".ssh/id_ed25519",
    ".ssh/config", ".netrc", ".pgpass", ".npmrc", ".pypirc",
    ".git-credentials", "/etc/sudoers", "/etc/passwd", "/etc/shadow",
    ".env", ".env.local", ".env.development", ".env.production",
    ".env.test", ".env.staging", ".envrc",
}

# 禁止写入的敏感目录前缀列表
_BLOCKED_WRITE_PREFIXES: ClassVar[list[str]] = [
    ".ssh/", ".aws/", ".gnupg/", ".kube/", ".docker/",
    ".azure/", ".config/gh/", ".config/gcloud/",
    "/etc/sudoers.d/", "/etc/systemd/",
]

# 禁止读取的敏感文件名集合
_BLOCKED_READ_BASENAMES: ClassVar[frozenset[str]] = frozenset({
    ".env", ".env.local", ".env.development", ".env.production",
    ".env.test", ".env.staging", ".envrc",
})


class FileSafetyGuard:
    """文件安全守卫，阻止对敏感路径的危险读写操作。

    属性:
        home_dir: 用户主目录路径，用于解析相对路径。
    """

    def __init__(self, home_dir: str | None = None):
        """初始化文件安全守卫。

        参数:
            home_dir: 显式指定主目录；None 则使用当前用户主目录。
        """
        self._home = Path(home_dir or os.path.expanduser("~")).resolve()

    def _expanded(self, path_str: str) -> Path:
        """将路径解析为绝对路径，相对路径基于 home_dir 解析。"""
        p = Path(path_str)
        if not p.is_absolute():
            p = self._home / p
        return p.resolve()

    async def check(self, tool_name: str, tool_args: dict[str, Any], context: GuardContext) -> GuardResult:
        """检查文件操作是否涉及敏感路径，必要时阻止执行。"""
        path = tool_args.get("path", tool_args.get("file_path", ""))
        if not path:
            return GuardResult()

        expanded = self._expanded(path)

        if tool_name in ("write", "edit", "apply_patch"):
            rel = str(expanded.relative_to(self._home)) if str(expanded).startswith(str(self._home)) else str(expanded)
            rel = rel.replace("\\", "/")

            for blocked in _BLOCKED_WRITE_PATHS:
                if rel == blocked or str(expanded) == blocked:
                    return GuardResult(
                        blocked=True, risk_level="high", code="file_blocked",
                        reason=f"Writing to {path} is blocked for security",
                    )

            for prefix in _BLOCKED_WRITE_PREFIXES:
                if rel.startswith(prefix) or str(expanded).startswith(prefix):
                    return GuardResult(
                        blocked=True, risk_level="high", code="file_blocked",
                        reason=f"Writing to {path} (in {prefix}) is blocked",
                    )

        if tool_name == "read":
            if Path(path).name in _BLOCKED_READ_BASENAMES:
                return GuardResult(
                    blocked=True, risk_level="medium", code="file_blocked",
                    reason=f"Reading {path} is blocked (credential file)",
                )

        return GuardResult()