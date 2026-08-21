"""
Agent 领域模型定义，涵盖 Agent 配置、状态、标识、能力及快照等核心数据结构。

本模块为 SolAgent 框架提供 Agent 运行所需的全部 Schema 层定义，
包括运行模式枚举、配置模型、状态追踪、全局唯一标识以及配置快照，
用于 Agent 的创建、序列化、持久化和跨实例通信。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from solagent.schema.llm import TokenUsage
from solagent.schema.messages import Message
from solagent.schema.tools import ToolResult


class AgentMode(str, Enum):
    """Agent 的运行模式枚举，决定 Agent 的行为策略和推理方式。"""
    CHAT = "chat"
    FUNCTION_CALL = "function_call"
    REACT = "react"
    PLAN_EXECUTE = "plan_execute"
    COMPILER = "compiler"
    REFLEXION = "reflexion"
    CODE_AS_ACTION = "code_as_action"
    EVOLVING_REACT = "evolving_react"
    DAG = "dag"


class AgentConfig(BaseModel):
    """Agent 的静态配置模型，定义 Agent 的行为参数与运行约束。

    属性说明：
        name: Agent 的名称标识。
        description: 对 Agent 功能的简短描述。
        system_prompt: 系统级提示词，用于设定 Agent 的角色和行为边界。
        model: 指定使用的 LLM 模型名称。
        mode: Agent 的运行模式，默认使用 ReAct 推理模式。
        max_iterations: 单次任务的最大迭代轮数，防止无限循环。
        max_tokens: 单次请求的最大生成 Token 数。
        max_execution_time: 最大执行时间（秒），0 表示不限制。
        temperature: 采样温度，控制输出的随机性。
        tools: Agent 可调用的工具名称列表。
        skills: Agent 可使用的技能名称列表。
        middleware: 中间件名称列表，用于扩展 Agent 行为。
        memory: 记忆模块配置，None 表示不使用记忆。
        guardrails: 安全防护规则名称列表。
        metadata: 额外的元数据字典，供扩展使用。
        compact_keep_last: 上下文压缩时保留的最新消息数量。
        compact_min_keep: 上下文压缩时至少保留的消息数量。
        auto_continue: 是否启用自动继续执行，当输出截断时自动续写。
        auto_continue_max_extra: 自动继续的最大额外轮数。
        circuit_breaker_enabled: 是否启用熔断机制，防止级联故障。
        max_replans: 最大重新规划次数，用于计划执行模式。
        termination_conditions: 自定义终止条件列表。
    """
    model_config = {"frozen": True}

    name: str
    description: str = ""
    system_prompt: str = ""
    model: str = ""
    mode: AgentMode = AgentMode.REACT
    max_iterations: int = 10
    max_tokens: int = 4096
    max_execution_time: int = 0
    temperature: float = 0.0
    tools: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    middleware: list[str] = Field(default_factory=list)
    memory: Any = None
    guardrails: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    compact_keep_last: int = 6
    compact_min_keep: int = 4
    auto_continue: bool = True
    auto_continue_max_extra: int = 2
    circuit_breaker_enabled: bool = True
    max_replans: int = 3
    code_timeout: int = 30
    termination_conditions: list[dict[str, Any]] = Field(default_factory=list)


@dataclass(frozen=True)
class AgentId:
    """Agent 的全局唯一标识符，采用三段式命名空间格式：namespace/name/instance。

    属性说明：
        namespace: 命名空间，用于组织和管理不同域的 Agent。
        name: Agent 的名称。
        instance: 实例标识，支持同一 Agent 的多个并发实例。
    """
    namespace: str
    name: str
    instance: str

    def __init__(self, full_id: str):
        """从三段式字符串解析 AgentId，格式必须为 'namespace/name/instance'。"""
        parts = full_id.split("/", 2)
        if len(parts) != 3:
            raise ValueError(f"AgentId must be 'namespace/name/instance', got '{full_id}'")
        # frozen dataclass 不允许直接赋值，需通过 object.__setattr__ 绕过
        object.__setattr__(self, "namespace", parts[0])
        object.__setattr__(self, "name", parts[1])
        object.__setattr__(self, "instance", parts[2])

    def __str__(self) -> str:
        """返回三段式字符串表示。"""
        return f"{self.namespace}/{self.name}/{self.instance}"


class AgentCapability(BaseModel):
    """Agent 能力描述模型，用于服务发现和动态路由。

    属性说明：
        agent_id: 关联的 Agent 标识符。
        modes: 支持的运行模式列表。
        tools: 可调用的工具名称列表。
        models: 支持的模型名称列表。
        address: Agent 的服务地址，用于远程调用。
        metadata: 扩展元数据。
    """
    agent_id: str
    modes: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)
    address: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderConfig(BaseModel):
    """LLM Provider 配置快照，仅保存配置引用而不存储实际密钥。

    属性说明：
        provider_type: Provider 类型，如 "openai"、"anthropic" 等。
        model: 使用的模型名称。
        base_url: 自定义 API 基础地址，None 则使用默认地址。
        api_key_ref: 密钥引用标识，由外部凭证存储系统解析为真实密钥。
        temperature: 采样温度。
        max_tokens: 最大生成 Token 数。
    """
    provider_type: str
    model: str
    base_url: str | None = None
    api_key_ref: str = ""
    temperature: float = 0.0
    max_tokens: int = 4096


class ToolSnapshot(BaseModel):
    """工具注册快照，仅保存工具的 Schema 描述而不包含可执行代码。

    用于 Agent 配置序列化和跨网络传输时的工具信息传递。

    属性说明：
        name: 工具名称。
        description: 工具功能描述。
        parameters_schema: 工具参数的结构化 Schema 定义。
    """
    name: str
    description: str
    parameters_schema: dict[str, Any] = Field(default_factory=dict)


class AgentSnapshot(BaseModel):
    """Agent 的完整配置快照，用于持久化、迁移和恢复 Agent 状态。

    属性说明：
        version: 快照格式版本号。
        config: Agent 的静态配置。
        provider: LLM Provider 配置。
        tools: 注册的工具快照列表。
        termination: 终止条件配置列表。
        memory: 记忆状态数据。
        guardrails: 安全防护规则配置。
    """
    version: str = "1.0"
    config: AgentConfig
    provider: ProviderConfig
    tools: list[ToolSnapshot] = Field(default_factory=list)
    termination: list[dict[str, Any]] = Field(default_factory=list)
    memory: dict[str, Any] | None = None
    guardrails: dict[str, Any] | None = None


class AgentStateEnum(str, Enum):
    """Agent 的运行时状态枚举，描述 Agent 在生命周期中的当前阶段。"""
    IDLE = "idle"           # 空闲状态，等待新任务
    RUNNING = "running"     # 正在执行推理或工具调用
    WAITING_TOOL = "waiting_tool"  # 等待工具执行结果返回
    DONE = "done"           # 任务已完成
    ERROR = "error"         # 执行过程中发生错误


class AgentState(BaseModel):
    """Agent 的运行时状态模型，记录当前执行过程中的动态数据。

    属性说明：
        messages: 当前会话中的消息历史列表。
        current_iteration: 当前迭代轮数，用于控制循环次数。
        tool_results: 已完成的工具调用结果列表。
        status: Agent 当前所处的状态。
        metadata: 运行时的扩展元数据。
    """
    messages: list[Message] = Field(default_factory=list)
    current_iteration: int = 0
    tool_results: list[ToolResult] = Field(default_factory=list)
    status: AgentStateEnum = AgentStateEnum.IDLE
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentResult(BaseModel):
    """Agent 执行任务后的结果模型，封装输出内容、消耗资源和执行轨迹。

    属性说明：
        content: Agent 生成的最终文本内容。
        messages: 执行过程中产生的完整消息历史。
        tool_results: 执行过程中所有工具调用的结果。
        token_usage: Token 消耗统计。
        finish_reason: 任务结束的原因描述。
        duration_ms: 任务执行耗时（毫秒）。
        steps: 执行步骤的详细记录，用于调试和审计。
    """
    model_config = {"frozen": True}

    content: str
    messages: list[Message] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    finish_reason: str = ""
    duration_ms: int = 0
    steps: list[dict] = Field(default_factory=list)