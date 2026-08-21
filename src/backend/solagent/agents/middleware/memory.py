"""Memory middleware. Queues memory updates after each turn and flushes to MemoryManager."""
import logging
import uuid
from typing import Any

from solagent.agents.middleware.base import NextFn
from solagent.schema.memory import MemoryCategory, MemoryRecord

_logger = logging.getLogger(__name__)


class MemoryMiddleware:
    def __init__(self, memory_manager: Any | None = None):
        self._pending: list[dict] = []
        self._memory_manager = memory_manager

    async def __call__(self, context: dict, next_fn: NextFn) -> dict:
        result = await next_fn(context)
        user_msg = context.get("user_message", "")
        assistant_msg = result.get("content", "")
        if user_msg or assistant_msg:
            self._pending.append({"user": user_msg, "assistant": assistant_msg})
        if self._memory_manager and len(self._pending) >= 5:
            await self.flush()
        return result

    async def flush(self) -> list[dict]:
        pending = list(self._pending)
        self._pending.clear()
        if self._memory_manager and pending:
            try:
                for entry in pending:
                    content = f"User: {entry.get('user', '')}\nAssistant: {entry.get('assistant', '')}"
                    record = MemoryRecord(
                        id=str(uuid.uuid4()),
                        content=content,
                        category=MemoryCategory.CONVERSATION,
                        importance=0.3,
                        metadata={"user": entry.get("user", ""), "assistant": entry.get("assistant", "")},
                    )
                    await self._memory_manager.add(record)
            except Exception as e:  # noqa: BLE001
                _logger.warning("Memory flush failed: %s", e)
        return pending