"""流式输出相关的数据模型定义。

本模块为 Agent 的流式响应提供事件类型枚举和事件数据结构，
支持文本增量、思考过程、工具调用、数据块传输等多种流式事件类型。
这些模型用于构建 Server-Sent Events（SSE）或 WebSocket 的响应负载，
使客户端能够实时接收 Agent 的执行进度和中间结果。
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class StreamEventType(str, Enum):
    """流式事件类型枚举，标识流中每一帧数据的语义类别。"""
    TEXT_DELTA = "text_delta"
    THINKING_DELTA = "thinking_delta"
    REASONING_DELTA = "reasoning_delta"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_DELTA = "tool_call_delta"
    TOOL_CALL_END = "tool_call_end"
    TOOL_RESULT = "tool_result"
    STEP_START = "step_start"
    STEP_END = "step_end"
    DATA_BLOCK_START = "data_block_start"
    DATA_BLOCK_DELTA = "data_block_delta"
    DATA_BLOCK_END = "data_block_end"
    ERROR = "error"
    DONE = "done"


class StreamEvent(BaseModel):
    """流式事件基类模型，表示流中的一个通用事件帧。

    属性说明：
        event_type: 事件的类型标识。
        data: 事件携带的负载数据字典。
        timestamp: 事件发生的时间戳（Unix 时间）。
        step_index: 事件关联的执行步骤序号，用于追踪执行进度。
    """
    event_type: StreamEventType
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: float = 0.0
    step_index: int = 0


class DeltaEvent(BaseModel):
    """增量事件模型，用于传输文本或思考内容的增量片段。

    属性说明：
        event_type: 增量事件的类型，如 TEXT_DELTA 或 THINKING_DELTA。
        content: 增量文本内容。
        finish_reason: 若当前增量标志着片段结束，给出结束原因。
        is_thinking: 标记是否属于思考过程增量。
    """
    event_type: StreamEventType
    content: str
    finish_reason: str | None = None
    is_thinking: bool = False


class StreamState(BaseModel):
    """流状态模型，用于客户端维护整个流式会话的聚合状态。

    属性说明：
        events: 已接收的所有事件列表。
        is_complete: 标记流是否已完全接收。
        error: 若流中断或出错，记录错误信息。
    """
    events: list[StreamEvent] = Field(default_factory=list)
    is_complete: bool = False
    error: str | None = None


class DataBlockStartEvent(BaseModel):
    """数据块开始事件，标志着一个结构化数据块的传输起始。

    属性说明：
        name: 数据块的名称标识。
        media_type: 数据块的 MIME 类型。
        block_id: 数据块的唯一标识。
        estimated_size: 预估的数据块总大小（字节），None 表示未知。
    """
    name: str
    media_type: str
    block_id: str
    estimated_size: int | None = None


class DataBlockDeltaEvent(BaseModel):
    """数据块增量事件，传输结构化数据块的分片内容。

    属性说明：
        block_id: 所属数据块的标识。
        index: 当前分片的序号。
        delta: 分片的增量数据内容。
        is_last: 标记是否为该数据块的最后一个分片。
    """
    block_id: str
    index: int
    delta: str
    is_last: bool = False


class DataBlockEndEvent(BaseModel):
    """数据块结束事件，标志着一个结构化数据块的传输完成。

    属性说明：
        block_id: 数据块的唯一标识。
        name: 数据块的名称。
        total_size: 数据块的实际总大小（字节）。
        media_type: 数据块的 MIME 类型。
    """
    block_id: str
    name: str
    total_size: int
    media_type: str