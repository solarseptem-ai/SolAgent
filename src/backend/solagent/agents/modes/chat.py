"""Chat mode - simple conversation, no tools, no loop."""
from collections.abc import AsyncIterator

from solagent.agents.base import AgentStep, BaseAgent
from solagent.schema.llm import LLMRequest
from solagent.schema.messages import Message


class ChatMode(BaseAgent):
    async def _execute_stream(self) -> AsyncIterator[AgentStep]:
        request = LLMRequest(messages=self._ctx.messages, model=self.config.model,
                            temperature=self.config.temperature, max_tokens=self.config.max_tokens)
        content_parts: list[str] = []
        async for chunk in self._chat_stream_with_retry(request):
            if chunk.reasoning_content:
                yield AgentStep(iteration=0, thinking=chunk.reasoning_content)
            elif chunk.content:
                content_parts.append(chunk.content)
                yield AgentStep(iteration=0, content=chunk.content)
        full_content = "".join(content_parts)
        self._ctx.messages.append(Message.assistant(full_content))
        self._add_step(0, content=full_content, is_final=True)
        yield AgentStep(iteration=0, content=full_content, is_final=True, finish_reason="stop")