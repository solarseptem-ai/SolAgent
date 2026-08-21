"""应用级 YAML 配置数据模型。

基于 Pydantic BaseModel 定义 SolAgent 应用配置的各组成部分，
包括生成参数、提供商配置、Agent 配置块、MCP 服务器配置、工具/技能配置和日志配置。
所有模型均支持从 YAML/JSON 反序列化，并提供默认值以简化最小化配置。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class GenerationConfig(BaseModel):
    """LLM 生成参数配置。

    Attributes:
        temperature: 采样温度，控制输出随机性（0.0-2.0）。
        max_tokens: 单次生成的最大 Token 数。
        top_p: 核采样概率阈值。
        reasoning_effort: 推理努力程度（如 "low"/"medium"/"high"，仅部分模型支持）。
    """
    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: float = 1.0
    reasoning_effort: str | None = None


class ProviderConfig(BaseModel):
    """LLM 提供商配置块。

    Attributes:
        name: 提供商唯一标识名称。
        display_name: 展示名称。
        api_mode: API 模式，如 "chat_completions"。
        base_url: API 基础地址。
        api_key: 直接指定的 API 密钥。
        api_key_env: 存储 API 密钥的环境变量名（优先级高于 api_key）。
        default_model: 默认使用的模型名称。
        models: 该提供商支持的模型列表。
        generation: 默认生成参数。
        extra_headers: 额外的请求头。
        extra_body: 额外的请求体字段。
        use: 自定义提供商类路径（如 "module.Class"）。
    """
    name: str
    display_name: str = ""
    api_mode: str = "chat_completions"
    base_url: str = ""
    api_key: str = ""
    api_key_env: str = ""
    default_model: str = ""
    models: list[str] = Field(default_factory=list)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    extra_headers: dict[str, str] = Field(default_factory=dict)
    extra_body: dict[str, Any] = Field(default_factory=dict)
    use: str = ""


class AgentConfigBlock(BaseModel):
    """单个 Agent 的配置块。

    Attributes:
        name: Agent 唯一标识名称。
        description: Agent 功能描述。
        system_prompt: 系统提示词。
        model: 使用的模型名称。
        mode: 运行模式，如 "react"。
        max_iterations: 最大迭代次数上限。
        max_tokens: 单次调用最大 Token 数。
        temperature: 采样温度。
        tools: 启用的工具名称列表。
        skills: 启用的技能名称列表。
        middleware: 启用的中间件名称列表。
        guardrails: 启用的安全护栏名称列表。
    """
    name: str
    description: str = ""
    system_prompt: str = ""
    model: str = ""
    mode: str = "react"
    max_iterations: int = 10
    max_tokens: int = 4096
    temperature: float = 0.0
    tools: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    middleware: list[str] = Field(default_factory=list)
    guardrails: list[str] = Field(default_factory=list)


class MCPServerConfigBlock(BaseModel):
    """MCP 服务器配置块。

    Attributes:
        name: 服务器唯一标识名称。
        command: 启动命令（stdio 传输模式时使用）。
        args: 启动参数列表。
        env: 环境变量字典。
        url: 远程服务器地址（sse 传输模式时使用）。
        transport: 传输协议，如 "stdio" 或 "sse"。
    """
    name: str
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str = ""
    transport: str = "stdio"


class ToolConfigBlock(BaseModel):
    """工具配置块。

    Attributes:
        name: 工具唯一标识名称。
        enabled: 是否启用该工具。
        config: 工具的额外配置参数。
    """
    name: str
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


class SkillConfigBlock(BaseModel):
    """技能配置块。

    Attributes:
        source: 技能来源，如 "builtin" 或 "file"。
        path: 技能文件路径（source 为 file 时使用）。
        enabled: 是否启用该技能。
    """
    source: str = "builtin"
    path: str = ""
    enabled: bool = True


class LoggingConfig(BaseModel):
    """日志配置块。

    Attributes:
        level: 日志级别，如 "DEBUG"/"INFO"/"WARNING"/"ERROR"。
        format: 日志输出格式，如 "json" 或 "text"。
    """
    level: str = "INFO"
    format: str = "json"


class AppConfig(BaseModel):
    """应用级根配置模型，聚合所有配置子块。

    Attributes:
        default_model: 全局默认模型名称。
        default_mode: 全局默认 Agent 运行模式。
        log: 日志配置。
        providers: LLM 提供商配置列表。
        agents: Agent 配置列表。
        mcp_servers: MCP 服务器配置列表。
        tools: 工具配置列表。
        skills: 技能配置列表。
    """
    default_model: str = "gpt-4o"
    default_mode: str = "react"
    log: LoggingConfig = Field(default_factory=LoggingConfig)
    providers: list[ProviderConfig] = Field(default_factory=list)
    agents: list[AgentConfigBlock] = Field(default_factory=list)
    mcp_servers: list[MCPServerConfigBlock] = Field(default_factory=list)
    tools: list[ToolConfigBlock] = Field(default_factory=list)
    skills: list[SkillConfigBlock] = Field(default_factory=list)