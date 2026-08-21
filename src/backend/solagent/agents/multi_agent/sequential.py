"""Sequential pattern. Reference: crewAI sequential process."""
import logging
from typing import Any

from solagent.schema.messages import Message

_logger = logging.getLogger(__name__)


class SequentialPattern:
    """Execute agents sequentially, passing each result to the next agent."""

    def __init__(self):
        self._agents: list[tuple[str, Any]] = []

    def add_agent(self, name: str, agent) -> "SequentialPattern":
        self._agents.append((name, agent))
        return self

    async def execute(self, tasks: list[dict]) -> list[dict]:
        results: list[dict] = []
        prev_output = ""
        for i, task in enumerate(tasks):
            agent_name = task.get("agent", "")
            task_text = task.get("task", "")
            agent = self._find_agent(agent_name)
            if agent is None:
                _logger.warning("Agent not found: %s", agent_name)
                results.append({"task": task_text, "status": "skipped", "error": f"Agent '{agent_name}' not found"})
                continue
            if prev_output:
                task_text = f"{task_text}\n\nPrevious result:\n{prev_output}"
            agent._ctx.messages = [Message.user(task_text)]
            try:
                result = await agent.run()
                prev_output = result.content
                results.append({"task": task_text, "status": "completed", "output": result.content})
            except Exception as e:  # noqa: BLE001
                _logger.error("Sequential agent %s failed: %s", agent_name, e)
                results.append({"task": task_text, "status": "failed", "error": str(e)})
        return results

    def _find_agent(self, name: str):
        for n, a in self._agents:
            if n == name:
                return a
        return None