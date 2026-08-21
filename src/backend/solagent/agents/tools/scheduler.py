"""Tool scheduler — 分组并行调度，保证模型顺序。

对标 dsh executeToolCalls：
- 按 execution_mode 动态分组（parallel / sequential / exclusive）
- 并行组使用有界并发池
- 结果按模型请求顺序提交
"""

import asyncio
import logging
from typing import Any

from solagent.schema.messages import ToolCallBlock
from solagent.schema.tools import ToolExecutionMode, ToolResult

_logger = logging.getLogger(__name__)


class ToolScheduler:
    """工具调度器 — 分组执行、模型顺序保证、有界并发。

    用法：
        scheduler = ToolScheduler(executor, max_parallel=8)
        results = await scheduler.execute(tool_calls)
    """

    def __init__(self, executor: Any, max_parallel: int = 8):
        self._executor = executor
        self._max_parallel = max_parallel

    async def execute(self, calls: list[ToolCallBlock]) -> list[ToolResult]:
        if not calls:
            return []

        abort_signal = getattr(self._executor, '_abort_signal', None)

        groups = self._classify(calls)
        results: list[ToolResult | None] = [None] * len(calls)

        for group_type, indices in groups:
            if abort_signal and abort_signal.aborted:
                for i in indices:
                    results[i] = ToolResult(
                        call_id=calls[i].id, name=calls[i].name,
                        output="Execution aborted before dispatch", is_error=True,
                    )
                continue

            group_calls = [calls[i] for i in indices]
            if group_type == "parallel":
                group_results = await self._run_parallel(group_calls, abort_signal)
            elif group_type == "exclusive":
                group_results = await self._run_exclusive(group_calls, abort_signal)
            else:
                group_results = await self._run_sequential(group_calls, abort_signal)

            for i, r in zip(indices, group_results):
                results[i] = r

        return [r for r in results if r is not None]

    def _classify(self, calls: list[ToolCallBlock]) -> list[tuple[str, list[int]]]:
        groups: list[tuple[str, list[int]]] = []
        current_type: str | None = None
        current_indices: list[int] = []

        for i, call in enumerate(calls):
            try:
                tool = self._executor._registry.get(call.name)
                mode = tool.execution_mode
            except Exception:
                mode = ToolExecutionMode.SEQUENTIAL

            group_type = _mode_to_group(mode)

            if group_type == current_type:
                current_indices.append(i)
            else:
                if current_indices:
                    groups.append((current_type, current_indices))
                current_type = group_type
                current_indices = [i]

        if current_indices:
            groups.append((current_type, current_indices))

        return groups

    async def _run_parallel(self, calls: list[ToolCallBlock], abort_signal=None) -> list[ToolResult]:
        sem = asyncio.Semaphore(self._max_parallel)

        async def _bounded(call: ToolCallBlock, idx: int) -> tuple[int, ToolResult]:
            if abort_signal and abort_signal.aborted:
                return idx, ToolResult(call_id=call.id, name=call.name, output="Aborted", is_error=True)
            async with sem:
                return idx, await self._executor._execute_one(call)

        tasks = [_bounded(c, i) for i, c in enumerate(calls)]
        gathered = await asyncio.gather(*tasks, return_exceptions=True)

        ordered: list[ToolResult | None] = [None] * len(calls)
        for item in gathered:
            if isinstance(item, Exception):
                _logger.warning("Parallel tool execution failed: %s", item)
                continue
            idx, result = item
            ordered[idx] = result

        for i in range(len(calls)):
            if ordered[i] is None:
                ordered[i] = ToolResult(
                    call_id=calls[i].id, name=calls[i].name,
                    output="Tool execution failed in parallel group", is_error=True,
                )

        return [r for r in ordered if r is not None]

    async def _run_sequential(self, calls: list[ToolCallBlock], abort_signal=None) -> list[ToolResult]:
        results = []
        for call in calls:
            if abort_signal and abort_signal.aborted:
                results.append(ToolResult(call_id=call.id, name=call.name, output="Aborted", is_error=True))
                continue
            results.append(await self._executor._execute_one(call))
        return results

    async def _run_exclusive(self, calls: list[ToolCallBlock], abort_signal=None) -> list[ToolResult]:
        return await self._run_sequential(calls, abort_signal)


def _mode_to_group(mode: ToolExecutionMode) -> str:
    if mode == ToolExecutionMode.PARALLEL:
        return "parallel"
    return "sequential"