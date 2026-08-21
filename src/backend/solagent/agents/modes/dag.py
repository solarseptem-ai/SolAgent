"""DAG orchestration mode: topological sort + parallel execution + data flow + error recovery.

Reference: LangGraph StateGraph, Prefect Flow, Airflow DAG.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from solagent.agents.base import AgentStep, BaseAgent
from solagent.agents.dag.executor import DAGExecutor
from solagent.llms.structured import StructuredOutputError, StructuredOutputPipeline
from solagent.schema.llm import LLMRequest
from solagent.schema.messages import Message
from solagent.schema.structured import DAGModel

_logger = logging.getLogger(__name__)


class DAGAgent(BaseAgent):
    DAG_PROMPT = (
        "Output a JSON array of DAG steps. Each step must have: id, tool, args, depends_on.\n"
        "Optional: description, input_mapping (Jinja2 templates), condition, on_error, retry_policy.\n"
        'Example: {"steps": [{"id": "1", "tool": "read", "args": {"path": "data.txt"}, "depends_on": []}, '
        '{"id": "2", "tool": "shell", "args": {"command": "cat data.txt"}, "depends_on": ["1"]}]}'
    )

    async def _execute_stream(self) -> AsyncIterator[AgentStep]:
        tool_defs = self.tools.get_definitions() if len(self.tools) > 0 else []

        dag = await self._generate_dag(self._ctx.messages, tool_defs)
        if dag is None:
            self._add_step(0, content="DAG generation failed", is_final=True)
            yield AgentStep(iteration=0, content="DAG generation failed", is_final=True, finish_reason="error")
            return

        yield AgentStep(iteration=0, content=f"DAG: {len(dag.steps)} steps, generating plan...")

        executor = DAGExecutor(self.tools, self._make_executor)
        step_idx = 0
        async for event in executor.execute_stream(dag):
            step_idx += 1
            yield AgentStep(iteration=step_idx, content=event.message)

        plan_json = dag.model_dump_json(indent=2)
        self._ctx.messages.append(Message.assistant(f"DAG Plan:\n{plan_json}"))
        self._add_step(step_idx + 1, content="DAG execution complete", is_final=True)
        yield AgentStep(iteration=step_idx + 1, content="DAG execution complete", is_final=True, finish_reason="stop")

    async def _generate_dag(self, messages: list[Message], tool_defs: list) -> DAGModel | None:
        dag_messages = list(messages) + [Message.user(self.DAG_PROMPT)]
        dag_request = LLMRequest(
            messages=dag_messages, model=self.config.model,
            temperature=0.0, max_tokens=2000, tools=tool_defs,
        )
        pipeline = StructuredOutputPipeline(self._ctx.provider, max_retries=2)
        try:
            dag = await pipeline.generate(dag_request, DAGModel)
            if pipeline.last_usage:
                self._total_usage = self._total_usage + pipeline.last_usage
            return dag
        except StructuredOutputError as e:
            _logger.error("Failed to parse DAG: %s", e)
            return None