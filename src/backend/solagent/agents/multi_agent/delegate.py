"""Delegate pattern. Reference: hermes-agent delegate_task tool."""
import logging
from typing import Any

from solagent.schema.messages import Message

_logger = logging.getLogger(__name__)


class DelegatePattern:
    """Delegate tasks to named agents based on task routing rules."""

    def __init__(self):
        self._agents: dict[str, Any] = {}
        self._routing: dict[str, str] = {}

    def register_agent(self, name: str, agent) -> "DelegatePattern":
        self._agents[name] = agent
        return self

    def set_routing(self, keyword: str, agent_name: str) -> "DelegatePattern":
        self._routing[keyword.lower()] = agent_name
        return self

    async def execute(self, tasks: list[dict]) -> list[dict]:
        results: list[dict] = []
        for task in tasks:
            task_text = task.get("task", "") if isinstance(task, dict) else str(task)
            agent_name = self._route(task_text)
            if agent_name not in self._agents:
                _logger.warning("No agent for task: %s", task_text[:80])
                results.append({"task": task_text, "status": "skipped", "error": "No matching agent"})
                continue
            agent = self._agents[agent_name]
            agent._ctx.messages = [Message.user(task_text)]
            try:
                result = await agent.run()
                results.append({"task": task_text, "status": "completed", "agent": agent_name, "output": result.content})
            except Exception as e:  # noqa: BLE001
                _logger.error("Delegate agent %s failed: %s", agent_name, e)
                results.append({"task": task_text, "status": "failed", "agent": agent_name, "error": str(e)})
        return results

    def _route(self, task_text: str) -> str:
        text_lower = task_text.lower()
        for keyword, agent_name in self._routing.items():
            if keyword in text_lower:
                return agent_name
        return next(iter(self._agents), "")