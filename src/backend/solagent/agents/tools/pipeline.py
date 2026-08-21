"""Waterfall-based tool execution pipeline.

对标 dsh tools/pre-execute + tools/execute + tools/post-execute waterfall。
三段式：pre_execute（可拦截）→ execute（around-dispatch）→ post_execute（可修改结果）。

每个 handler 接收 (args..., next_fn) 签名：
- 调用 next_fn() 委托给下一个 handler（waterfall 链继续）
- 不调用 next_fn() 则短路返回（拦截/替换）
"""

from collections.abc import Callable


class ToolPipeline:
    """Waterfall 工具执行管道。

    用法：
        pipeline = ToolPipeline()
        pipeline.add_pre(my_guard_handler)
        pipeline.add_around(my_timeout_handler)
        pipeline.add_post(my_compression_handler)

        # 在 ToolExecutor 中：
        pre_result = await pipeline.run_pre(call, tool, params, default_fn=_default_pre)
        result = await pipeline.run_around(call, tool, params, default_fn=_default_execute)
        result = await pipeline.run_post(call, tool, params, result, default_fn=_default_post)
    """

    def __init__(self):
        self._pre_handlers: list[Callable] = []
        self._around_handlers: list[Callable] = []
        self._post_handlers: list[Callable] = []

    def add_pre(self, handler: Callable) -> None:
        self._pre_handlers.append(handler)

    def add_around(self, handler: Callable) -> None:
        self._around_handlers.append(handler)

    def add_post(self, handler: Callable) -> None:
        self._post_handlers.append(handler)

    async def run_pre(self, *args, default_fn: Callable | None = None):
        return await _waterfall(self._pre_handlers, 0, *args, default_fn=default_fn)

    async def run_around(self, *args, default_fn: Callable | None = None):
        return await _waterfall(self._around_handlers, 0, *args, default_fn=default_fn)

    async def run_post(self, *args, default_fn: Callable | None = None):
        return await _waterfall(self._post_handlers, 0, *args, default_fn=default_fn)


async def _waterfall(handlers: list[Callable], idx: int, *args, default_fn: Callable | None = None):
    if idx >= len(handlers):
        if default_fn is not None:
            return await default_fn()
        return None
    handler = handlers[idx]

    async def _next():
        return await _waterfall(handlers, idx + 1, *args, default_fn=default_fn)

    return await handler(*args, _next)