"""gRPC Agent 服务器：将 LocalAgentAdapter 暴露为 gRPC 服务。

接收远程的 Execute / Health / Capabilities 请求，
将 protobuf 消息转换为本地模型后交由 LocalAgentAdapter 处理，再把结果序列化返回。
适用于将单机 Agent 能力以微服务形式对外提供。
"""
from __future__ import annotations

import logging

from grpc import aio

from solagent.adapters.remote import agent_pb2, agent_pb2_grpc
from solagent.schema.task import TaskSpec

_logger = logging.getLogger(__name__)


class _AgentServicer(agent_pb2_grpc.AgentServiceServicer):
    """AgentService 的 gRPC 服务实现。

    属性:
        _local: 本地 LocalAgentAdapter 实例，负责实际处理请求。
    """

    def __init__(self, local_adapter):
        self._local = local_adapter

    async def Execute(self, request, context):
        """处理远程执行请求：反序列化 TaskSpec，调用本地 adapter，再序列化结果。"""
        task = TaskSpec(
            task_id=request.task_id,
            target_agent=request.target_agent,
            payload=request.payload,
            deadline=request.deadline,
            priority=request.priority,
        )
        result = await self._local.execute(task)
        return agent_pb2.TaskResponse(
            task_id=result.task_id,
            status=result.status.value,
            output=result.output,
            error=result.error,
            duration_ms=result.duration_ms,
        )

    async def Health(self, request, context):
        """处理远程健康查询请求。"""
        health = await self._local.health()
        return agent_pb2.HealthResponse(
            agent_id=health.agent_id,
            state=health.state,
            last_seen=health.last_seen,
            load=health.load,
        )

    async def Capabilities(self, request, context):
        """处理远程能力查询请求。"""
        cap = await self._local.capabilities()
        return agent_pb2.CapabilitiesResponse(
            agent_id=cap.agent_id,
            modes=cap.modes,
            tools=cap.tools,
            models=cap.models,
            address=cap.address,
        )


class AgentServer:
    """gRPC Agent 服务器包装器。

    负责创建 gRPC 异步服务器、绑定端口、注册服务实现以及优雅停止。

    属性:
        _local: 本地 LocalAgentAdapter 实例。
        _port: 期望绑定的端口。
        _actual_port: 实际绑定到的端口（可能因系统分配而与期望不同）。
        _server: gRPC 异步服务器实例。
    """

    def __init__(self, local_adapter, port: int = 50051):
        self._local = local_adapter
        self._port = port
        self._actual_port = port
        self._server: aio.Server | None = None

    @property
    def port(self) -> int:
        """返回服务器实际监听的端口。"""
        return self._actual_port or 0

    async def start(self):
        """启动 gRPC 服务器，绑定指定端口并注册 AgentService。"""
        self._server = aio.server()
        agent_pb2_grpc.add_AgentServiceServicer_to_server(
            _AgentServicer(self._local), self._server
        )
        bound_port = self._server.add_insecure_port(f"[::]:{self._port}")
        self._actual_port = bound_port
        await self._server.start()
        _logger.info("gRPC AgentServer started on port %d", self._actual_port)

    async def stop(self):
        """停止 gRPC 服务器（立即关闭，不等待正在处理的请求完成）。"""
        if self._server:
            await self._server.stop(0)
            self._server = None