"""
Core 模块的统一入口，导出框架核心的基础工具类和函数。

本模块聚合了序列化、会话上下文、Token 计数等核心能力，
供框架内部各模块统一导入使用，避免循环依赖和分散引用。
"""
from solagent.core.serialization import (
    deserialize_from_file,
    deserialize_message,
    deserialize_messages_jsonl,
    serialize_message,
    serialize_messages_jsonl,
    serialize_to_file,
)
from solagent.core.session import SessionContext
from solagent.core.token_counter import (
    CharTokenCounter,
    TiktokenCounter,
    TokenCounter,
    auto_counter,
)

__all__ = [
    "CharTokenCounter",
    "SessionContext",
    "TiktokenCounter",
    "TokenCounter",
    "auto_counter",
    "deserialize_from_file",
    "deserialize_message",
    "deserialize_messages_jsonl",
    "serialize_message",
    "serialize_messages_jsonl",
    "serialize_to_file",
]