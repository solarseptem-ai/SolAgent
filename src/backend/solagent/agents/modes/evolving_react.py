from __future__ import annotations

from solagent.agents.base import AgentContext
from solagent.agents.learning.consolidator import Consolidator
from solagent.agents.learning.extractor import ExperienceExtractor
from solagent.agents.learning.retriever import ExperienceRetriever
from solagent.agents.learning.scheduler import ReflectionScheduler
from solagent.agents.learning.strategy import StrategyEngine
from solagent.agents.modes.react import ReActMode
from solagent.schema.agent import AgentResult
from solagent.schema.messages import Message, ToolCallBlock


class EvolvingReAct(ReActMode):
    def __init__(self, ctx: AgentContext):
        super().__init__(ctx)
        self._memory = ctx.memory
        self._provider = ctx.provider
        self._retriever = ExperienceRetriever(self._memory)
        self._strategy = StrategyEngine(self._memory)
        self._extractor = ExperienceExtractor(self._memory, self._provider)
        self._consolidator = Consolidator(self._provider)
        self._scheduler = ReflectionScheduler(self._memory, self._provider)

    def _intercept_tool_calls(self, calls: list[ToolCallBlock]) -> list[ToolCallBlock]:
        return self._strategy.intercept(calls)

    async def _execute(self) -> AgentResult:
        await self._strategy.load_rules()
        task = self._extract_task(self._ctx.messages)
        experiences = await self._retriever.retrieve(task)
        strategies = await self._strategy.match(task)
        if experiences:
            self._inject_experiences(experiences)
        if strategies:
            self._inject_strategies(strategies)
        result = await super()._execute()
        await self._post_execute(result)
        return result

    async def _post_execute(self, result: AgentResult):
        experience = await self._extractor.extract(result, self._ctx.messages)
        await self._extractor.persist(experience)

        await self._consolidator.consolidate(self._ctx.messages)

        self._scheduler.notify_experience()
        await self._scheduler.spawn_background_review(self._ctx.messages)

    def _extract_task(self, messages: list[Message]) -> str:
        for msg in messages:
            if msg.role == "user":
                content = msg.content
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    parts = []
                    for block in content:
                        t = getattr(block, "text", None)
                        if t:
                            parts.append(str(t))
                    return " ".join(parts) if parts else ""
        return ""

    def _inject_experiences(self, experiences):
        if not experiences:
            return
        for msg in self._ctx.messages[1:4]:
            if hasattr(msg, "content") and "Relevant Past Experiences" in str(msg.content):
                return
        exp_text = "\n".join([
            f"- [{e.tag.value}] {e.task_signature}: {e.lesson or 'See details'}"
            for e in experiences[:3]
        ])
        system_msg = Message.system(
            f"## Relevant Past Experiences\n{exp_text}\n\n"
            "Use these experiences to guide your approach. Avoid patterns that failed before."
        )
        self._ctx.messages.insert(1, system_msg)

    def _inject_strategies(self, strategies):
        if not strategies:
            return
        for msg in self._ctx.messages[1:4]:
            if hasattr(msg, "content") and "Active Strategies" in str(msg.content):
                return
        strat_text = "\n".join([
            f"- {s.description} (success rate: {s.success_rate:.0%})"
            for s in strategies[:3]
        ])
        system_msg = Message.system(
            f"## Active Strategies\n{strat_text}\n\n"
            "Follow these strategies when selecting tools."
        )
        self._ctx.messages.insert(1, system_msg)