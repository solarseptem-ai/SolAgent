"""Agent 消息收件箱（Inbox）模块。

提供 next-turn 和 next-step 双队列路由机制，用于管理 Agent 执行过程中
需要延迟处理的消息（如新 turn 的用户输入、当前 turn 的工具结果注入）。
所有变更操作先写入 SessionLog（INBOX_SPLICED 事件）再修改内存状态，
支持从事件日志重建 Inbox，实现崩溃恢复。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from solagent.schema.messages import Message

if TYPE_CHECKING:
    from solagent.core.session_log import SessionLog


@dataclass
class Inbox:
    """Agent 双队列消息收件箱。

    维护两个内部队列：
    - next-turn: 新 turn 开始时 claim，通常存放用户新消息。
    - next-step: 当前 turn 的下一步 claim，通常存放需要注入的工具结果。

    所有变更先持久化到 SessionLog，再修改内存，确保可恢复性。
    """

    _next_turn: list[Message] = field(default_factory=list)
    _next_step: list[Message] = field(default_factory=list)
    _session_log: SessionLog | None = field(default=None, repr=False)

    def _log_splice(self, op: str, target: str, deleted: int = 0, inserted: list[dict] | None = None) -> None:
        if self._session_log is None:
            return
        from solagent.core.session_log import DurableEventType

        self._session_log.append(
            DurableEventType.INBOX_SPLICED,
            data={
                "op": op,
                "target": target,
                "deleted": deleted,
                "inserted": inserted or [],
            },
        )

    def claim(self) -> list[Message]:
        """取出所有 next-step 消息以及一条 next-turn 消息。

        返回:
            按顺序组合的消息列表（next-step 在前，next-turn 在后）。
        """
        step_messages = list(self._next_step)
        self._next_step.clear()
        if step_messages:
            self._log_splice("claim", "next-step", deleted=len(step_messages),
                             inserted=[m.model_dump(mode="json") for m in step_messages])

        turn_messages: list[Message] = []
        if self._next_turn:
            turn_messages = [self._next_turn.pop(0)]
            self._log_splice("claim", "next-turn", deleted=1,
                             inserted=[m.model_dump(mode="json") for m in turn_messages])

        return step_messages + turn_messages

    def claim_next_turn(self) -> list[Message]:
        """仅取出一条 next-turn 消息，不触及 next-step 队列。

        返回:
            包含一条消息的列表；队列为空时返回空列表。
        """
        if self._next_turn:
            msg = self._next_turn.pop(0)
            self._log_splice("claim", "next-turn", deleted=1,
                             inserted=[msg.model_dump(mode="json")])
            return [msg]
        return []

    def claim_next_step(self) -> list[Message]:
        """仅取出所有 next-step 消息，不触及 next-turn 队列。

        返回:
            next-step 队列中的全部消息列表。
        """
        result = list(self._next_step)
        self._next_step.clear()
        if result:
            self._log_splice("claim", "next-step", deleted=len(result),
                             inserted=[m.model_dump(mode="json") for m in result])
        return result

    def append(self, target: str, message: Message) -> None:
        """向指定队列追加单条消息。

        参数:
            target: 目标队列（"next-turn" 或 "next-step"）。
            message: 要追加的消息对象。

        异常:
            ValueError: target 不是合法队列名称。
        """
        self._log_splice("append", target, inserted=[message.model_dump(mode="json")])
        if target == "next-turn":
            self._next_turn.append(message)
        elif target == "next-step":
            self._next_step.append(message)
        else:
            raise ValueError(f"Unknown inbox target: {target}")

    def splice(self, target: str, messages: list[Message], position: int | None = None) -> None:
        """在指定队列的指定位置插入一批消息。

        参数:
            target: 目标队列（"next-turn" 或 "next-step"）。
            messages: 要插入的消息列表。
            position: 插入位置索引，None 表示追加到末尾。
        """
        self._log_splice("splice", target, inserted=[m.model_dump(mode="json") for m in messages])
        queue = self._next_turn if target == "next-turn" else self._next_step
        if position is None:
            queue.extend(messages)
        else:
            for i, msg in enumerate(messages):
                queue.insert(position + i, msg)

    def replace(self, target: str, index: int, message: Message) -> None:
        """替换指定队列中某位置的消息。

        参数:
            target: 目标队列（"next-turn" 或 "next-step"）。
            index: 要替换的消息索引。
            message: 新的消息对象。
        """
        queue = self._next_turn if target == "next-turn" else self._next_step
        if 0 <= index < len(queue):
            self._log_splice("replace", target, deleted=1, inserted=[message.model_dump(mode="json")])
            queue[index] = message

    def remove(self, target: str, index: int) -> None:
        """移除指定队列中某位置的消息。

        参数:
            target: 目标队列（"next-turn" 或 "next-step"）。
            index: 要移除的消息索引。
        """
        queue = self._next_turn if target == "next-turn" else self._next_step
        if 0 <= index < len(queue):
            msg = queue.pop(index)
            self._log_splice("remove", target, deleted=1, inserted=[msg.model_dump(mode="json")])

    def clear(self) -> None:
        """清空两个队列中的所有消息。"""
        if self._next_turn:
            self._log_splice("clear", "next-turn", deleted=len(self._next_turn))
        if self._next_step:
            self._log_splice("clear", "next-step", deleted=len(self._next_step))
        self._next_turn.clear()
        self._next_step.clear()

    @property
    def has_pending(self) -> bool:
        """是否存在尚未被 claim 的待处理消息。"""
        return bool(self._next_turn) or bool(self._next_step)

    @property
    def pending_count(self) -> int:
        """待处理消息的总数。"""
        return len(self._next_turn) + len(self._next_step)

    def __len__(self) -> int:
        """返回待处理消息总数，与 pending_count 一致。"""
        return self.pending_count

    @classmethod
    def from_session_log(cls, log: SessionLog | None) -> Inbox:
        """从 SessionLog 事件流重建 Inbox 状态，用于崩溃后恢复。

        参数:
            log: SessionLog 实例，若为 None 则返回空的 Inbox。

        返回:
            重建后的 Inbox 实例。
        """
        inbox = cls()
        if log is None:
            return inbox
        from solagent.core.session_log import DurableEventType

        inbox._session_log = log
        for event in log.replay():
            if event.type != DurableEventType.INBOX_SPLICED:
                continue
            op = event.data.get("op")
            target = event.data.get("target")
            queue = inbox._next_turn if target == "next-turn" else inbox._next_step
            if op == "append":
                for msg_data in event.data.get("inserted", []):
                    queue.append(Message.model_validate(msg_data))
            elif op == "clear":
                queue.clear()
            elif op == "claim":
                deleted = event.data.get("deleted", 0)
                for _ in range(deleted):
                    if queue:
                        queue.pop(0)
            elif op == "remove":
                deleted = event.data.get("deleted", 0)
                for _ in range(deleted):
                    if queue:
                        queue.pop()
            elif op == "replace":
                if queue:
                    queue.pop(0)
                    for msg_data in event.data.get("inserted", []):
                        queue.insert(0, Message.model_validate(msg_data))
        return inbox