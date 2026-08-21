"""Tool executor with hooks, cache, sandbox, and validation."""
import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass

from pydantic import ValidationError as PydanticValidationError

from solagent.agents.guard.base import CompositeGuard, GuardContext, ToolHistoryEntry
from solagent.agents.guard.loop_detector import IDEMPOTENT_TOOLS
from solagent.agents.tools.cache import ToolResultCache
from solagent.agents.tools.checkpoint_mgr import CheckpointManager
from solagent.agents.tools.hooks import ToolHooks
from solagent.agents.tools.pipeline import ToolPipeline
from solagent.agents.tools.registry import ToolRegistry
from solagent.agents.tools.result_storage import ToolResultStorage
from solagent.agents.tools.validator import (
    ToolArgumentError,
    parse_and_repair_arguments,
)
from solagent.schema.messages import ToolCallBlock, ToolCallState
from solagent.schema.tools import ToolCallContext, ToolExecutionMode, ToolResult

_logger = logging.getLogger(__name__)


@dataclass
class PreResult:
    blocked: bool = False
    error: str = ""
    modified_params: object = None


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, max_parallel: int = 8, timeout_seconds: float = 420.0,
                 hooks: ToolHooks | None = None,
                 cache: ToolResultCache | None = None,
                 sandbox=None,
                 checkpoint: CheckpointManager | None = None,
                 result_storage: ToolResultStorage | None = None,
                 guard: CompositeGuard | None = None,
                 tool_pipeline=None,
                 pipeline: ToolPipeline | None = None):
        self._registry = registry
        self.max_parallel = max_parallel
        self.timeout_seconds = timeout_seconds
        self._hooks = hooks or ToolHooks()
        self._cache = cache
        self._sandbox = sandbox
        self._checkpoint = checkpoint
        self._result_storage = result_storage
        self._guard = guard
        self._guard_context = GuardContext()
        self._tool_pipeline = tool_pipeline
        self._pipeline = pipeline or ToolPipeline()
        from solagent.agents.tools.scheduler import ToolScheduler
        self._scheduler = ToolScheduler(self, max_parallel=max_parallel)

    async def execute_sequential(self, calls: list[ToolCallBlock]) -> list[ToolResult]:
        results = []
        for call in calls:
            result = await self._execute_one(call)
            if self._result_storage:
                result = self._result_storage.persist_if_large(result)
            results.append(result)
        if self._result_storage:
            results = self._result_storage.enforce_turn_budget(results)
        return results

    async def execute_parallel(self, calls: list[ToolCallBlock]) -> list[ToolResult]:
        semaphore = asyncio.Semaphore(self.max_parallel)
        async def bounded(call, idx):
            async with semaphore:
                return idx, await self._execute_one(call)
        tasks = [bounded(c, i) for i, c in enumerate(calls)]
        gathered = await asyncio.gather(*tasks, return_exceptions=True)
        ordered = [None] * len(calls)
        for item in gathered:
            if isinstance(item, Exception):
                _logger.warning("Parallel execution failed: %s", item)
                continue
            idx, result = item
            ordered[idx] = result
        for i in range(len(calls)):
            if ordered[i] is None:
                ordered[i] = ToolResult(call_id=calls[i].id, name=calls[i].name,
                                        output="Tool execution failed", is_error=True)
        return [r for r in ordered if r is not None]

    async def execute_smart(self, calls: list[ToolCallBlock]) -> list[ToolResult]:
        return await self._scheduler.execute(calls)

    async def execute_stream_one(self, call: ToolCallBlock):
        from solagent.schema.tools import ToolStreamItem
        tool = self._registry.get(call.name)
        try:
            repaired_args = parse_and_repair_arguments(call.arguments)
            params = tool.params_model.model_validate(repaired_args)
        except Exception as e:
            yield ToolStreamItem(type="terminal", result=ToolResult(
                call_id=call.id, name=call.name, output=str(e), is_error=True,
            ))
            return
        ctx = ToolCallContext(tool_call_id=call.id)
        async for item in tool.execute_stream(params, ctx):
            yield item
            if item.type == "terminal":
                break

    async def _execute_one(self, call: ToolCallBlock) -> ToolResult:
        if self._tool_pipeline:
            from solagent.plugins.pipeline import PipelineContext
            pctx = PipelineContext(
                tool_call_name=call.name,
                arguments=call.arguments,
                call=call,
                timeout=self.timeout_seconds,
            )
            return await self._tool_pipeline.run(pctx)

        call.state = ToolCallState.PENDING
        tool = None
        try:
            tool = self._registry.get(call.name)
        except Exception:
            _logger.warning("Tool registry lookup failed for call %s", call.name, exc_info=True)
            call.state = ToolCallState.FINISHED
            return ToolResult(call_id=call.id, name=call.name, output=f"Tool '{call.name}' not found", is_error=True)

        call.state = ToolCallState.VALIDATING
        try:
            repaired_args = parse_and_repair_arguments(call.arguments)
        except ToolArgumentError as e:
            call.state = ToolCallState.FINISHED
            return ToolResult(call_id=call.id, name=call.name, output=f"Invalid arguments: {e}", is_error=True)

        try:
            params = tool.params_model.model_validate(repaired_args)
        except PydanticValidationError as e:
            call.state = ToolCallState.FINISHED
            return ToolResult(
                call_id=call.id, name=call.name,
                output=f"Argument validation failed: {e}",
                is_error=True,
            )

        if self._checkpoint and tool.id in ("write", "edit", "shell", "apply_patch"):
            await self._checkpoint.ensure_checkpoint(0, f"before_{tool.id}", "")

        state: dict = {"params": params, "duration": 0.0}

        async def _default_pre():
            if self._guard:
                guard_result = await self._guard.check(call.name, call.arguments, self._guard_context)
                if guard_result.blocked:
                    return PreResult(blocked=True, error=f"Blocked by guard [{guard_result.code}]: {guard_result.reason}")
            for hook in self._hooks.before:
                before_result = await hook(tool.id, state["params"], call)
                if not before_result.allowed:
                    return PreResult(blocked=True, error=f"Blocked: {before_result.reason}")
                if before_result.modified_params is not None:
                    state["params"] = before_result.modified_params
            return PreResult(blocked=False)

        pre = await self._pipeline.run_pre(call, tool, state["params"], default_fn=_default_pre)
        if pre.blocked:
            call.state = ToolCallState.DENIED
            return ToolResult(call_id=call.id, name=call.name, output=pre.error, is_error=True)

        call.state = ToolCallState.ALLOWED

        async def _default_execute():
            if self._cache:
                ttl = getattr(tool, "cache_ttl", 0)
                if ttl != 0:
                    cached = self._cache.get(tool.id, call.arguments)
                    if cached is not None:
                        call.state = ToolCallState.FINISHED
                        return cached

            call.state = ToolCallState.EXECUTING
            if self._sandbox and getattr(tool, "sandboxed", False):
                try:
                    exec_result = await self._sandbox.execute(
                        "local", state["params"].command, language="shell", timeout=self.timeout_seconds
                    )
                    stderr_block = f"\n[stderr]\n{exec_result.stderr}" if exec_result.stderr else ""
                    result = ToolResult(
                        call_id=call.id, name=call.name,
                        output=exec_result.stdout + stderr_block,
                        is_error=exec_result.exit_code != 0,
                    )
                except Exception as e:
                    result = ToolResult(call_id=call.id, name=call.name, output=str(e), is_error=True)
            else:
                ctx = ToolCallContext(tool_call_id=call.id)
                start = time.monotonic()
                try:
                    result = await asyncio.wait_for(tool.execute(state["params"], ctx), timeout=self.timeout_seconds)
                except TimeoutError:
                    for hook in self._hooks.on_error:
                        handled = await hook(tool.id, state["params"], TimeoutError(f"timed out after {self.timeout_seconds}s"), call)
                        if handled is not None:
                            call.state = ToolCallState.FINISHED
                            return handled
                    call.state = ToolCallState.FINISHED
                    return ToolResult(call_id=call.id, name=call.name,
                                      output=f"Tool timed out after {self.timeout_seconds}s", is_error=True)
                except Exception as e:
                    for hook in self._hooks.on_error:
                        handled = await hook(tool.id, state["params"], e, call)
                        if handled is not None:
                            call.state = ToolCallState.FINISHED
                            return handled
                    _logger.warning("Tool execution failed for %s", call.name, exc_info=True)
                    call.state = ToolCallState.FINISHED
                    return ToolResult(call_id=call.id, name=call.name, output=str(e), is_error=True)
                state["duration"] = time.monotonic() - start
            return result

        result = await self._pipeline.run_around(call, tool, state["params"], default_fn=_default_execute)

        async def _default_post():
            r = result
            for hook in self._hooks.after:
                r = await hook(tool.id, state["params"], r, state["duration"], call)
            if self._cache and not r.is_error:
                ttl = getattr(tool, "cache_ttl", 0)
                if ttl != 0:
                    self._cache.set(tool.id, call.arguments, r, ttl=ttl)
            if self._guard:
                entry = ToolHistoryEntry(
                    tool_name=call.name,
                    tool_args_hash=hashlib.sha256(json.dumps(call.arguments, sort_keys=True, default=str).encode()).hexdigest(),
                    success=not r.is_error,
                    result_hash=hashlib.sha256(r.output.encode()).hexdigest() if call.name in IDEMPOTENT_TOOLS else "",
                )
                self._guard_context.tool_history.append(entry)
            return r

        result = await self._pipeline.run_post(call, tool, state["params"], result, default_fn=_default_post)

        call.state = ToolCallState.FINISHED
        return result