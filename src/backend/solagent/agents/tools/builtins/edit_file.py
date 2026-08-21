"""Edit file tool."""
from pathlib import Path
from pydantic import BaseModel, Field
from solagent.agents.tools.defs import ToolDef
from solagent.agents.tools.decorators import register_tool
from solagent.schema.tools import ToolCallContext, ToolExecutionMode, ToolResult


class EditFileParams(BaseModel):
    path: str = Field(..., description="File path to edit")
    old_string: str = Field(..., description="Text to replace")
    new_string: str = Field(..., description="Replacement text")


@register_tool(toolset="core")
class EditFileTool(ToolDef[EditFileParams]):
    id = "edit"
    description = "Replace text in a file using exact string matching"
    params_model = EditFileParams
    execution_mode = ToolExecutionMode.SEQUENTIAL

    async def execute(self, params: EditFileParams, ctx: ToolCallContext) -> ToolResult:
        try:
            p = Path(params.path)
            if not p.exists():
                return ToolResult(call_id=ctx.tool_call_id, name=self.id, output=f"File not found: {params.path}", is_error=True)
            content = p.read_text(encoding="utf-8")
            if params.old_string not in content:
                return ToolResult(call_id=ctx.tool_call_id, name=self.id, output="old_string not found in file", is_error=True)
            new_content = content.replace(params.old_string, params.new_string, 1)
            p.write_text(new_content, encoding="utf-8")
            return ToolResult(call_id=ctx.tool_call_id, name=self.id, output=f"Edited {params.path}")
        except Exception as e:
            return ToolResult(call_id=ctx.tool_call_id, name=self.id, output=str(e), is_error=True)