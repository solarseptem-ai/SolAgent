"""SolAgent 异常基类。"""


class AgentError(Exception):
    """所有 Agent 异常的根基类。

    Attributes:
        cause: 原始底层异常，用于错误链追踪。
    """

    def __init__(self, message: str, *, cause: Exception | None = None):
        """
        Args:
            message: 错误描述信息。
            cause: 触发本异常的原始异常。
        """
        super().__init__(message)
        self.cause = cause