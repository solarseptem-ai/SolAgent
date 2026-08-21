"""消息序列化与反序列化工具模块。

本模块提供 Message 对象的序列化、JSONL 格式批量处理以及文件持久化功能。
采用 JSONL（每行一个 JSON 对象）格式存储消息历史，便于增量写入和流式读取，
同时支持原子写操作（先写入临时文件再替换），避免数据损坏。
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

_logger = logging.getLogger(__name__)

from solagent.schema.messages import Message


def serialize_message(msg: Message) -> str:
    """将单条消息序列化为 JSON 字符串。"""
    return msg.model_dump_json()


def deserialize_message(data: str) -> Message:
    """从 JSON 字符串反序列化为 Message 对象。"""
    return Message.model_validate_json(data)


def serialize_messages_jsonl(messages: list[Message]) -> str:
    """将消息列表序列化为 JSONL 格式字符串（每行一条 JSON）。"""
    return "\n".join(msg.model_dump_json() for msg in messages)


def deserialize_messages_jsonl(data: str) -> list[Message]:
    """从 JSONL 格式字符串反序列化为消息列表，自动跳过空行和格式错误的行。

    遇到解析失败的行时记录警告日志并继续处理后续行，确保容错性。
    """
    messages: list[Message] = []
    for line in data.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            messages.append(Message.model_validate_json(stripped))
        except Exception:
            _logger.warning("Serialization failed", exc_info=True)
            continue
    return messages


def serialize_to_file(messages: list[Message], path: Path) -> None:
    """将消息列表原子写入到指定文件路径。

    实现机制：
        1. 先在同目录创建临时文件写入内容。
        2. 写入成功后通过 replace 操作原子替换目标文件。
        3. 若写入失败则清理临时文件，避免残留脏数据。

    Args:
        messages: 待持久化的消息列表。
        path: 目标文件路径。
    """
    content = serialize_messages_jsonl(messages)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(suffix=".jsonl", dir=path.parent)
    try:
        with open(fd, "w", encoding="utf-8") as f:
            f.write(content)
        Path(tmp_path).replace(path)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise


def deserialize_from_file(path: Path) -> list[Message]:
    """从指定文件路径读取并反序列化消息列表。

    Args:
        path: 消息文件路径。

    Returns:
        反序列化后的消息列表；若文件不存在则返回空列表。
    """
    if not path.exists():
        return []
    data = path.read_text(encoding="utf-8")
    return deserialize_messages_jsonl(data)