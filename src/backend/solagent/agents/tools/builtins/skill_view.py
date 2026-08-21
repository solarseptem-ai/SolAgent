"""Skill view tool — Agent can load skill content on demand."""
from pydantic import BaseModel, Field
from solagent.agents.tools.defs import ToolDef
from solagent.agents.tools.decorators import register_tool
from solagent.schema.tools import ToolCallContext, ToolExecutionMode, ToolResult


class SkillViewParams(BaseModel):
    skill_name: str = Field(..., description="Name of the skill to load")


@register_tool(toolset="interact")
class SkillViewTool(ToolDef[SkillViewParams]):
    id = "skill_view"
    description = "Load the full instructions for a skill by name. Call this BEFORE using any skill's workflow."
    params_model = SkillViewParams
    execution_mode = ToolExecutionMode.SEQUENTIAL

    def __init__(self):
        super().__init__()
        self._skill_manager = None

    def bind_skill_manager(self, skill_manager) -> None:
        self._skill_manager = skill_manager

    async def execute(self, params: SkillViewParams, ctx: ToolCallContext) -> ToolResult:
        if self._skill_manager is None:
            return ToolResult(call_id=ctx.tool_call_id, name=self.id,
                              output="SkillViewTool not bound to SkillManager", is_error=True)
        skill = self._skill_manager.registry.get(params.skill_name)
        if skill is None:
            available = [s.name for s in self._skill_manager.registry.list_all()]
            return ToolResult(call_id=ctx.tool_call_id, name=self.id,
                              output=f"Skill '{params.skill_name}' not found. Available: {', '.join(available)}",
                              is_error=True)
        return ToolResult(call_id=ctx.tool_call_id, name=self.id,
                          output=f"# Skill: {skill.name}\n\n{skill.content}\n\n"
                                 f"Allowed tools: {', '.join(skill.allowed_tools) if skill.allowed_tools else 'all'}",
                          is_error=False)