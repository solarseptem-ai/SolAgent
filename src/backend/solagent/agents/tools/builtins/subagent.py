"""Subagent delegation tool. 真实委派任务给子 AgentBuilder。"""
import asyncio
import logging
from typing import Callable

from pydantic import BaseModel, Field

from solagent.agents.tools.defs import ToolDef
from solagent.agents.tools.decorators import register_tool
from solagent.schema.tools import ToolCallContext, ToolExecutionMode, ToolResult

_logger = logging.getLogger(__name__)


class SubagentParams(BaseModel):
    task: str = Field(..., description="Task description for the subagent")
    agent_name: str = Field(default="", description="Optional agent name（指定已注册的 subagent provider）")
    tools: str = Field(default="", description="Comma-separated tool names to grant")
    max_depth: int = Field(default=3, ge=1, le=10, description="Maximum subagent nesting depth")


@register_tool(toolset="meta")
class SubagentTool(ToolDef[SubagentParams]):
    id = "subagent"
    description = "Delegate a task to a subagent for isolated execution"
    params_model = SubagentParams
    execution_mode = ToolExecutionMode.SEQUENTIAL

    def __init__(self):
        super().__init__()
        self._parent_ctx = None

    def bind_parent_ctx(self, ctx_fn: Callable) -> None:
        self._parent_ctx = ctx_fn

    async def execute(self, params: SubagentParams, ctx: ToolCallContext) -> ToolResult:
        if self._parent_ctx is None:
            return ToolResult(call_id=ctx.tool_call_id, name=self.id,
                              output="SubagentTool not bound to parent context", is_error=True)

        parent_ctx = self._parent_ctx()

        current_depth = parent_ctx.metadata.get("subagent_depth", 0)
        if current_depth >= params.max_depth:
            return ToolResult(call_id=ctx.tool_call_id, name=self.id,
                              output=f"Subagent depth {current_depth} exceeds max {params.max_depth}", is_error=True)

        if params.agent_name:
            return await self._execute_named(params, ctx, parent_ctx)

        tool_names = [t.strip() for t in params.tools.split(",") if t.strip()] or None

        try:
            from solagent.agents.subagent_factory import create as _create_subagent
            from solagent.schema.messages import Message

            builder = await _create_subagent(
                parent_ctx=parent_ctx,
                task=params.task,
                tool_names=tool_names,
            )
            result = await builder.run([Message.user(params.task)])
            return ToolResult(call_id=ctx.tool_call_id, name=self.id,
                              output=result.content, is_error=result.finish_reason == "error")
        except asyncio.CancelledError:
            return ToolResult(call_id=ctx.tool_call_id, name=self.id,
                              output="Subagent cancelled", is_error=True)
        except Exception as e:
            _logger.warning("Subagent execution failed", exc_info=True)
            return ToolResult(call_id=ctx.tool_call_id, name=self.id,
                              output=f"Subagent failed: {e}", is_error=True)

    async def _execute_named(self, params, ctx, parent_ctx):
        try:
            from solagent.subagent.runtime import SubagentRuntime
            from solagent.subagent.types import SubagentStartRequest
        except ImportError:
            return ToolResult(call_id=ctx.tool_call_id, name=self.id,
                              output=f"Named subagent '{params.agent_name}' not available: SubagentRuntime not loaded", is_error=True)

        try:
            runtime = parent_ctx.plugin_ctx.root._services.get("subagent_runtime")
        except Exception:
            runtime = None

        if runtime is None:
            return ToolResult(call_id=ctx.tool_call_id, name=self.id,
                              output=f"SubagentRuntime not initialized. Use unnamed subagent or configure subagent_runtime.", is_error=True)

        tool_names = [t.strip() for t in params.tools.split(",") if t.strip()] if params.tools else None
        request = SubagentStartRequest(
            task=params.task,
            tools=tool_names or [],
            max_iterations=5,
        )
        try:
            run = await runtime.start(params.agent_name, request)
            result = await run.result()
            if result.error:
                return ToolResult(call_id=ctx.tool_call_id, name=self.id, output=result.error, is_error=True)
            return ToolResult(call_id=ctx.tool_call_id, name=self.id,
                              output=str(result.value) if result.value else result.error or "", is_error=False)
        except ValueError as e:
            return ToolResult(call_id=ctx.tool_call_id, name=self.id, output=str(e), is_error=True)
        except Exception as e:
            return ToolResult(call_id=ctx.tool_call_id, name=self.id, output=f"Named subagent failed: {e}", is_error=True)