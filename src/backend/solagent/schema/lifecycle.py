"""Agent 生命周期与健康管理相关的数据模型。

本模块定义了 Agent 健康状态的数据结构，用于监控 Agent 实例的存活状态、
负载情况以及最近活跃时间，支持服务发现和故障检测场景。
"""
from pydantic import BaseModel


class HealthStatus(BaseModel):
    """Agent 实例的健康状态快照。

    属性说明：
        agent_id: Agent 的唯一标识符。
        state: 当前状态描述，如 "healthy"、"unhealthy"、"starting"。
        last_seen: 最后一次心跳或响应的时间戳（Unix 时间）。
        load: 当前负载指标，数值越高表示负载越重，0.0 表示无负载。
    """
    agent_id: str
    state: str
    last_seen: float
    load: float = 0.0