"""本地 Agent 适配器：将 BaseAgent 包装为 AgentPort 的本地实现。

在同一线程/进程内直接调用 Agent 的 run 方法，将执行结果转换为标准 TaskResult，
同时提供健康状态与能力查询的本地版本。
"""
from __future__ import annotations

import time

from solagent.agents.base import BaseAgent
from solagent.schema.agent import AgentCapability
from solagent.schema.lifecycle import HealthStatus
from solagent.schema.task import TaskResult, TaskSpec, TaskStatus
from solagent.schema.messages import Message


class LocalAgentAdapter:
    """本地 Agent 端口适配器。

    属性:
        _agent: 被包装的 BaseAgent 实例。
    """

    def __init__(self, agent: BaseAgent):
        self._agent = agent

    async def execute(self, task: TaskSpec) -> TaskResult:
        """在本地执行 Agent 任务，将运行结果映射为标准 TaskResult。

        参数:
            task: 包含任务 ID、负载等信息的 TaskSpec。

        返回:
            包含状态、输出、耗时等的 TaskResult。
        """
        self._agent._ctx.messages = [Message.user(task.payload)]
        result = await self._agent.run()
        # 根据 finish_reason 判断任务最终状态
        if result.finish_reason in ("stop", "done"):
            status = TaskStatus.COMPLETED
        elif result.finish_reason == "timeout":
            status = TaskStatus.TIMEOUT
        else:
            status = TaskStatus.FAILED
        return TaskResult(
            task_id=task.task_id,
            status=status,
            output=result.content,
            error="" if result.finish_reason == "stop" else result.content,
            duration_ms=result.duration_ms,
        )

    async def health(self) -> HealthStatus:
        """返回本地 Agent 的健康状态（始终视为 idle）。"""
        return HealthStatus(
            agent_id=self._agent.config.name,
            state="idle",
            last_seen=time.monotonic(),
        )

    async def capabilities(self) -> AgentCapability:
        """返回本地 Agent 支持的模式、工具和模型列表。"""
        return AgentCapability(
            agent_id=self._agent.config.name,
            modes=[self._agent.config.mode.value],
            tools=list(self._agent.tools.list()),
            models=[self._agent.config.model],
        )