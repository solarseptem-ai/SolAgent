"""LLM（大语言模型）相关的数据模型定义。

本模块封装了与 LLM 交互所需的全部 Schema，包括请求参数、响应内容、
流式输出片段、Token 消耗统计以及错误详情等。这些模型用于统一不同 LLM Provider
（如 OpenAI、Anthropic 等）的输入输出格式，使上层代码可以无差别地处理各类模型响应。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, Field

from solagent.schema.messages import Message
from solagent.schema.tools import ToolCall, ToolDefinition


class LLMFinishReason(str, Enum):
    """LLM 生成结束的缘由枚举，用于判断响应终止的具体原因。"""
    STOP = "stop"
    TOOL_CALLS = "tool_calls"
    LENGTH = "length"
    CONTENT_FILTER = "content_filter"
    ERROR = "error"


class TokenUsage(BaseModel):
    """Token 消耗统计模型，记录一次 LLM 请求中各类 Token 的使用量。

    属性说明：
        input_tokens: 输入提示词消耗的 Token 数量。
        output_tokens: 模型生成内容消耗的 Token 数量。
        cache_read_tokens: 从缓存中读取的 Token 数量（部分 Provider 支持提示缓存）。
        cache_write_tokens: 写入缓存的 Token 数量。
    """
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """返回总 Token 消耗量，包含输入、输出及缓存相关 Token。"""
        return self.input_tokens + self.output_tokens + self.cache_read_tokens + self.cache_write_tokens

    def __add__(self, other: TokenUsage) -> TokenUsage:
        """支持两个 TokenUsage 实例相加，用于聚合多轮请求的 Token 消耗。"""
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
        )


class LLMStreamChunk(BaseModel):
    """LLM 流式输出中的单个片段模型，用于逐块接收模型生成的内容。

    属性说明：
        content: 当前片段的文本内容。
        finish_reason: 若当前片段标志着生成结束，则给出结束原因。
        is_thinking: 标记当前内容是否属于模型的思考过程（如 Anthropic 的扩展思考）。
        reasoning_content: 模型推理过程的原始内容。
        index: 片段在流中的序号。
        tool_call_id: 关联的工具调用标识。
        tool_call_name: 关联的工具名称。
        tool_call_arguments: 工具调用的参数 JSON 字符串（流式拼接中）。
        usage: 当前片段附带的 Token 使用统计（部分 Provider 仅在最后一块提供）。
        data_block: 扩展数据块，用于传输自定义结构化数据。
    """
    content: str
    finish_reason: LLMFinishReason | None = None
    is_thinking: bool = False
    reasoning_content: str = ""
    index: int = 0
    tool_call_id: str = ""
    tool_call_name: str = ""
    tool_call_arguments: str = ""
    usage: TokenUsage | None = None
    data_block: dict | None = None


class LLMErrorDetail(BaseModel):
    """LLM 请求失败时的错误详情模型，封装了诊断和重试决策所需的全部信息。

    属性说明：
        message: 错误描述信息。
        status_code: HTTP 状态码，若为 None 则表示非 HTTP 层错误。
        error_type: 错误类型分类，如 "rate_limit"、"timeout"。
        retry_after: 服务端建议的等待重试时间（秒）。
        error_kind: 错误种类的细分标识。
        error_code:  Provider 特定的错误代码。
        response_body: 原始响应体内容，用于调试。
    """
    message: str
    status_code: int | None = None
    error_type: str = "unknown"
    retry_after: float | None = None
    error_kind: str = ""
    error_code: str = ""
    response_body: str = ""

    @property
    def should_retry(self) -> bool:
        """根据 HTTP 状态码判断当前错误是否适合重试。

        429（限流）和 5xx 服务端错误通常具有瞬时性，适合重试；
        4xx 客户端错误通常不应重试。
        """
        if self.status_code is None:
            return False
        return self.status_code in (429, 500, 502, 503, 504)


class LLMResponse(BaseModel):
    """LLM 非流式请求的完整响应模型，聚合了模型生成的全部内容和元数据。

    属性说明：
        content: 模型生成的文本内容。
        finish_reason: 生成结束的原因。
        usage: Token 消耗统计。
        tool_calls: 模型请求调用的工具列表。
        model: 实际响应的模型名称。
        retry_after: 限流时建议的等待时间。
        reasoning_content: 模型的推理过程内容。
        error_status_code: 若发生错误，对应的 HTTP 状态码。
        error_kind: 错误种类。
        error_type: 错误类型。
        error_code: Provider 错误代码。
        error_retry_after_s: 错误场景下建议的重试等待时间。
        error_should_retry: 标记该错误是否应触发重试逻辑。
    """
    content: str
    finish_reason: LLMFinishReason
    usage: TokenUsage = Field(default_factory=TokenUsage)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    model: str = ""
    retry_after: float | None = None
    reasoning_content: str | None = None
    error_status_code: int | None = None
    error_kind: str | None = None
    error_type: str | None = None
    error_code: str | None = None
    error_retry_after_s: float | None = None
    error_should_retry: bool | None = None

    @property
    def has_tool_calls(self) -> bool:
        """判断当前响应中是否包含工具调用请求。"""
        return len(self.tool_calls) > 0


class LLMRequest(BaseModel):
    """向 LLM 发起请求时的参数模型，封装了对话消息和生成控制参数。

    属性说明：
        messages: 对话历史消息列表，包含系统和用户消息。
        model: 目标模型名称。
        temperature: 采样温度，0.0 表示确定性输出，越高随机性越强。
        max_tokens: 单次请求允许生成的最大 Token 数。
        top_p: 核采样参数，控制候选 Token 的累积概率阈值。
        stop: 停止词列表，模型遇到这些词时停止生成。
        tools: 可供模型调用的工具定义列表。
        stream: 是否启用流式输出。
        extra_headers: 额外的 HTTP 请求头，用于传递 Provider 特定参数。
    """
    messages: list[Message]
    model: str
    temperature: float = 0.0
    max_tokens: int = 4096
    top_p: float = 1.0
    stop: list[str] = Field(default_factory=list)
    tools: list[ToolDefinition] = Field(default_factory=list)
    stream: bool = False
    extra_headers: dict[str, str] = Field(default_factory=dict)


@dataclass(frozen=True)
class GenerationSettings:
    """LLM 生成参数的数据类，用于在不同组件间传递生成控制配置。

    属性说明：
        temperature: 采样温度，默认 0.7 在创造性和确定性之间取得平衡。
        max_tokens: 最大生成 Token 数，默认 4096。
        reasoning_effort: 推理努力程度（部分模型支持，如 OpenAI o1 系列），
            可选值如 "low"、"medium"、"high"，None 表示使用模型默认策略。
    """
    temperature: float = 0.7
    max_tokens: int = 4096
    reasoning_effort: str | None = None