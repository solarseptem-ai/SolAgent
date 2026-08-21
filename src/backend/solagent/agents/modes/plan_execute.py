"""Plan-Execute mode with state machine and replanning.

State machine:
  PLANNING → EXECUTING → RETRYING → REPLANNING → EXECUTING
                                          ↓ (max replans)
                                        FAILED
                                          ↓
                                        DONE
"""
import json
import logging
from collections.abc import AsyncIterator
from enum import Enum, auto

from solagent.agents.base import AgentStep, BaseAgent
from solagent.events.types import AgentEventType
from solagent.llms.structured import StructuredOutputError, StructuredOutputPipeline
from solagent.schema.llm import LLMRequest
from solagent.schema.messages import Message, ToolCallBlock, ToolResultBlock
from solagent.schema.structured import PlanModel, PlanStep

_logger = logging.getLogger(__name__)


class _PlanState(Enum):
    PLANNING = auto()
    EXECUTING = auto()
    RETRYING = auto()
    REPLANNING = auto()
    DONE = auto()
    FAILED = auto()


class PlanExecuteMode(BaseAgent):
    PLANNING_PROMPT = (
        "Create a step-by-step plan. Output as JSON: "
        '{"steps": [{"step": 1, "action": "description", "tool": "tool_name", "args": {...}}]}'
    )
    _MAX_STEP_RETRIES = 1
    _MAX_STALL_COUNT = 3

    async def _execute_stream(self) -> AsyncIterator[AgentStep]:
        await self._emit_event(AgentEventType.PLAN_START, {"mode": "plan_execute"})
        executor = self._make_executor()
        max_replans = self.config.max_replans
        step_results = []
        replan_count = 0
        stall_count = 0

        steps = await self._generate_plan(self._ctx.messages)
        if steps is None:
            self._add_step(0, content="Plan generation failed", is_final=True)
            yield AgentStep(iteration=0, content="Plan generation failed", is_final=True, finish_reason="error")
            return

        plan_summary = json.dumps([s.model_dump() for s in steps], ensure_ascii=False)
        self._ctx.messages.append(Message.assistant(f"Plan: {plan_summary}"))
        yield AgentStep(iteration=0, content=f"\nPlan: {plan_summary}")

        state = _PlanState.EXECUTING
        current_step_idx = 0
        step_retry_count = 0

        while state not in (_PlanState.DONE, _PlanState.FAILED):
            self._log_step_start(current_step_idx)
            if state == _PlanState.EXECUTING:
                if current_step_idx >= len(steps):
                    state = _PlanState.DONE
                    self._log_step_end(current_step_idx)
                    continue

                step = steps[current_step_idx]
                await self._emit_event(AgentEventType.PLAN_STEP, {"step": step.step, "action": step.action})

                if step.tool and self.tools.has(step.tool):
                    call = ToolCallBlock(
                        type="tool_call", id=f"step_{step.step}",
                        name=step.tool, arguments=step.args,
                    )
                    yield AgentStep(iteration=current_step_idx + 1,
                                    tool_calls=[{"id": f"step_{step.step}", "name": step.tool,
                                                 "arguments": str(step.args)}])
                    results = await executor.execute_sequential([call])
                    for r in results:
                        self._ctx.messages.append(Message.tool_result([
                            ToolResultBlock(type="tool_result", tool_call_id=r.call_id, content=r.output,
                                            is_error=r.is_error)
                        ]))
                        step_results.append(f"Step {step.step}: {r.output}")
                        yield AgentStep(iteration=current_step_idx + 1, content=r.output,
                                        tool_results=[r.model_dump()])
                        if r.is_error:
                            state = _PlanState.RETRYING
                            step_retry_count = 0
                            break
                        else:
                            current_step_idx += 1
                            step_retry_count = 0
                else:
                    step_results.append(f"Step {step.step}: {step.action}")
                    yield AgentStep(iteration=current_step_idx + 1, content=step.action)
                    current_step_idx += 1
                    step_retry_count = 0

                self._add_step(current_step_idx, content=str(step_results[-1]) if step_results else "")
                await self._check_termination(self._steps[-1])

            elif state == _PlanState.RETRYING:
                if current_step_idx >= len(steps):
                    state = _PlanState.DONE
                    self._log_step_end(current_step_idx)
                    continue
                step = steps[current_step_idx]
                if step_retry_count < self._MAX_STEP_RETRIES and step.tool and self.tools.has(step.tool):
                    step_retry_count += 1
                    _logger.info("Stream retrying step %d (attempt %d)", step.step, step_retry_count + 1)
                    call = ToolCallBlock(
                        type="tool_call", id=f"step_{step.step}_retry{step_retry_count}",
                        name=step.tool, arguments=step.args,
                    )
                    yield AgentStep(iteration=current_step_idx + 1,
                                    tool_calls=[{"id": f"step_{step.step}_retry{step_retry_count}",
                                                 "name": step.tool, "arguments": str(step.args)}])
                    results = await executor.execute_sequential([call])
                    for r in results:
                        self._ctx.messages.append(Message.tool_result([
                            ToolResultBlock(type="tool_result", tool_call_id=r.call_id, content=r.output,
                                            is_error=r.is_error)
                        ]))
                        step_results.append(f"Step {step.step}: {r.output}")
                        yield AgentStep(iteration=current_step_idx + 1, content=r.output,
                                        tool_results=[r.model_dump()])
                        if r.is_error:
                            state = _PlanState.REPLANNING
                        else:
                            current_step_idx += 1
                            step_retry_count = 0
                            state = _PlanState.EXECUTING
                else:
                    state = _PlanState.REPLANNING

            elif state == _PlanState.REPLANNING:
                if replan_count >= max_replans:
                    _logger.warning("Max replans (%d) exceeded in stream", max_replans)
                    self._ctx.messages.append(Message.user(f"Max replans ({max_replans}) exceeded. Execution stopped."))
                    state = _PlanState.FAILED
                    continue

                replan_count += 1
                remaining = steps[current_step_idx:]
                error_msg = step_results[-1] if step_results else "unknown error"
                _logger.info("Stream replanning (%d/%d) remaining %d steps", replan_count, max_replans, len(remaining))

                self._ctx.messages.append(Message.user(
                    f"Step failed: {error_msg}. Replanning remaining steps ({replan_count}/{max_replans})."
                ))
                new_steps = await self._replan(remaining, error_msg, self._ctx.messages)

                if new_steps == remaining:
                    stall_count += 1
                    if stall_count >= self._MAX_STALL_COUNT:
                        _logger.warning("Stream replan stalled %d times", stall_count)
                        self._ctx.messages.append(Message.user("Replanning stalled — same steps returned repeatedly."))
                        state = _PlanState.FAILED
                        continue
                else:
                    stall_count = 0

                steps = list(steps[:current_step_idx]) + new_steps
                current_step_idx = 0
                yield AgentStep(iteration=0,
                                content=f"\nReplan ({replan_count}/{max_replans}): {json.dumps([s.model_dump() for s in new_steps], ensure_ascii=False)}")
                state = _PlanState.EXECUTING

            self._log_step_end(current_step_idx)

        summary = "\n".join(step_results)
        self._ctx.messages.append(Message.assistant(summary))
        await self._emit_event(AgentEventType.PLAN_END, {"steps_completed": len(step_results)})
        finish = "error" if state == _PlanState.FAILED else "stop"
        self._add_step(len(steps), content=summary, is_final=True)
        yield AgentStep(iteration=len(steps), content=summary, is_final=True, finish_reason=finish)

    async def _generate_plan(self, messages: list[Message]) -> list[PlanStep] | None:
        tool_defs = self.tools.get_definitions() if len(self.tools) > 0 else []
        plan_messages = list(messages) + [Message.user(self.PLANNING_PROMPT)]
        plan_request = LLMRequest(
            messages=plan_messages, model=self.config.model,
            temperature=0.0, max_tokens=1000, tools=tool_defs,
        )
        pipeline = StructuredOutputPipeline(self._ctx.provider, max_retries=2)
        try:
            plan = await pipeline.generate(plan_request, PlanModel)
        except StructuredOutputError as e:
            _logger.warning("Failed to parse plan: %s", e)
            plan = PlanModel(steps=[PlanStep(step=1, action="execute task", tool="", args={})])

        if pipeline.last_usage:
            self._total_usage = self._total_usage + pipeline.last_usage

        steps = list(plan.steps[:self.config.max_iterations])
        if len(plan.steps) > self.config.max_iterations:
            _logger.warning("Plan truncated: %d steps beyond max_iterations %d",
                            len(plan.steps) - self.config.max_iterations, self.config.max_iterations)
        return steps

    async def _replan(self, remaining_steps: list[PlanStep], error: str, messages: list[Message]) -> list[PlanStep]:
        tool_defs = self.tools.get_definitions() if len(self.tools) > 0 else []
        remaining_desc = json.dumps([s.model_dump() for s in remaining_steps], ensure_ascii=False)
        replan_prompt = (
            f"A step failed with error: {error}\n\n"
            f"Remaining steps: {remaining_desc}\n\n"
            "Adjust the plan for the remaining steps. Output as JSON: "
            '{"steps": [{"step": 1, "action": "description", "tool": "tool_name", "args": {}}]}'
        )
        replan_request = LLMRequest(
            messages=list(messages) + [Message.user(replan_prompt)],
            model=self.config.model, temperature=0.0, max_tokens=1000, tools=tool_defs,
        )
        pipeline = StructuredOutputPipeline(self._ctx.provider, max_retries=2)
        try:
            new_plan = await pipeline.generate(replan_request, PlanModel)
            if pipeline.last_usage:
                self._total_usage = self._total_usage + pipeline.last_usage
            return list(new_plan.steps[:self.config.max_iterations])
        except StructuredOutputError as e:
            _logger.warning("Failed to replan: %s, continuing with original steps", e)
            return remaining_steps