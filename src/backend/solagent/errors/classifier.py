"""LLM 提供商错误分类器。

基于多维度特征对错误进行分类：HTTP 状态码、异常类名、错误消息文本模式（支持中英文）。
分类结果用于决定错误是否可重试，以及采用何种重试策略。
"""
from __future__ import annotations

from typing import Any

# 额度/计费相关错误关键词（中英文）
_QUOTA_PATTERNS = (
    "insufficient_quota",
    "quota",
    "billing",
    "credit",
    "payment",
    "余额不足",
    "超出限额",
    "额度不足",
    "欠费",
)

# 鉴权/权限相关错误关键词（中英文）
_AUTH_PATTERNS = (
    "authentication",
    "unauthorized",
    "invalid api key",
    "invalid_api_key",
    "permission",
    "forbidden",
    "access denied",
    "无权",
    "未授权",
)

# 服务繁忙/临时不可用相关错误关键词（中英文）
_BUSY_PATTERNS = (
    "server busy",
    "temporarily unavailable",
    "try again later",
    "please retry",
    "please try again",
    "overloaded",
    "high demand",
    "rate limit",
    "负载较高",
    "服务繁忙",
    "稍后重试",
    "请稍后重试",
)

# 可重试的 HTTP 状态码
_RETRIABLE_STATUS_CODES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})

# 瞬态网络/服务器异常类名
_TRANSIENT_EXCEPTIONS = frozenset({
    "APITimeoutError",
    "APIConnectionError",
    "InternalServerError",
    "ReadError",
    "RemoteProtocolError",
    "StreamChunkTimeoutError",
})

# 流式响应中断异常类名
_STREAM_DROP_EXCEPTIONS = frozenset({
    "StreamChunkTimeoutError",
})


def _match_any(detail: str, patterns: tuple[str, ...]) -> bool:
    """检查 detail 中是否包含任一 pattern 子串。"""
    return any(pattern in detail for pattern in patterns)


def extract_status_code(exc: BaseException) -> int | None:
    """从异常对象中提取 HTTP 状态码。

    按优先级尝试：status_code → status → response.status_code
    """
    for attr in ("status_code", "status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def extract_error_code(exc: BaseException) -> Any:
    """从异常对象中提取错误代码。

    按优先级尝试：code → error_code → body.error.code/type
    """
    for attr in ("code", "error_code"):
        value = getattr(exc, attr, None)
        if value not in (None, ""):
            return value
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            for key in ("code", "type"):
                value = error.get(key)
                if value not in (None, ""):
                    return value
    return None


def classify_error(exc: BaseException) -> tuple[bool, str]:
    """将 LLM 错误分类为（是否可重试, 原因）。

    分类结果：
        (True, "transient")  —— 可重试，临时网络/服务器问题
        (True, "busy")       —— 可重试，服务商过载
        (False, "quota")     —— 不可重试，计费/额度问题
        (False, "auth")      —— 不可重试，凭证问题
        (False, "generic")   —— 不可重试，未知错误

    Args:
        exc: 捕获到的异常对象。

    Returns:
        二元组（是否可重试, 原因字符串）。
    """
    detail = str(exc).lower()
    error_code = extract_error_code(exc)

    # 优先检查额度/计费问题（不可重试）
    if _match_any(detail, _QUOTA_PATTERNS) or _match_any(str(error_code).lower(), _QUOTA_PATTERNS):
        return False, "quota"
    # 检查鉴权问题（不可重试）
    if _match_any(detail, _AUTH_PATTERNS):
        return False, "auth"

    # 检查已知瞬态异常类名
    exc_name = type(exc).__name__
    if exc_name in _TRANSIENT_EXCEPTIONS:
        return True, "transient"

    # 检查可重试 HTTP 状态码
    status_code = extract_status_code(exc)
    if status_code in _RETRIABLE_STATUS_CODES:
        return True, "transient"

    # 检查服务繁忙关键词
    if _match_any(detail, _BUSY_PATTERNS):
        return True, "busy"

    return False, "generic"


def is_stream_drop(exc: BaseException) -> bool:
    """判断异常是否为流式响应中的分块超时（上游在响应中途停滞）。

    此类错误通常可通过重新发起请求恢复。
    """
    return type(exc).__name__ in _STREAM_DROP_EXCEPTIONS