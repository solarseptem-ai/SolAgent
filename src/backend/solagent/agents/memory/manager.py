"""Memory manager. Orchestrates multiple providers. Reference: hermes-agent MemoryManager, crewAI unified memory."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from solagent.agents.memory.provider import MemoryProvider
from solagent.events.types import AgentEventType
from solagent.schema.memory import MemoryQuery, MemoryRecord, MemorySearchResult

if TYPE_CHECKING:
    from solagent.events.bus import EventBus

_logger = logging.getLogger(__name__)


class MemoryManager:
    def __init__(self, event_bus: EventBus | None = None):
        self._providers: list[MemoryProvider] = []
        self._event_bus = event_bus

    def register(self, provider: MemoryProvider) -> None:
        self._providers.append(provider)

    async def add(self, record: MemoryRecord) -> None:
        for p in self._providers:
            try:
                await p.add(record)
            except Exception:
                _logger.warning("Memory add failed for provider %s", type(p).__name__, exc_info=True)
        if self._event_bus:
            from solagent.events.types import AgentEvent as _AgentEvent
            self._event_bus.emit(_AgentEvent(
                event_type=AgentEventType.MEMORY_ADD,
                data={"memory_id": record.id, "category": str(record.category), "content": record.content[:200]},
            ))

    async def search(self, query: MemoryQuery) -> list[MemorySearchResult]:
        results = []
        for p in self._providers:
            try:
                results.extend(await p.search(query))
            except Exception:
                _logger.warning("Memory search failed for provider %s", type(p).__name__, exc_info=True)
        results.sort(key=lambda r: r.score, reverse=True)
        final_results = results[:query.limit]
        if self._event_bus:
            from solagent.events.types import AgentEvent as _AgentEvent
            self._event_bus.emit(_AgentEvent(
                event_type=AgentEventType.MEMORY_QUERY,
                data={"query": query.query, "categories": query.categories, "result_count": len(final_results)},
            ))
        return final_results

    async def system_prompt_block(self) -> str:
        blocks = []
        for p in self._providers:
            try:
                block = await p.system_prompt_block()
                if block:
                    blocks.append(block)
            except Exception:
                _logger.warning("Memory system_prompt_block failed for provider %s", type(p).__name__, exc_info=True)
        return "\n".join(blocks)

    async def delete(self, memory_id: str) -> bool:
        for p in self._providers:
            try:
                if await p.delete(memory_id):
                    return True
            except Exception:
                _logger.warning("Memory delete failed for provider %s", type(p).__name__, exc_info=True)
        return False

    async def clear(self) -> None:
        for p in self._providers:
            try:
                await p.clear()
            except Exception:
                _logger.warning("Memory clear failed for provider %s", type(p).__name__, exc_info=True)