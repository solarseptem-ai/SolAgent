"""
任务队列端口 — 异步任务调度的抽象接口。

支持将任务入队并按 ID 获取执行结果，常用于后台执行和并发控制。
"""
from typing import Protocol

from solagent.schema.task import TaskResult, TaskSpec


class TaskPort(Protocol):
    """任务队列协议，提供入队和结果查询能力。"""

    async def enqueue(self, task: TaskSpec) -> str:
        """将任务加入队列。

        Args:
            task: 任务规格。

        Returns:
            分配的任务唯一标识 ID。
        """
        ...

    async def result(self, task_id: str, timeout: float = 60.0) -> TaskResult:
        """等待并获取任务的执行结果。

        Args:
            task_id: 任务 ID。
            timeout: 等待超时时间（秒），默认 60 秒。

        Returns:
            任务执行结果。
        """
        ...