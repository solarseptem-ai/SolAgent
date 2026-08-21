"""Loop detection middleware. Detects repeated tool call patterns."""
from solagent.agents.middleware.base import NextFn


class LoopDetectionMiddleware:
    def __init__(self, max_repeats: int = 5):
        self.max_repeats = max_repeats
        self._history: list[str] = []
    
    async def __call__(self, context: dict, next_fn: NextFn) -> dict:
        tool_calls = context.get("tool_calls", [])
        call_sig = ",".join(tc.get("name", "") for tc in tool_calls) if tool_calls else ""
        self._history.append(call_sig)
        if len(self._history) > self.max_repeats:
            recent = self._history[-self.max_repeats:]
            if len(set(recent)) == 1 and recent[0]:
                from solagent.errors.loop import MaxIterationError
                raise MaxIterationError(self.max_repeats)
        return await next_fn(context)
    
    def reset(self) -> None:
        self._history.clear()