"""Search tools."""
from pathlib import Path

from pydantic import BaseModel, Field

from solagent.agents.tools.defs import ToolDef
from solagent.agents.tools.decorators import register_tool
from solagent.schema.tools import ToolCallContext, ToolExecutionMode, ToolResult


class GlobParams(BaseModel):
    pattern: str = Field(..., description="Glob pattern (e.g. '**/*.py')")
    path: str = Field(default=".", description="Base directory")


@register_tool(toolset="core")
class GlobTool(ToolDef[GlobParams]):
    id = "glob"
    description = "Find files matching a glob pattern"
    params_model = GlobParams
    execution_mode = ToolExecutionMode.SEQUENTIAL
    cache_ttl = -1

    async def execute(self, params: GlobParams, ctx: ToolCallContext) -> ToolResult:
        try:
            base = Path(params.path)
            matches = sorted(base.glob(params.pattern))
            lines = [str(m) for m in matches[:200]]
            return ToolResult(call_id=ctx.tool_call_id, name=self.id, output="\n".join(lines) or "(no matches)")
        except Exception as e:
            return ToolResult(call_id=ctx.tool_call_id, name=self.id, output=str(e), is_error=True)


class GrepParams(BaseModel):
    pattern: str = Field(..., description="Regex pattern to search for")
    path: str = Field(default=".", description="Directory or file to search")
    include: str = Field(default="", description="File pattern filter (e.g. '*.py')")


@register_tool(toolset="core")
class GrepTool(ToolDef[GrepParams]):
    id = "grep"
    description = "Search file contents using regex"
    params_model = GrepParams
    execution_mode = ToolExecutionMode.SEQUENTIAL
    cache_ttl = -1

    async def execute(self, params: GrepParams, ctx: ToolCallContext) -> ToolResult:
        import re
        try:
            base = Path(params.path)
            pattern = re.compile(params.pattern)
            results = []
            files = [base] if base.is_file() else base.rglob("*")
            for f in files:
                if not f.is_file():
                    continue
                if params.include and not f.match(params.include):
                    continue
                try:
                    for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                        if pattern.search(line):
                            results.append(f"{f}:{i}: {line.strip()}")
                except Exception:
                    pass
                if len(results) >= 200:
                    break
            return ToolResult(call_id=ctx.tool_call_id, name=self.id, output="\n".join(results) or "(no matches)")
        except Exception as e:
            return ToolResult(call_id=ctx.tool_call_id, name=self.id, output=str(e), is_error=True)
