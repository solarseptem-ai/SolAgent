"""Utility tools."""
from datetime import UTC, datetime
from pydantic import BaseModel
from solagent.agents.tools.defs import ToolDef
from solagent.agents.tools.decorators import register_tool
from solagent.schema.tools import ToolCallContext, ToolExecutionMode, ToolResult


class EmptyParams(BaseModel):
    pass


class GetCurrentTimeTool(ToolDef[EmptyParams]):
    id = "get_current_time"
    description = "Get the current date and time"
    params_model = EmptyParams
    execution_mode = ToolExecutionMode.SEQUENTIAL

    async def execute(self, params: EmptyParams, ctx: ToolCallContext) -> ToolResult:
        now = datetime.now(UTC)
        return ToolResult(call_id=ctx.tool_call_id, name=self.id, output=now.isoformat())


class GetTokenUsageTool(ToolDef[EmptyParams]):
    id = "get_token_usage"
    description = "Get current token usage statistics"
    params_model = EmptyParams
    execution_mode = ToolExecutionMode.SEQUENTIAL

    async def execute(self, params: EmptyParams, ctx: ToolCallContext) -> ToolResult:
        return ToolResult(call_id=ctx.tool_call_id, name=self.id, output="Token usage tracking is active")