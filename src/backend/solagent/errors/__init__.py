"""SolAgent 错误类型定义模块。

集中暴露 Agent 运行过程中可能抛出的所有异常类型，按功能域分为：
    - base: 所有异常的根基类 AgentError
    - llm: LLM 调用相关错误（速率限制、Token 超限、鉴权等）
    - loop: Agent 循环相关错误（最大迭代次数超限）
    - mcp: MCP 服务器连接错误
    - memory: 记忆存储相关错误
    - sandbox: 沙箱执行错误
    - tool: 工具调用错误
"""

from solagent.errors.base import AgentError
from solagent.errors.llm import AuthError, LLMError, LLMProviderError, QuotaError, RateLimitError, TokenLimitError
from solagent.errors.loop import LoopError, MaxIterationError
from solagent.errors.mcp import MCPConnectionError, MCPError
from solagent.errors.memory import MemoryError, MemoryNotFoundError
from solagent.errors.sandbox import SandboxError, SandboxTimeoutError
from solagent.errors.tool import ToolError, ToolExecutionError, ToolNotFoundError

__all__ = [
    "AgentError",
    "AuthError",
    "LLMError",
    "LLMProviderError",
    "LoopError",
    "MCPConnectionError",
    "MCPError",
    "MaxIterationError",
    "MemoryError",
    "MemoryNotFoundError",
    "QuotaError",
    "RateLimitError",
    "SandboxError",
    "SandboxTimeoutError",
    "TokenLimitError",
    "ToolError",
    "ToolExecutionError",
    "ToolNotFoundError",
]