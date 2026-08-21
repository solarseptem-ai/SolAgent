"""
沙箱健康状态模块。

追踪沙箱的启动时间，提供启动宽限期判断，用于避免启动初期的健康检查误报。
"""
from __future__ import annotations

import time


class SandboxHealth:
    """沙箱健康状态追踪器。

    Attributes:
        startup_grace_seconds: 启动宽限期（秒），此期间内健康检查始终通过。
        _started_at: 启动时间戳，None 表示尚未启动。
    """

    def __init__(self, startup_grace_seconds: float = 15.0):
        self.startup_grace_seconds = startup_grace_seconds
        self._started_at: float | None = None

    def mark_started(self) -> None:
        """记录沙箱启动时间。"""
        self._started_at = time.monotonic()

    def is_within_grace_period(self) -> bool:
        """判断当前是否仍处于启动宽限期内。

        若尚未启动或距离启动时间不足宽限期，返回 True。
        """
        if self._started_at is None:
            return True
        elapsed = time.monotonic() - self._started_at
        return elapsed < self.startup_grace_seconds