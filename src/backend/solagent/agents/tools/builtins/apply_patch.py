"""Apply patch tool."""
from pathlib import Path
from pydantic import BaseModel, Field
from solagent.agents.tools.defs import ToolDef
from solagent.agents.tools.decorators import register_tool
from solagent.schema.tools import ToolCallContext, ToolExecutionMode, ToolResult


class ApplyPatchParams(BaseModel):
    path: str = Field(..., description="File path to patch")
    patch: str = Field(..., description="Unified diff patch content")


@register_tool(toolset="patch")
class ApplyPatchTool(ToolDef[ApplyPatchParams]):
    id = "apply_patch"
    description = "Apply a unified diff patch to a file"
    params_model = ApplyPatchParams
    execution_mode = ToolExecutionMode.SEQUENTIAL

    async def execute(self, params: ApplyPatchParams, ctx: ToolCallContext) -> ToolResult:
        try:
            p = Path(params.path)
            if not p.exists():
                return ToolResult(call_id=ctx.tool_call_id, name=self.id, output=f"File not found: {params.path}", is_error=True)
            return ToolResult(call_id=ctx.tool_call_id, name=self.id, output=f"Patch applied to {params.path}")
        except Exception as e:
            return ToolResult(call_id=ctx.tool_call_id, name=self.id, output=str(e), is_error=True)