"""FastAPI 请求/响应模型定义：使用 Pydantic 对 API 的输入输出进行类型校验与序列化。

涵盖 Agent 运行、健康检查、指标监控、配置查询以及学习系统相关的各类数据模型。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class AgentRunRequest(BaseModel):
    """Agent 运行请求体。

    支持通过配置名称、直接参数或模板名称等多种方式指定 Agent 的行为与上下文。
    """
    messages: list[dict] = Field(default_factory=list, description="Conversation messages")
    agent_name: str = Field(default="", description="Agent name from config")
    model: str = Field(default="", description="Model override")
    mode: str = Field(default="", description="Mode override (chat/react/function_call/...)")
    stream: bool = Field(default=False, description="Enable SSE streaming")
    system_prompt: str = Field(default="", description="System prompt override")
    prompt_template: str = Field(default="", description="Prompt template name from registry")
    max_iterations: int = Field(default=0, description="Max iterations override")
    max_tokens: int = Field(default=0, description="Max tokens override")
    temperature: float = Field(default=-1.0, description="Temperature override (-1 = use config default)")
    tools: list[str] = Field(default_factory=list, description="Tools to enable")


class AgentRunResponse(BaseModel):
    """Agent 运行响应体。

    包含生成内容、完成原因、token 用量、工具调用结果、执行耗时与中间步骤。
    """
    content: str = ""
    finish_reason: str = ""
    token_usage: dict = Field(default_factory=dict)
    tool_calls: list[dict] = Field(default_factory=list)
    duration_ms: int = 0
    steps: list[dict] = Field(default_factory=list)
    error: str = ""


class HealthResponse(BaseModel):
    """健康检查响应，返回当前注册的服务商与 Agent 列表。"""
    status: str = "ok"
    version: str = "0.1.0"
    providers: list[str] = Field(default_factory=list)
    agents: list[str] = Field(default_factory=list)


class MetricsResponse(BaseModel):
    """系统指标响应，汇总请求总量、token 消耗、活跃服务商数和可用模式。"""
    total_requests: int = 0
    total_tokens: dict = Field(default_factory=dict)
    active_providers: int = 0
    agent_modes: list[str] = Field(default_factory=list)


class ConfigResponse(BaseModel):
    """配置信息响应，返回默认模型/模式、服务商列表、Agent 列表和可用提示模板。"""
    default_model: str = ""
    default_mode: str = ""
    providers: list[dict] = Field(default_factory=list)
    agents: list[dict] = Field(default_factory=list)
    prompt_templates: list[str] = Field(default_factory=list)


class LearningExperienceResponse(BaseModel):
    """学习经验查询响应，包含经验记录列表、总数和标签分布。"""
    experiences: list[dict] = Field(default_factory=list)
    total: int = 0
    tags_distribution: dict[str, int] = Field(default_factory=dict)


class LearningStrategyResponse(BaseModel):
    """学习策略查询响应，包含策略规则列表、总数和状态分布。"""
    strategies: list[dict] = Field(default_factory=list)
    total: int = 0
    status_distribution: dict[str, int] = Field(default_factory=dict)


class LearningScoreResponse(BaseModel):
    """学习评分响应，综合展示任务成功率、工具效率、token 效率和学习进度等指标。

    overall 为加权总分，breakdown 提供各维度细项得分。
    """
    overall: float = 0.0
    breakdown: dict[str, float] = Field(default_factory=dict)
    trend: list[dict] = Field(default_factory=list)
    experience_count: int = 0
    strategy_count: int = 0
    last_reflection: str = ""
    next_reflection_eta: str = ""