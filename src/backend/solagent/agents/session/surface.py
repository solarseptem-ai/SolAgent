from solagent.core.session_log import DurableEvent, DurableEventType
from solagent.schema.messages import Message


class SurfaceManager:
    """从 SessionLog 投影出模型可见的消息序列。

    与 SessionLog.derive_messages() 的区别：
    - derive_messages() 是"全量重建"（从头遍历所有事件）
    - SurfaceManager 是"增量更新"（apply() 增量修改，derive() 返回缓存）
    - SurfaceManager 支持 replace 操作（替换已有消息）

    用法：
        surface = SurfaceManager()
        log = SessionLog()
        log.attach_surface(surface)
        log.append(DurableEventType.USER_MESSAGE, data={"message": msg.model_dump()})
        messages = surface.derive()  # 增量缓存，无需全量重建
    """

    def __init__(self):
        self._messages: list[Message] = []
        self._event_index_to_msg_index: dict[int, int] = {}

    def apply(self, event: DurableEvent, event_index: int) -> None:
        surface_op = getattr(event, 'surface_op', None) or _infer_surface_op(event.type)
        if surface_op == "append":
            msg = self._event_to_message(event)
            self._event_index_to_msg_index[event_index] = len(self._messages)
            self._messages.append(msg)
        elif surface_op == "replace":
            source_indices = getattr(event, 'source_event_indices', None) or []
            for src_idx in source_indices:
                if src_idx in self._event_index_to_msg_index:
                    msg_idx = self._event_index_to_msg_index[src_idx]
                    new_msg = self._event_to_message(event)
                    self._messages[msg_idx] = new_msg
                    self._event_index_to_msg_index[event_index] = msg_idx

    def derive(self) -> list[Message]:
        return list(self._messages)

    def _event_to_message(self, event: DurableEvent) -> Message:
        msg_data = event.data.get("message")
        if msg_data is None:
            raise ValueError(f"event type {event.type} has no message data, cannot convert to Message")
        return Message.model_validate(msg_data)


def _infer_surface_op(event_type: str) -> str | None:
    if event_type in (
        DurableEventType.USER_MESSAGE,
        DurableEventType.ASSISTANT_MESSAGE,
        DurableEventType.TOOL_RESULT,
        DurableEventType.SYSTEM_INJECT,
        DurableEventType.SUMMARY,
    ):
        return "append"
    return None