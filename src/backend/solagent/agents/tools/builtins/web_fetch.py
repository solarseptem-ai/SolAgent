"""Web fetch tool."""
from pydantic import BaseModel, Field
from solagent.agents.tools.defs import ToolDef
from solagent.agents.tools.decorators import register_tool
from solagent.schema.tools import ToolCallContext, ToolExecutionMode, ToolResult


class WebFetchParams(BaseModel):
    url: str = Field(..., description="URL to fetch")
    max_length: int = Field(default=5000, description="Max content length")


@register_tool(toolset="search")
class WebFetchTool(ToolDef[WebFetchParams]):
    id = "web_fetch"
    description = "Fetch content from a URL"
    params_model = WebFetchParams
    execution_mode = ToolExecutionMode.SEQUENTIAL
    cache_ttl = 60
    streamable = True

    async def execute(self, params: WebFetchParams, ctx: ToolCallContext) -> ToolResult:
        try:
            import urllib.request
            req = urllib.request.Request(params.url, headers={"User-Agent": "solagent/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                content = resp.read().decode("utf-8", errors="replace")[:params.max_length]
            return ToolResult(call_id=ctx.tool_call_id, name=self.id, output=content)
        except Exception as e:
            return ToolResult(call_id=ctx.tool_call_id, name=self.id, output=str(e), is_error=True)