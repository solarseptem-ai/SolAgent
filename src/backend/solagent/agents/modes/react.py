"""ReAct mode - Think -> Act -> Observe -> Repeat."""
from collections.abc import AsyncIterator

from solagent.agents.base import AgentStep, BaseAgent
from solagent.agents.stream_assembler import StreamAssembler
from solagent.errors.loop import MaxIterationError
from solagent.schema.llm import LLMRequest
from solagent.schema.messages import Message, ToolCallBlock

_AUTO_CONTINUE_HINT = (
    "<system-hint>"
    "Your previous turn had text only (no tool calls). "
    "Review the conversation: if the task still needs tools, emit tool_use now; "
    "if it is fully done, reply with a short text only (no tools). "
    "Do not stop with plans or code fences alone when tools are still needed."
    "</system-hint>"
)


class ReActMode(BaseAgent):
    def _intercept_tool_calls(self, calls: list[ToolCallBlock]) -> list[ToolCallBlock]:
        return calls

    async def _execute_stream(self) -> AsyncIterator[AgentStep]:
        tool_defs = self.tools.get_definitions() if len(self.tools) > 0 else []
        executor = self._make_executor()
        auto_continue_count = 0

        for iteration in range(self.config.max_iterations):
            self._log_step_start(iteration)
            is_last = iteration == self.config.max_iterations - 1
            request_tools = [] if is_last else tool_defs
            self._ctx.messages = self._enforce_token_limit(self._ctx.messages)
            request = LLMRequest(messages=self._ctx.messages, model=self.config.model,
                                temperature=self.config.temperature, max_tokens=self.config.max_tokens,
                                tools=request_tools)

            assembler = StreamAssembler()
            thinking_parts: list[str] = []
            async for chunk in self._chat_stream_with_retry(request):
                if chunk.reasoning_content:
                    thinking_parts.append(chunk.reasoning_content)
                    yield AgentStep(iteration=iteration, thinking=chunk.reasoning_content)
                elif chunk.is_thinking and chunk.content:
                    thinking_parts.append(chunk.content)
                    yield AgentStep(iteration=iteration, thinking=chunk.content)
                else:
                    assembler.push(chunk)
                    if chunk.content:
                        yield AgentStep(iteration=iteration, content=chunk.content)

            full_content, calls = assembler.build()

            if not calls:
                if self.config.auto_continue and not is_last and auto_continue_count < self.config.auto_continue_max_extra:
                    auto_continue_count += 1
                    self._ctx.messages.append(Message.assistant(full_content))
                    self._ctx.messages.append(Message.user(_AUTO_CONTINUE_HINT))
                    self._log_step_end(iteration)
                    continue
                self._ctx.messages.append(Message.assistant(full_content))
                self._add_step(iteration, content=full_content, is_final=True)
                self._log_step_end(iteration)
                yield AgentStep(iteration=iteration, content=full_content, is_final=True, finish_reason="stop")
                return

            if is_last:
                self._ctx.messages.append(Message.assistant(
                    f"[WARNING] Max iterations reached. Task may be incomplete.\n{full_content}"))
                self._add_step(iteration,
                               content=f"[WARNING] Max iterations reached. Task may be incomplete.\n{full_content}",
                               is_final=True)
                self._log_step_end(iteration)
                yield AgentStep(iteration=iteration,
                                content=f"[WARNING] Max iterations reached.\n{full_content}",
                                is_final=True, finish_reason="max_iterations")
                return

            auto_continue_count = 0
            calls = self._intercept_tool_calls(calls)
            self._ctx.messages.append(Message.assistant_with_tool_calls(full_content, calls))
            self._add_step(iteration, tool_calls=[c.model_dump() for c in calls])
            yield AgentStep(iteration=iteration, tool_calls=[c.model_dump() for c in calls])

            tool_results = await self._execute_tools_and_append(executor, calls, self._ctx.messages)
            self._add_step(iteration, tool_results=[r.model_dump() for r in tool_results])
            yield AgentStep(iteration=iteration, tool_results=[r.model_dump() for r in tool_results])

            await self._check_termination(self._steps[-1])

            if any(r.metadata.get("return_directly") for r in tool_results):
                self._add_step(iteration, content="Tool completed.", is_final=True)
                self._log_step_end(iteration)
                yield AgentStep(iteration=iteration, content="Tool completed.", is_final=True,
                                finish_reason="return_directly")
                return

            self._log_step_end(iteration)

        raise MaxIterationError(self.config.max_iterations)