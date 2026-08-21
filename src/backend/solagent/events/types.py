"""SolAgent 事件类型定义与事件模型。

定义了 Agent 运行过程中可能产生的所有标准事件类型，以及 CloudEvents 兼容的事件结构。
"""

import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AgentEventType(str, Enum):
    """Agent 运行时标准事件类型枚举。

    事件命名采用 domain.action.stage 的三段式结构：
        - agent.*: Agent 生命周期事件
        - llm.call.*: LLM 调用事件
        - tool.call.*: 工具调用事件
        - memory.*: 记忆操作事件
        - plan.*: 计划执行事件
        - knowledge.query.*: 知识库查询事件
        - stream.*: 流式输出事件
    """
    AGENT_START = "agent.start"                    # Agent 开始运行
    AGENT_END = "agent.end"                        # Agent 运行结束
    AGENT_ERROR = "agent.error"                    # Agent 执行出错
    AGENT_STATE_CHANGE = "agent.state_change"      # Agent 状态变更
    LLM_CALL_START = "llm.call.start"              # LLM 调用开始
    LLM_CALL_END = "llm.call.end"                  # LLM 调用结束
    LLM_CALL_ERROR = "llm.call.error"              # LLM 调用出错
    RETRY_ATTEMPT = "retry.attempt"                # 重试尝试
    RATE_LIMITED = "rate.limited"                  # 触发速率限制
    TOOL_CALL_START = "tool.call.start"            # 工具调用开始
    TOOL_CALL_END = "tool.call.end"                # 工具调用结束
    TOOL_CALL_ERROR = "tool.call.error"            # 工具调用出错
    TOOL_CALL_STATE_CHANGE = "tool.call.state_change"  # 工具调用状态变更
    MEMORY_ADD = "memory.add"                      # 添加记忆
    MEMORY_QUERY = "memory.query"                  # 查询记忆
    GUARDRAIL_TRIGGERED = "guardrail.triggered"    # 触发安全护栏
    PLAN_START = "plan.start"                      # 计划开始
    PLAN_END = "plan.end"                          # 计划结束
    PLAN_STEP = "plan.step"                        # 计划步骤执行
    KNOWLEDGE_QUERY_START = "knowledge.query.start"    # 知识库查询开始
    KNOWLEDGE_QUERY_END = "knowledge.query.end"        # 知识库查询结束
    KNOWLEDGE_QUERY_ERROR = "knowledge.query.error"    # 知识库查询出错
    STREAM_DELTA = "stream.delta"                  # 流式输出片段
    STREAM_END = "stream.end"                      # 流式输出结束
    PLUGIN_EVENT = "plugin.event"                  # 插件自定义事件


class AgentEvent(BaseModel):
    """CloudEvents 兼容的标准事件结构。

    Attributes:
        event_id: 全局唯一事件标识符（UUID）。
        event_type: 事件类型，决定事件的语义和处理方式。
        data: 事件载荷，具体结构由 event_type 决定。
        session_id: 所属会话标识，用于跨事件追踪同一 Agent 运行实例。
        topic: 事件主题，用于路由和过滤。
        source: 事件来源组件名称。
        parent_event_id: 父事件 ID，用于构建事件因果链。
        timestamp: 事件生成时间（UTC）。
    """
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: AgentEventType
    data: dict[str, Any] = Field(default_factory=dict)
    session_id: str = ""
    topic: str = ""
    source: str = ""
    parent_event_id: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))