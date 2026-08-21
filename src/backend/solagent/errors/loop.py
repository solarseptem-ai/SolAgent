"""Agent 循环执行相关的异常类型。"""

from solagent.errors.base import AgentError


class LoopError(AgentError):
    """Agent 主循环错误的基类。"""


class MaxIterationError(LoopError):
    """Agent 循环达到最大迭代次数上限。

    Attributes:
        max_iterations: 配置的最大允许迭代次数。
    """

    def __init__(self, max_iterations: int):
        super().__init__(f"Maximum iterations ({max_iterations}) reached")
        self.max_iterations = max_iterations