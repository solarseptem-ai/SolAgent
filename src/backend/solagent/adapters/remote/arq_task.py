"""ARQ 任务适配器：通过 ARQ + Redis 实现 TaskPort，支持异步任务队列。

将 Agent 任务序列化后投递到 Redis 队列，由 ARQ worker 异步消费执行，
适用于需要削峰填谷、延迟执行或分布式调度的场景。
"""
from __future__ import annotations

import asyncio
import logging

from solagent.schema.task import TaskResult, TaskSpec, TaskStatus

_logger = logging.getLogger(__name__)


class ArqTaskAdapter:
    """基于 ARQ 的任务队列适配器。

    属性:
        _redis_url: Redis 连接地址。
        _pool: ARQ 连接池，延迟初始化。
    """

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self._redis_url = redis_url
        self._pool = None

    async def connect(self):
        """初始化与 Redis 的 ARQ 连接池。"""
        from arq import create_pool
        from arq.connections import RedisSettings
        self._pool = await create_pool(RedisSettings.from_dsn(self._redis_url))

    async def enqueue(self, task: TaskSpec) -> str:
        """将任务序列化后投递到 ARQ 队列。

        参数:
            task: 要投递的 TaskSpec。

        返回:
            ARQ 作业 ID。

        异常:
            RuntimeError: 当尚未调用 connect() 时抛出。
        """
        if not self._pool:
            raise RuntimeError("ArqTaskAdapter not connected")
        job = await self._pool.enqueue_job(
            "execute_agent_task",
            task.model_dump(),
            _job_id=task.task_id,
        )
        return job.job_id

    async def result(self, task_id: str, timeout: float = 60.0) -> TaskResult:
        """阻塞等待指定任务的结果。

        参数:
            task_id: 任务 ID（即 ARQ 作业 ID）。
            timeout: 最长等待时间（秒）。

        返回:
            任务结果；超时或失败时返回对应状态的 TaskResult。

        异常:
            RuntimeError: 当尚未调用 connect() 时抛出。
        """
        if not self._pool:
            raise RuntimeError("ArqTaskAdapter not connected")
        try:
            job_result = await asyncio.wait_for(
                self._pool.get_result(task_id), timeout=timeout
            )
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.COMPLETED,
                output=str(job_result) if job_result else "",
            )
        except TimeoutError:
            return TaskResult(task_id=task_id, status=TaskStatus.TIMEOUT, error="timeout")
        except Exception as e:
            _logger.warning("ARQ task execution failed", exc_info=True)
            return TaskResult(task_id=task_id, status=TaskStatus.FAILED, error=str(e))

    async def close(self):
        """关闭 ARQ 连接池。"""
        if self._pool:
            await self._pool.close()