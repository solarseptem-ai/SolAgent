"""Tool search bridge. 对标 hermes-agent tool_search.py：三层桥接模式。"""
from pydantic import BaseModel, Field

from solagent.agents.tools.defs import ToolDef
from solagent.agents.tools.decorators import register_tool
from solagent.agents.tools.registry import ToolEntry
from solagent.schema.tools import ToolCallContext, ToolExecutionMode, ToolResult


class ToolSearchParams(BaseModel):
    query: str = Field(..., description="Keyword to search for in tool names and descriptions")


@register_tool(toolset="meta")
class ToolSearchTool(ToolDef[ToolSearchParams]):
    id = "tool_search"
    description = "Search for available tools by keyword. Use this to discover tools not listed above."
    params_model = ToolSearchParams
    execution_mode = ToolExecutionMode.SEQUENTIAL

    _deferred: list[ToolEntry] = []

    def bind_deferred(self, deferred: list[ToolEntry]) -> None:
        self._deferred = deferred

    async def execute(self, params: ToolSearchParams, ctx: ToolCallContext) -> ToolResult:
        query = params.query.lower()
        matches = [
            e for e in self._deferred
            if query in e.tool.id.lower() or query in e.tool.description.lower()
        ]
        if not matches:
            ids = [e.tool.id for e in self._deferred]
            return ToolResult(
                call_id=ctx.tool_call_id, name=self.id,
                output=f"No tools found matching '{params.query}'. Available deferred tools: {ids}",
            )
        lines = ["## Matching Tools"]
        for e in matches[:5]:
            lines.append(f"- **{e.tool.id}**: {e.tool.description}")
        lines.append(f"\nTo use a tool, call it directly by name.")
        return ToolResult(call_id=ctx.tool_call_id, name=self.id, output="\n".join(lines))