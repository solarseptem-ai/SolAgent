"""
Agent 执行端口 — 本地与远程 Agent 执行的抽象接口。

定义 Agent 必须暴露的三个核心能力：
- execute: 执行一个任务规格并返回结果
- health: 返回当前健康状态
- capabilities: 声明自身具备的能力
"""
from typing import Protocol

from solagent.schema.agent import AgentCapability
from solagent.schema.lifecycle import HealthStatus
from solagent.schema.task import TaskResult, TaskSpec


class AgentPort(Protocol):
    """Agent 执行抽象协议，所有 Agent 实现需遵循此接口。"""

    async def execute(self, task: TaskSpec) -> TaskResult:
        """执行任务。

        Args:
            task: 任务规格，包含输入消息、工具列表、配置参数等。

        Returns:
            任务执行结果，包含输出内容、消息历史、Token 用量等。
        """
        ...

    async def health(self) -> HealthStatus:
        """查询 Agent 健康状态。"""
        ...

    async def capabilities(self) -> AgentCapability:
        """获取 Agent 声明的能力集合。"""
        ...