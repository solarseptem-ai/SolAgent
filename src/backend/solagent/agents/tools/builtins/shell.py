"""Shell execution tool."""
import subprocess
from pydantic import BaseModel, Field
from solagent.agents.tools.defs import ToolDef
from solagent.agents.tools.decorators import register_tool
from solagent.schema.tools import ToolCallContext, ToolExecutionMode, ToolResult


class ShellParams(BaseModel):
    command: str = Field(..., description="Shell command to execute")
    cwd: str = Field(default="", description="Working directory")


@register_tool(toolset="core")
class ShellTool(ToolDef[ShellParams]):
    id = "shell"
    description = "Execute a shell command"
    params_model = ShellParams
    execution_mode = ToolExecutionMode.SEQUENTIAL
    sandboxed = True
    streamable = True
    cache_ttl = 0
    concurrency_safe = False  # 文件系统操作不可并行

    async def execute(self, params: ShellParams, ctx: ToolCallContext) -> ToolResult:
        try:
            result = subprocess.run(
                params.command, shell=True, capture_output=True, text=True,
                timeout=120, cwd=params.cwd or ctx.cwd or None,
            )
            output = result.stdout
            if result.stderr:
                output += f"\n[stderr]\n{result.stderr}"
            if result.returncode != 0:
                output += f"\n[exit code: {result.returncode}]"
            return ToolResult(call_id=ctx.tool_call_id, name=self.id, output=output,
                              is_error=result.returncode != 0)
        except Exception as e:
            return ToolResult(call_id=ctx.tool_call_id, name=self.id, output=str(e), is_error=True)