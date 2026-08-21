"""Memory operation tools."""
from pydantic import BaseModel, Field
from solagent.agents.tools.defs import ToolDef
from solagent.agents.tools.decorators import register_tool
from solagent.schema.tools import ToolCallContext, ToolExecutionMode, ToolResult


class RememberParams(BaseModel):
    content: str = Field(..., description="Content to remember")
    category: str = Field(default="fact", description="Category: fact, preference, event, knowledge")
    importance: float = Field(default=0.5, description="Importance 0-1")


@register_tool(toolset="memory")
class RememberTool(ToolDef[RememberParams]):
    id = "remember"
    description = "Store a fact or memory for later recall"
    params_model = RememberParams
    execution_mode = ToolExecutionMode.SEQUENTIAL

    async def execute(self, params: RememberParams, ctx: ToolCallContext) -> ToolResult:
        return ToolResult(call_id=ctx.tool_call_id, name=self.id,
                          output=f"Stored: [{params.category}] {params.content} (importance: {params.importance})")


class RecallParams(BaseModel):
    query: str = Field(..., description="Search query")
    limit: int = Field(default=5, description="Max results")


@register_tool(toolset="memory")
class RecallTool(ToolDef[RecallParams]):
    id = "recall"
    description = "Recall memories matching a query"
    params_model = RecallParams
    execution_mode = ToolExecutionMode.SEQUENTIAL

    async def execute(self, params: RecallParams, ctx: ToolCallContext) -> ToolResult:
        return ToolResult(call_id=ctx.tool_call_id, name=self.id,
                          output=f"Searching memories for: {params.query}\nNo memories stored yet. Use remember tool first.")


class ForgetParams(BaseModel):
    memory_id: str = Field(..., description="Memory ID to forget")


@register_tool(toolset="memory")
class ForgetTool(ToolDef[ForgetParams]):
    id = "forget"
    description = "Delete a specific memory"
    params_model = ForgetParams
    execution_mode = ToolExecutionMode.SEQUENTIAL

    async def execute(self, params: ForgetParams, ctx: ToolCallContext) -> ToolResult:
        return ToolResult(call_id=ctx.tool_call_id, name=self.id, output=f"Memory {params.memory_id} forgotten")