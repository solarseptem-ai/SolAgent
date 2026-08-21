"""LLM 调用相关的异常类型。"""

from solagent.errors.base import AgentError


class LLMError(AgentError):
    """LLM 调用错误的基类。

    Attributes:
        status_code: HTTP 状态码（若有）。
        retry_after: 服务端建议的重试等待时间（秒）。
        error_type: 错误类型标识。
        error_code: 提供商特定的错误代码。
    """

    def __init__(self, message: str, *, status_code: int | None = None,
                 retry_after: float | None = None,
                 error_type: str | None = None,
                 error_code: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after
        self.error_type = error_type
        self.error_code = error_code


class RateLimitError(LLMError):
    """LLM API 速率限制超限（429）。"""


class TokenLimitError(LLMError):
    """请求 Token 数超过模型上下文窗口限制。"""


class LLMProviderError(LLMError):
    """提供商级别的不可重试错误（如模型不存在、参数非法等）。"""


class AuthError(LLMError):
    """鉴权/授权错误（401, 403），通常由 API Key 无效或权限不足引起。"""


class QuotaError(LLMError):
    """计费/额度错误（额度不足、欠费等），不可通过重试恢复。"""
