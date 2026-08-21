from __future__ import annotations

from datetime import UTC, datetime

from solagent.agents.learning.models import StrategyRule
from solagent.schema.memory import MemoryCategory, MemoryQuery
from solagent.schema.messages import ToolCallBlock


class StrategyEngine:
    def __init__(self, memory_manager):
        self._memory_manager = memory_manager
        self._rules: dict[str, StrategyRule] = {}
        self._active_rules: list[StrategyRule] = []

    async def load_rules(self):
        query = MemoryQuery(
            query="",
            categories=[MemoryCategory.STRATEGY],
            limit=100,
        )
        results = await self._memory_manager.search(query)
        for r in results:
            rule = StrategyRule.from_memory(r.record)
            self._rules[rule.rule_id] = rule
            if rule.status == "active":
                self._active_rules.append(rule)
        self._auto_transition()

    async def match(self, task_signature: str) -> list[StrategyRule]:
        task_lower = task_signature.lower()
        matched: list[StrategyRule] = []
        for rule in self._active_rules:
            keywords = rule.trigger_conditions.get("task_keywords", [])
            if not keywords:
                continue
            if any(kw.lower() in task_lower for kw in keywords):
                matched.append(rule)
        return sorted(matched, key=lambda r: r.success_rate, reverse=True)

    def intercept(self, tool_calls: list[ToolCallBlock]) -> list[ToolCallBlock]:
        for i, call in enumerate(tool_calls):
            for rule in self._active_rules:
                if call.name in rule.deprecated_tools:
                    if rule.recommended_tools:
                        tool_calls[i] = call.model_copy(update={"name": rule.recommended_tools[0]})
        return tool_calls

    def update_success_rate(self, rule_id: str, success: bool):
        rule = self._rules.get(rule_id)
        if not rule:
            return
        rule.use_count += 1
        rule.last_used = datetime.now(UTC)
        n = max(1, rule.use_count)
        rule.success_rate = (rule.success_rate * (n - 1) + int(success)) / n

    def _auto_transition(self):
        now = datetime.now(UTC)
        for rule in self._rules.values():
            days = (now - rule.last_used).days
            if rule.status == "active" and days > 30:
                rule.status = "stale"
            elif rule.status == "stale" and days > 90:
                rule.status = "archived"