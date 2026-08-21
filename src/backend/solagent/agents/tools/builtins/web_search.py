"""Web search tool."""
from pydantic import BaseModel, Field
from solagent.agents.tools.defs import ToolDef
from solagent.agents.tools.decorators import register_tool
from solagent.schema.tools import ToolCallContext, ToolExecutionMode, ToolResult


class WebSearchParams(BaseModel):
    query: str = Field(..., description="Search query")
    num_results: int = Field(default=5, description="Number of results")


@register_tool(toolset="search")
class WebSearchTool(ToolDef[WebSearchParams]):
    id = "web_search"
    description = "Search the web for information"
    params_model = WebSearchParams
    execution_mode = ToolExecutionMode.SEQUENTIAL

    async def execute(self, params: WebSearchParams, ctx: ToolCallContext) -> ToolResult:
        return ToolResult(call_id=ctx.tool_call_id, name=self.id,
                          output=f"Web search for: {params.query}\n(Configure a search API key to enable live results)")