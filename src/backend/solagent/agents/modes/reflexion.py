"""Reflexion mode with structured self-criticism."""
import asyncio
import logging
from collections.abc import AsyncIterator

from solagent.agents.base import AgentStep, BaseAgent
from solagent.agents.modes.react import ReActMode
from solagent.llms.structured import StructuredOutputError, StructuredOutputPipeline
from solagent.schema.messages import Message
from solagent.schema.structured import ReflexionModel

_logger = logging.getLogger(__name__)


class ReflexionMode(BaseAgent):
    REFLECTION_PROMPT = (
        "Previous attempt failed or was incomplete. Analyze what went wrong, then suggest a better approach. "
        'Output as JSON: {"analysis": "what went wrong", "new_approach": "what to do differently"}'
    )

    async def _execute_stream(self) -> AsyncIterator[AgentStep]:
        max_attempts = min(self.config.max_iterations, 3)
        reflections = []

        for attempt in range(max_attempts):
            self._log_step_start(attempt)
            yield AgentStep(iteration=attempt, content=f"\n--- Attempt {attempt + 1}/{max_attempts} ---")

            react = ReActMode(self._ctx)
            inner_success = False
            try:
                async for step in react._execute_stream():
                    yield step
                    if step.is_final:
                        if step.finish_reason != "error" and step.content:
                            inner_success = True
                            self._add_step(attempt, content=step.content, is_final=True)
                            self._log_step_end(attempt)
                            yield AgentStep(iteration=attempt, content=step.content,
                                            is_final=True, finish_reason="stop")
                            return
                        # Inner step indicates error or empty — fall through to reflection
                        reflections.append(f"Attempt {attempt + 1}: returned empty or error")
            except Exception as e:
                if isinstance(e, (KeyboardInterrupt, SystemExit, asyncio.CancelledError)):
                    raise
                _logger.warning("Reflexion attempt %d failed: %s", attempt + 1, e)
                reflections.append(f"Attempt {attempt + 1}: {e}")

            if inner_success:
                return  # Should not reach here, but just in case

            if attempt < max_attempts - 1:
                reflection_text = "\n".join(reflections)
                pipeline = StructuredOutputPipeline(self._ctx.provider, max_retries=2)
                try:
                    reflexion = await pipeline.generate(
                        f"{self.REFLECTION_PROMPT}\n\nHistory:\n{reflection_text}",
                        ReflexionModel,
                        system_prompt="You are a critical analyst. Be specific and actionable.",
                    )
                    self._ctx.messages.append(Message.user(
                        f"Analysis: {reflexion.analysis}\nNew approach: {reflexion.new_approach}"
                    ))
                    yield AgentStep(iteration=attempt, content=f"[Reflection] {reflexion.analysis}")
                except StructuredOutputError:
                    self._ctx.messages.append(Message.user(
                        f"Reflection: {reflection_text}\nTry again with a different approach."
                    ))
                self._ctx.messages.append(Message.user("Try again with the improved approach."))

            self._log_step_end(attempt)

        self._add_step(max_attempts, content="All attempts failed after reflection", is_final=True)
        yield AgentStep(iteration=max_attempts, content="All attempts failed after reflection",
                        is_final=True, finish_reason="error")