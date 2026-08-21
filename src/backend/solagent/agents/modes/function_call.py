"""FunctionCall mode - single-turn native function calling."""
from collections.abc import AsyncIterator

from solagent.agents.base import AgentStep, BaseAgent
from solagent.agents.stream_assembler import StreamAssembler
from solagent.schema.llm import LLMRequest
from solagent.schema.messages import Message


class FunctionCallMode(BaseAgent):
    async def _execute_stream(self) -> AsyncIterator[AgentStep]:
        self._log_step_start(0)
        tool_defs = self.tools.get_definitions() if len(self.tools) > 0 else []
        executor = self._make_executor()

        request = LLMRequest(messages=self._ctx.messages, model=self.config.model,
                            temperature=self.config.temperature, max_tokens=self.config.max_tokens,
                            tools=tool_defs)

        assembler = StreamAssembler()
        async for chunk in self._chat_stream_with_retry(request):
            assembler.push(chunk)
            if chunk.content:
                yield AgentStep(iteration=0, content=chunk.content)

        full_content, calls = assembler.build()

        if not calls:
            self._ctx.messages.append(Message.assistant(full_content))
            self._add_step(0, content=full_content, is_final=True)
            self._log_step_end(0)
            yield AgentStep(iteration=0, content=full_content, is_final=True, finish_reason="stop")
            return

        self._ctx.messages.append(Message.assistant_with_tool_calls(full_content, calls))
        self._add_step(0, tool_calls=[c.model_dump() for c in calls])
        yield AgentStep(iteration=0, tool_calls=[c.model_dump() for c in calls])

        await self._execute_tools_and_append(executor, calls, self._ctx.messages)
        output = "\n".join(r.output for r in self._tool_results[-len(calls):] if calls)
        self._add_step(0, content=output,
                       tool_results=[r.model_dump() for r in self._tool_results[-len(calls):]],
                       is_final=True)
        self._log_step_end(0)
        yield AgentStep(iteration=0, content=output,
                        tool_results=[r.model_dump() for r in self._tool_results[-len(calls):]],
                        is_final=True, finish_reason="tool_calls")