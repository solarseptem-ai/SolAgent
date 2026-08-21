"""Interaction tools."""
from pydantic import BaseModel, Field
from solagent.agents.tools.defs import ToolDef
from solagent.agents.tools.decorators import register_tool
from solagent.schema.tools import ToolCallContext, ToolExecutionMode, ToolResult


class PresentFileParams(BaseModel):
    path: str = Field(..., description="File path to present")


@register_tool(toolset="interact")
class PresentFileTool(ToolDef[PresentFileParams]):
    id = "present_file"
    description = "Present a file to the user for review"
    params_model = PresentFileParams
    execution_mode = ToolExecutionMode.SEQUENTIAL

    async def execute(self, params: PresentFileParams, ctx: ToolCallContext) -> ToolResult:
        return ToolResult(call_id=ctx.tool_call_id, name=self.id, output=f"Presenting file: {params.path}")


class ClarificationParams(BaseModel):
    question: str = Field(..., description="Question to ask the user")


@register_tool(toolset="interact")
class ClarificationTool(ToolDef[ClarificationParams]):
    id = "clarify"
    description = "Ask the user a clarifying question"
    params_model = ClarificationParams
    execution_mode = ToolExecutionMode.SEQUENTIAL

    async def execute(self, params: ClarificationParams, ctx: ToolCallContext) -> ToolResult:
        return ToolResult(call_id=ctx.tool_call_id, name=self.id, output=f"Clarification requested: {params.question}")