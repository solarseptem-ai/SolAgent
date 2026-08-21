"""持久化会话日志模块，基于 Durable Event 模式实现事件溯源。

本模块采用"先写日志，再改内存状态"的事件溯源设计，所有对会话状态的变更
都先以不可变事件的形式追加到日志中。这种设计支持：
- 通过事件重放恢复 Agent 的任意历史状态。
- 会话压缩（compaction）减少长会话的存储和传输开销。
- 多观察者（listener + surface）实时消费事件流。

支持的事件类型包括：turn/start、turn/end、step/start、step/end、
user/message、assistant/message、tool/call、tool/result、session/summary 等。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from solagent.schema.messages import Message

_logger = logging.getLogger(__name__)


class DurableEventType:
    """持久化事件类型常量集合，定义会话日志中所有支持的事件类型标识。"""
    TURN_START = "turn/start"           # 一轮交互开始
    TURN_END = "turn/end"               # 一轮交互结束
    STEP_START = "step/start"           # 单步执行开始
    STEP_END = "step/end"               # 单步执行结束
    USER_MESSAGE = "user/message"       # 用户输入消息
    ASSISTANT_MESSAGE = "assistant/message"  # 助手回复消息
    TOOL_CALL = "tool/call"             # 工具调用请求
    TOOL_RESULT = "tool/result"         # 工具执行结果
    SYSTEM_INJECT = "system/inject"     # 系统消息注入
    INBOX_SPLICED = "agent/inbox/spliced"  # 收件箱拼接事件
    SUMMARY = "session/summary"         # 会话摘要


@dataclass
class DurableEvent:
    """单个持久化事件，表示会话历史中的一次不可变变更记录。

    属性说明：
        type: 事件类型，来自 DurableEventType 的常量。
        turn: 事件所属的交互轮次序号。
        step: 事件在该轮次中的步骤序号。
        data: 事件携带的负载数据字典。
        timestamp: 事件创建时间的 ISO 格式字符串（UTC）。
        compacted: 标记该事件是否已被压缩（压缩后不再参与消息派生）。
        surface_op: 表面操作类型，可选 "append"、"replace" 或 None。
        source_event_indices: 当 surface_op 为 "replace" 时，指向被替换的事件索引列表。
    """
    type: str
    turn: int = 0
    step: int = 0
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    compacted: bool = False
    surface_op: str | None = None  # "append" | "replace" | None
    source_event_indices: list[int] | None = None  # replace 操作时指向被替换的事件索引


class SessionLog:
    """持久化会话日志管理器，负责事件的追加、查询、重放和压缩。

    核心设计原则：
        - 事件一旦追加不可修改，保证历史可追溯。
        - 通过 compacted 标记实现逻辑删除，而非物理删除。
        - 支持监听器和表面（surface）两种观察者模式消费事件。
    """

    def __init__(self):
        """初始化空的会话日志实例。"""
        self._events: list[DurableEvent] = []
        self._listeners: list = []
        self._surface = None

    def attach_surface(self, surface) -> None:
        """附加一个表面（surface）对象，用于接收事件并更新可观测状态。"""
        self._surface = surface

    def append(self, event_type: str, turn: int = 0, step: int = 0, data: dict[str, Any] | None = None,
               surface_op: str | None = None, source_event_indices: list[int] | None = None) -> DurableEvent:
        """追加一个新事件到日志，并通知所有监听者和表面对象。

        Args:
            event_type: 事件类型标识。
            turn: 所属交互轮次。
            step: 所属步骤序号。
            data: 事件负载数据。
            surface_op: 表面操作类型。
            source_event_indices: 被替换事件的索引列表。

        Returns:
            创建的 DurableEvent 实例。
        """
        event = DurableEvent(type=event_type, turn=turn, step=step, data=data or {},
                             surface_op=surface_op, source_event_indices=source_event_indices)
        event_index = len(self._events)
        self._events.append(event)
        # 通知所有注册的事件监听器，单个监听器异常不影响其他监听器
        for listener in self._listeners:
            try:
                listener(event)
            except Exception:
                pass
        # 若已附加 surface，将事件应用到表面状态
        if self._surface is not None:
            self._surface.apply(event, event_index)
        return event

    def replay(self) -> list[DurableEvent]:
        """返回所有事件的副本列表，用于重放分析或审计。"""
        return list(self._events)

    def replay_from(self, turn: int) -> list[DurableEvent]:
        """返回从指定轮次开始的所有事件，用于部分状态恢复。

        Args:
            turn: 起始轮次（含）。
        """
        return [e for e in self._events if e.turn >= turn]

    def last_turn(self) -> int:
        """获取日志中记录的最大交互轮次，空日志返回 0。"""
        if not self._events:
            return 0
        return max(e.turn for e in self._events)

    def last_step(self, turn: int) -> int:
        """获取指定轮次中的最大步骤序号。

        Args:
            turn: 目标交互轮次。

        Returns:
            该轮次的最大步骤序号；若该轮次无事件则返回 0。
        """
        steps = [e.step for e in self._events if e.turn == turn]
        return max(steps) if steps else 0

    def on_event(self, listener) -> None:
        """注册一个事件监听器，新事件追加时会同步调用。"""
        self._listeners.append(listener)

    def clear(self) -> None:
        """清空所有事件和监听器，重置日志状态。"""
        self._events.clear()

    def to_jsonl(self) -> str:
        """将日志序列化为 JSONL 格式字符串，便于持久化存储。"""
        return "\n".join(
            json.dumps({
                "type": e.type, "turn": e.turn, "step": e.step,
                "data": e.data, "timestamp": e.timestamp,
                "compacted": e.compacted,
            })
            for e in self._events
        )

    @classmethod
    def from_jsonl(cls, text: str) -> SessionLog:
        """从 JSONL 格式字符串反序列化恢复会话日志。

        Args:
            text: JSONL 格式的日志文本。

        Returns:
            恢复后的 SessionLog 实例。
        """
        log = cls()
        for line in text.strip().split("\n"):
            if not line:
                continue
            d = json.loads(line)
            event = log.append(
                d["type"],
                turn=d.get("turn", 0),
                step=d.get("step", 0),
                data=d.get("data", {}),
            )
            event.compacted = d.get("compacted", False)
        return log

    def __len__(self) -> int:
        """返回当前日志中的事件总数。"""
        return len(self._events)

    def __iter__(self):
        """支持迭代访问日志中的所有事件。"""
        return iter(self._events)

    def derive_messages(self, start_turn: int = 0) -> list[Message]:
        """从日志事件中派生出模型可见的消息列表。

        过滤条件：
            - 排除已被压缩（compacted）的事件。
            - 仅包含用户消息、助手消息、工具结果和摘要事件。
            - 仅包含指定轮次之后的事件。

        Args:
            start_turn: 起始轮次（含），默认从第 0 轮开始。

        Returns:
            派生出的 Message 列表。
        """
        messages: list[Message] = []
        for event in self._events:
            if event.turn < start_turn:
                continue
            if event.compacted:
                continue
            msg_data = event.data.get("message")
            if msg_data is None:
                continue
            if event.type in (
                DurableEventType.USER_MESSAGE,
                DurableEventType.ASSISTANT_MESSAGE,
                DurableEventType.TOOL_RESULT,
                DurableEventType.SUMMARY,
            ):
                messages.append(Message.model_validate(msg_data))
        return messages

    def compact(self, turn_start: int, turn_end: int) -> int:
        """将指定轮次范围内的消息事件标记为已压缩（compacted）。

        压缩后的事件不再参与消息派生，但保留在日志中用于审计。
        通常配合 add_summary 使用，用摘要替代原始消息以节省 Token。

        Args:
            turn_start: 压缩起始轮次（含）。
            turn_end: 压缩结束轮次（含）。

        Returns:
            被标记为 compacted 的事件数量。
        """
        count = 0
        for event in self._events:
            if turn_start <= event.turn <= turn_end:
                if event.type in (
                    DurableEventType.USER_MESSAGE,
                    DurableEventType.ASSISTANT_MESSAGE,
                    DurableEventType.TOOL_RESULT,
                ):
                    event.compacted = True
                    count += 1
        return count

    def add_summary(self, turn: int, summary: str) -> DurableEvent:
        """为指定轮次添加会话摘要事件，用于上下文压缩后的信息保留。

        Args:
            turn: 摘要所覆盖的轮次。
            summary: 摘要文本内容。

        Returns:
            创建的摘要事件。
        """
        return self.append(
            DurableEventType.SUMMARY,
            turn=turn,
            data={"message": Message.system(f"[Previous conversation summary]\n{summary}").model_dump(mode="json")},
        )

    def __getitem__(self, index):
        """支持通过索引直接访问日志中的事件。"""
        return self._events[index]