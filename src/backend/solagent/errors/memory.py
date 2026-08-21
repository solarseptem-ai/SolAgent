"""记忆存储相关的异常类型。"""

from solagent.errors.base import AgentError


class MemoryError(AgentError):
    """记忆相关错误的基类。"""


class MemoryNotFoundError(MemoryError):
    """根据指定 ID 未找到对应的记忆条目。

    Attributes:
        memory_id: 查询的记忆标识符。
    """

    def __init__(self, memory_id: str):
        super().__init__(f"Memory not found: {memory_id}")
        self.memory_id = memory_id