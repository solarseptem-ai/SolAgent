"""File I/O tools."""
from pathlib import Path

from pydantic import BaseModel, Field

from solagent.agents.tools.defs import ToolDef
from solagent.agents.tools.decorators import register_tool
from solagent.schema.tools import ToolCallContext, ToolExecutionMode, ToolResult


class ReadFileParams(BaseModel):
    path: str = Field(..., description="File path to read")
    offset: int = Field(default=0, description="Start line (1-indexed)")
    limit: int = Field(default=200, description="Max lines to read")


@register_tool(toolset="core")
class ReadFileTool(ToolDef[ReadFileParams]):
    id = "read"
    description = "Read a file from the local filesystem"
    params_model = ReadFileParams
    execution_mode = ToolExecutionMode.SEQUENTIAL
    cache_ttl = -1

    async def execute(self, params: ReadFileParams, ctx: ToolCallContext) -> ToolResult:
        try:
            p = Path(params.path)
            if not p.exists():
                return ToolResult(call_id=ctx.tool_call_id, name=self.id, output=f"File not found: {params.path}", is_error=True)
            lines = p.read_text(encoding="utf-8").splitlines()
            if params.offset > 0:
                lines = lines[params.offset - 1:]
            if params.limit > 0:
                lines = lines[:params.limit]
            content = "\n".join(lines)
            return ToolResult(call_id=ctx.tool_call_id, name=self.id, output=content)
        except Exception as e:
            return ToolResult(call_id=ctx.tool_call_id, name=self.id, output=str(e), is_error=True)


class WriteFileParams(BaseModel):
    path: str = Field(..., description="File path to write")
    content: str = Field(..., description="Content to write")


@register_tool(toolset="core")
class WriteFileTool(ToolDef[WriteFileParams]):
    id = "write"
    description = "Write content to a file"
    params_model = WriteFileParams
    execution_mode = ToolExecutionMode.SEQUENTIAL
    cache_ttl = 0

    async def execute(self, params: WriteFileParams, ctx: ToolCallContext) -> ToolResult:
        try:
            p = Path(params.path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(params.content, encoding="utf-8")
            return ToolResult(call_id=ctx.tool_call_id, name=self.id, output=f"Written {len(params.content)} bytes to {params.path}")
        except Exception as e:
            return ToolResult(call_id=ctx.tool_call_id, name=self.id, output=str(e), is_error=True)


class ListDirParams(BaseModel):
    path: str = Field(default=".", description="Directory path to list")


@register_tool(toolset="core")
class ListDirTool(ToolDef[ListDirParams]):
    id = "ls"
    description = "List files and directories"
    params_model = ListDirParams
    execution_mode = ToolExecutionMode.SEQUENTIAL
    cache_ttl = -1

    async def execute(self, params: ListDirParams, ctx: ToolCallContext) -> ToolResult:
        try:
            p = Path(params.path)
            if not p.exists():
                return ToolResult(call_id=ctx.tool_call_id, name=self.id, output=f"Directory not found: {params.path}", is_error=True)
            entries = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
            lines = []
            for entry in entries:
                suffix = "/" if entry.is_dir() else ""
                lines.append(f"{entry.name}{suffix}")
            return ToolResult(call_id=ctx.tool_call_id, name=self.id, output="\n".join(lines) or "(empty)")
        except Exception as e:
            return ToolResult(call_id=ctx.tool_call_id, name=self.id, output=str(e), is_error=True)
