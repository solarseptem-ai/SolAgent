"""
Schema 模块的统一入口，聚合并重新导出所有领域模型定义。

本模块将分散在各个子模块中的 Pydantic 模型、枚举类型和值对象集中暴露，
方便外部代码通过 `from solagent.schema import Xxx` 一次性导入所需类型。
涵盖消息、工具、LLM、Agent、任务、生命周期、记忆、流式输出、结构化输出、凭证等核心领域。
"""
from solagent.schema.agent import (
    AgentCapability,
    AgentConfig,
    AgentId,
    AgentMode,
    AgentResult,
    AgentSnapshot,
    AgentState,
    AgentStateEnum,
    ProviderConfig,
    ToolSnapshot,
)
from solagent.schema.abort import (
    AbortController,
    AbortError,
    AbortSignal,
)
from solagent.schema.lifecycle import (
    HealthStatus,
)
from solagent.schema.task import (
    TaskResult,
    TaskSpec,
    TaskStatus,
)
from solagent.schema.credentials import (
    CredentialStore,
)
from solagent.schema.llm import (
    GenerationSettings,
    LLMErrorDetail,
    LLMFinishReason,
    LLMRequest,
    LLMResponse,
    LLMStreamChunk,
    TokenUsage,
)
from solagent.schema.memory import (
    MemoryCategory,
    MemoryQuery,
    MemoryRecord,
    MemorySearchResult,
)
from solagent.schema.messages import (
    ContentBlock,
    ImageBlock,
    ImageSource,
    ImageSourceType,
    Message,
    MessageRole,
    TextBlock,
    ThinkingBlock,
    ToolCallBlock,
    ToolCallState,
    ToolResultBlock,
)
from solagent.schema.stream import (
    DataBlockDeltaEvent,
    DataBlockEndEvent,
    DataBlockStartEvent,
    DeltaEvent,
    StreamEvent,
    StreamEventType,
    StreamState,
)
from solagent.schema.structured import (
    ConversationSummary,
    DAGModel,
    DAGStep,
    PlanModel,
    PlanStep,
    ReflexionModel,
    RetryPolicy,
)
from solagent.schema.tools import (
    ToolCall,
    ToolDefinition,
    ToolParameter,
    ToolParameterType,
    ToolResult,
    ToolSchema,
)

__all__ = [
    # abort
    "AbortController",
    "AbortError",
    "AbortSignal",
    # messages
    "ContentBlock",
    "ImageBlock",
    "ImageSource",
    "ImageSourceType",
    "Message",
    "MessageRole",
    "TextBlock",
    "ThinkingBlock",
    "ToolCallBlock",
    "ToolCallState",
    "ToolResultBlock",
    # tools
    "ToolCall",
    "ToolDefinition",
    "ToolParameter",
    "ToolParameterType",
    "ToolResult",
    "ToolSchema",
    # llm
    "GenerationSettings",
    "LLMErrorDetail",
    "LLMFinishReason",
    "LLMRequest",
    "LLMResponse",
    "LLMStreamChunk",
    "TokenUsage",
    # agent
    "AgentCapability",
    "AgentConfig",
    "AgentId",
    "AgentMode",
    "AgentResult",
    "AgentSnapshot",
    "AgentState",
    "AgentStateEnum",
    "ProviderConfig",
    "ToolSnapshot",
    # task
    "TaskResult",
    "TaskSpec",
    "TaskStatus",
    # lifecycle
    "HealthStatus",
    # memory
    "MemoryCategory",
    "MemoryQuery",
    "MemoryRecord",
    "MemorySearchResult",
    # stream
    "DataBlockDeltaEvent",
    "DataBlockEndEvent",
    "DataBlockStartEvent",
    "DeltaEvent",
    "StreamEvent",
    "StreamEventType",
    "StreamState",
    # structured
    "ConversationSummary",
    "DAGModel",
    "DAGStep",
    "PlanModel",
    "PlanStep",
    "ReflexionModel",
    "RetryPolicy",
    # credentials
    "CredentialStore",
]