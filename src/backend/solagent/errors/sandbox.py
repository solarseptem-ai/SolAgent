"""沙箱执行相关的异常类型。"""

from solagent.errors.base import AgentError


class SandboxError(AgentError):
    """沙箱执行错误的基类。"""


class SandboxTimeoutError(SandboxError):
    """沙箱中代码执行超过指定时间限制。

    Attributes:
        timeout_seconds: 配置的超时时长（秒）。
    """

    def __init__(self, timeout_seconds: float):
        super().__init__(f"Sandbox execution timed out after {timeout_seconds}s")
        self.timeout_seconds = timeout_seconds