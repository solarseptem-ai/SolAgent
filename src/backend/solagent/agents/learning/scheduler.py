from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from solagent.schema.memory import MemoryCategory, MemoryQuery
from solagent.schema.messages import TextBlock, ThinkingBlock


class ReflectionScheduler:
    REFLECTION_PROMPT = (
        "Review the following conversation and extract lessons learned.\n"
        "1. What went well? What tools/patterns were effective?\n"
        "2. What went wrong? What should be avoided?\n"
        "3. Are there any reusable patterns that should become a strategy?\n"
        "4. Do any existing strategies need updating?\n\n"
        "Conversation:\n{conversation}"
    )

    DREAM_PROMPT = (
        "You are maintaining the agent's long-term memory. Review all experiences "
        "tagged [permanent] and [durable] since the last Dream run.\n\n"
        "1. Identify recurring patterns across multiple experiences\n"
        "2. For each pattern: create or update a StrategyRule\n"
        "3. Merge similar rules into umbrella rules\n"
        "4. Clean up [ephemeral] experiences older than 7 days\n"
        "5. If a [correction] contradicts an existing [permanent] experience, "
        "   update the [permanent] one\n\n"
        "Experiences:\n{experiences}"
    )

    def __init__(self, memory_manager, provider,
                 threshold_experiences: int = 10,
                 threshold_days: int = 7):
        self._memory_manager = memory_manager
        self._provider = provider
        self._threshold_experiences = threshold_experiences
        self._threshold_days = threshold_days
        self._pending_count = 0
        self._last_reflection: datetime | None = None

    def should_reflect(self) -> bool:
        if self._pending_count >= self._threshold_experiences:
            return True
        if self._last_reflection and (
            datetime.now(UTC) - self._last_reflection
        ).days >= self._threshold_days:
            return True
        return False

    def notify_experience(self):
        self._pending_count += 1

    async def spawn_background_review(self, conversation: list):
        if not self.should_reflect():
            return
        self._pending_count = 0
        asyncio.create_task(self._run_reflection(conversation))

    def _extract_text(self, msg) -> str:
        roles = []
        for block in msg.content:
            if isinstance(block, TextBlock):
                if block.text:
                    roles.append(block.text)
            elif isinstance(block, ThinkingBlock):
                if block.thinking:
                    roles.append(block.thinking)
        return " ".join(roles)

    async def _run_reflection(self, conversation: list):
        try:
            text = "\n".join([
                self._extract_text(m) for m in conversation
                if hasattr(m, "content") and m.content
            ])
            await self._provider.chat(
                self.REFLECTION_PROMPT.format(conversation=text)
            )
            self._last_reflection = datetime.now(UTC)
            self._pending_count = 0

            if await self._should_trigger_dream():
                await self._run_dream()
        except Exception:
            _logger = logging.getLogger(__name__)
            _logger.warning("Reflection run failed", exc_info=True)

    async def _should_trigger_dream(self) -> bool:
        query = MemoryQuery(
            query="",
            categories=[MemoryCategory.EXPERIENCE],
            limit=100,
        )
        results = await self._memory_manager.search(query)
        permanent_count = sum(
            1 for r in results
            if r.record.metadata.get("tag") == "permanent"
        )
        return permanent_count >= 20

    async def _run_dream(self):
        query = MemoryQuery(
            query="",
            categories=[MemoryCategory.EXPERIENCE],
            limit=200,
        )
        results = await self._memory_manager.search(query)
        experiences = [
            r.record for r in results
            if r.record.metadata.get("tag") in ("permanent", "durable")
        ]
        if not experiences:
            return

        exp_text = "\n\n".join([
            f"[{e.metadata.get('tag', 'durable')}] {e.content}\n"
            f"  Outcome: {e.metadata.get('outcome', 'unknown')}\n"
            f"  Lesson: {e.metadata.get('lesson', 'N/A')}"
            for e in experiences
        ])

        await self._provider.chat(self.DREAM_PROMPT.format(experiences=exp_text))
