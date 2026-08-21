"""Tool error handling middleware."""
from solagent.agents.middleware.base import NextFn


class ToolErrorHandlingMiddleware:
    async def __call__(self, context: dict, next_fn: NextFn) -> dict:
        result = await next_fn(context)
        tool_results = context.get("tool_results", [])
        errors = [r for r in tool_results if getattr(r, "is_error", False)]
        if errors:
            result["tool_errors"] = [{"name": e.name, "output": e.output} for e in errors]
        return result