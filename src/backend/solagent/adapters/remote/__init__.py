"""远程适配器：基于 gRPC、NATS、ARQ 等通信机制实现的分布式适配层。

用于将本地核心能力暴露为远程服务，或接入外部队列与事件总线，
支持 Agent 的微服务化、任务队列化与事件驱动的分布式部署。
"""
from solagent.adapters.remote.arq_task import ArqTaskAdapter
from solagent.adapters.remote.grpc_agent import GrpcAgentAdapter
from solagent.adapters.remote.grpc_server import AgentServer
from solagent.adapters.remote.nats_event import NatsEventAdapter
from solagent.adapters.remote.registry import NatsRegistry

__all__ = ["AgentServer", "ArqTaskAdapter", "GrpcAgentAdapter", "NatsEventAdapter", "NatsRegistry"]