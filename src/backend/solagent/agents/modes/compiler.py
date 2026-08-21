"""LLM Compiler mode with structured output pipeline."""
import logging
from collections.abc import AsyncIterator

from solagent.agents.base import AgentStep, BaseAgent
from solagent.agents.stream_assembler import StreamAssembler
from solagent.llms.structured import StructuredOutputError, StructuredOutputPipeline
from solagent.schema.llm import LLMRequest
from solagent.schema.messages import Message, ToolCallBlock
from solagent.schema.structured import DAGModel

_logger = logging.getLogger(__name__)


class CompilerMode(BaseAgent):
    DAG_PROMPT = (
        'Output a JSON array of parallel tool calls: '
        '{"steps": [{"id": "1", "tool": "name", "args": {}, "depends_on": []}]}'
    )

    async def _execute_stream(self) -> AsyncIterator[AgentStep]:
        self._log_step_start(0)
        tool_defs = self.tools.get_definitions() if len(self.tools) > 0 else []
        executor = self._make_executor()

        dag_messages = list(self._ctx.messages) + [Message.user(self.DAG_PROMPT)]
        dag_request = LLMRequest(
            messages=dag_messages, model=self.config.model,
            temperature=0.0, max_tokens=1000, tools=tool_defs,
        )

        assembler = StreamAssembler()

        async for chunk in self._chat_stream_with_retry(dag_request):
            assembler.push(chunk)
            if chunk.content:
                yield AgentStep(iteration=0, content=chunk.content)

        _, calls = assembler.build()

        if calls:
            self._add_step(0, tool_calls=[c.model_dump() for c in calls])
            yield AgentStep(iteration=0, tool_calls=[c.model_dump() for c in calls])
            await self._execute_tools_and_append(executor, calls, self._ctx.messages)
            output = "DAG execution completed"
            self._ctx.messages.append(Message.assistant(output))
            self._add_step(0, content=output, is_final=True)
            self._log_step_end(0)
            yield AgentStep(iteration=0, content=output, is_final=True, finish_reason="stop")
            return

        pipeline = StructuredOutputPipeline(self._ctx.provider, max_retries=2)
        try:
            dag = await pipeline.generate(dag_request, DAGModel)
        except StructuredOutputError as e:
            _logger.error("Failed to parse DAG: %s", e)
            output = f"DAG parse error: {e}"
            self._ctx.messages.append(Message.assistant(output))
            self._add_step(0, content=output, is_final=True)
            self._log_step_end(0)
            yield AgentStep(iteration=0, content=output, is_final=True, finish_reason="error")
            return

        yield AgentStep(iteration=0, content=f"\nDAG: {len(dag.steps)} steps")

        executed: set[str] = set()
        max_iter = max(len(dag.steps) * 2, self.config.max_iterations * 2)
        iterations = 0

        while len(executed) < len(dag.steps) and iterations < max_iter:
            iterations += 1
            ready = [
                s for s in dag.steps
                if s.id not in executed and all(d in executed for d in s.depends_on)
            ]
            if not ready and len(executed) < len(dag.steps):
                unresolved = [s for s in dag.steps if s.id not in executed]
                _logger.warning("DAG has %d unresolved steps, likely cyclic: %s", len(unresolved), [s.id for s in unresolved])
                ready = unresolved

            batch_calls = []
            for step in ready:
                if step.tool and self.tools.has(step.tool):
                    batch_calls.append(ToolCallBlock(
                        type="tool_call", id=step.id, name=step.tool, arguments=step.args,
                    ))
            if batch_calls:
                batch_info = [{"id": c.id, "name": c.name} for c in batch_calls]
                self._add_step(iterations, tool_calls=batch_info)
                yield AgentStep(iteration=iterations, tool_calls=batch_info)
                await self._execute_tools_and_append(executor, batch_calls, self._ctx.messages)
            for step in ready:
                executed.add(step.id)
            self._add_step(iterations, content=f"DAG step {len(executed)}/{len(dag.steps)}")
            await self._check_termination(self._steps[-1])

        if len(executed) < len(dag.steps):
            _logger.error("DAG execution incomplete: %d/%d steps after %d iterations", len(executed), len(dag.steps), iterations)

        output = "DAG execution completed"
        self._ctx.messages.append(Message.assistant(output))
        self._add_step(iterations, content=output, is_final=True)
        self._log_step_end(0)
        yield AgentStep(iteration=iterations, content=output, is_final=True, finish_reason="stop")