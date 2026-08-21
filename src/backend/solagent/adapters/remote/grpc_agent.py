"""gRPC Agent 适配器：通过 gRPC 协议实现 AgentPort，用于调用远程 Agent 服务。

将本地 TaskSpec 序列化为 protobuf 消息，通过 gRPC 发送到远程 AgentServer，
并将响应反序列化为标准的 TaskResult、HealthStatus 和 AgentCapability。
"""
from __future__ import annotations

import grpc

from solagent.adapters.remote import agent_pb2, agent_pb2_grpc
from solagent.schema.agent import AgentCapability
from solagent.schema.lifecycle import HealthStatus
from solagent.schema.task import TaskResult, TaskSpec, TaskStatus


class GrpcAgentAdapter:
    """gRPC 客户端适配器，用于与远程 Agent 服务通信。

    属性:
        _address: 远程 gRPC 服务地址，例如 "localhost:50051"。
        _channel: gRPC 异步通道。
        _stub: AgentService 的 gRPC 客户端存根。
    """

    def __init__(self, address: str):
        self._address = address
        self._channel = grpc.aio.insecure_channel(address)
        self._stub = agent_pb2_grpc.AgentServiceStub(self._channel)

    async def execute(self, task: TaskSpec) -> TaskResult:
        """向远程 Agent 发送执行任务请求。

        参数:
            task: 包含任务信息的 TaskSpec。

        返回:
            远程 Agent 返回的 TaskResult。
        """
        request = agent_pb2.TaskRequest(
            task_id=task.task_id,
            target_agent=task.target_agent,
            payload=task.payload,
            deadline=task.deadline,
            priority=task.priority,
        )
        response = await self._stub.Execute(request)
        return TaskResult(
            task_id=response.task_id,
            status=TaskStatus(response.status),
            output=response.output,
            error=response.error,
            duration_ms=response.duration_ms,
        )

    async def health(self) -> HealthStatus:
        """查询远程 Agent 的健康状态。"""
        response = await self._stub.Health(agent_pb2.HealthRequest())
        return HealthStatus(
            agent_id=response.agent_id,
            state=response.state,
            last_seen=response.last_seen,
            load=response.load,
        )

    async def capabilities(self) -> AgentCapability:
        """查询远程 Agent 的能力列表。"""
        response = await self._stub.Capabilities(agent_pb2.CapabilitiesRequest())
        return AgentCapability(
            agent_id=response.agent_id,
            modes=list(response.modes),
            tools=list(response.tools),
            models=list(response.models),
            address=response.address,
        )