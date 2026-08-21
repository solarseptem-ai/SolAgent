"""DAG 执行引擎。

负责将编译后的 DAG 模型按拓扑层级调度执行，支持：
- 同层级步骤并行执行（asyncio.gather）
- 条件分支过滤（condition evaluation）
- Fan-out 批量展开（对一个列表逐项执行）
- 结果缓存（cache_policy）
- 重试机制（retry_policy）
- 子 DAG 嵌套执行
- 流式进度事件（execute_stream）

适用于复杂多步骤任务的自动化流水线编排。
"""

from __future__ import annotations

import asyncio
import copy
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from jinja2 import BaseLoader, Environment, UndefinedError

from solagent.agents.dag.plan import ExecutionPlan
from solagent.agents.tools.registry import ToolRegistry
from solagent.schema.messages import ToolCallBlock
from solagent.schema.structured import DAGModel, DAGStep
from solagent.schema.tools import ToolResult

_logger = logging.getLogger(__name__)

# Jinja2 环境，用于解析步骤输入模板和条件表达式
_jinja_env = Environment(loader=BaseLoader(), autoescape=False)


@dataclass
class StepResult:
    """单个 DAG 步骤的执行结果。

    属性:
        step_id: 步骤标识。
        output: 步骤输出内容。
        error: 错误信息（如有）。
        is_error: 是否执行失败。
        duration_ms: 执行耗时（毫秒）。
        retries: 实际重试次数。
        cached: 结果是否来自缓存。
        skipped: 是否因条件未满足而被跳过。
    """
    step_id: str
    output: Any = None
    error: str | None = None
    is_error: bool = False
    duration_ms: float = 0.0
    retries: int = 0
    cached: bool = False
    skipped: bool = False


@dataclass
class DAGResult:
    """整个 DAG 的执行结果聚合。

    属性:
        steps: 各步骤的 StepResult 列表。
        total_duration_ms: 总执行耗时（毫秒）。
        error: 全局错误信息（如编译失败或严重异常）。
    """
    steps: list[StepResult] = field(default_factory=list)
    total_duration_ms: float = 0.0
    error: str | None = None

    @property
    def failed(self) -> bool:
        """判断 DAG 整体是否失败（存在全局错误或有步骤报错）。"""
        return self.error is not None or any(s.is_error for s in self.steps)

    def get_output(self, step_id: str) -> Any:
        """按步骤 ID 获取对应输出，若步骤出错则返回 None。"""
        for s in self.steps:
            if s.step_id == step_id:
                return s.output if not s.is_error else None
        return None


@dataclass
class DAGEvent:
    """DAG 执行过程中的流式事件，用于进度追踪和监控。

    属性:
        type: 事件类型（dag_start、level_start、step_start、step_end、level_end、dag_end、dag_error 等）。
        step_id: 相关步骤 ID。
        level: 当前层级索引。
        progress: 进度百分比（0~1）。
        message: 可读的事件描述。
        data: 附加数据。
    """
    type: str
    step_id: str = ""
    level: int = 0
    progress: float = 0.0
    message: str = ""
    data: Any = None


class DAGExecutor:
    """DAG 执行器，按拓扑层级并行调度执行 DAG 中的各个步骤。

    属性:
        registry: 工具注册表，用于查找步骤对应的工具。
        tool_executor_factory: 可选的工具执行器工厂函数。
        max_parallel: Fan-out 场景下的最大并发数。
        cache: 步骤结果缓存字典，按 cache_key 命中可跳过实际执行。
    """

    def __init__(
        self,
        registry: ToolRegistry,
        tool_executor_factory=None,
        max_parallel: int = 8,
        cache: dict | None = None,
    ):
        self._registry = registry
        self._tool_executor_factory = tool_executor_factory
        self._max_parallel = max_parallel
        self._cache: dict[str, StepResult] = cache or {}

    def _make_executor(self):
        """创建工具执行器实例，优先使用工厂函数，否则默认创建 ToolExecutor。"""
        if self._tool_executor_factory:
            return self._tool_executor_factory()
        from solagent.agents.tools.executor import ToolExecutor
        return ToolExecutor(self._registry)

    async def execute(self, dag: DAGModel) -> DAGResult:
        """执行 DAG 并返回聚合结果（非流式）。

        参数:
            dag: 要执行的 DAG 模型。

        返回:
            包含所有步骤结果和总耗时的 DAGResult。
        """
        plan = ExecutionPlan.compile(dag)
        if not plan.is_valid:
            return DAGResult(error="; ".join(plan.errors))

        if plan.cycles:
            _logger.warning("DAG has cycles: %s", plan.cycles)

        results: dict[str, StepResult] = {}
        start_time = time.monotonic()

        for level_idx, level in enumerate(plan.levels):
            ready_steps = self._filter_conditional(level, results)

            if not ready_steps:
                continue

            executor = self._make_executor()
            batch_tasks = []
            for step in ready_steps:
                batch_tasks.append(self._execute_step(step, results, executor))

            level_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
            for step, sr in zip(ready_steps, level_results):
                if isinstance(sr, Exception):
                    results[step.id] = StepResult(
                        step_id=step.id, error=str(sr), is_error=True,
                        duration_ms=0.0,
                    )
                else:
                    results[step.id] = sr

        total_ms = (time.monotonic() - start_time) * 1000
        step_list = [results.get(s.id) for s in dag.steps if s.id in results]
        return DAGResult(steps=step_list, total_duration_ms=total_ms)

    async def execute_stream(self, dag: DAGModel) -> AsyncIterator[DAGEvent]:
        """流式执行 DAG，逐步产出进度事件（dag_start、level_start、step_start、step_end 等）。

        参数:
            dag: 要执行的 DAG 模型。

        返回:
            异步迭代器，产出 DAGEvent 事件对象。
        """
        plan = ExecutionPlan.compile(dag)
        if not plan.is_valid:
            yield DAGEvent(type="dag_error", message="; ".join(plan.errors))
            return

        if plan.cycles:
            _logger.warning("DAG has cycles: %s", plan.cycles)

        yield DAGEvent(type="dag_start", message=f"Starting DAG: {plan.total_steps} steps, {plan.level_count} levels")

        results: dict[str, StepResult] = {}
        for level_idx, level in enumerate(plan.levels):
            yield DAGEvent(type="level_start", level=level_idx,
                               message=f"Level {level_idx + 1}/{plan.level_count}: {len(level)} steps")

            ready_steps = self._filter_conditional(level, results)
            if not ready_steps:
                yield DAGEvent(type="level_end", level=level_idx, message=f"Level {level_idx + 1}: all steps skipped")
                continue

            executor = self._make_executor()
            for step in ready_steps:
                yield DAGEvent(type="step_start", step_id=step.id, level=level_idx,
                               message=f"Step {step.id}: {step.description or step.tool}")

            batch_tasks = [self._execute_step(step, results, executor) for step in ready_steps]
            level_results = await asyncio.gather(*batch_tasks, return_exceptions=True)

            for step, sr in zip(ready_steps, level_results):
                if isinstance(sr, Exception):
                    results[step.id] = StepResult(step_id=step.id, error=str(sr), is_error=True, duration_ms=0.0)
                    yield DAGEvent(type="step_end", step_id=step.id, level=level_idx,
                                   message=f"Step {step.id}: FAILED — {sr}")
                else:
                    results[step.id] = sr
                    status = "CACHED" if sr.cached else ("SKIPPED" if sr.skipped else "OK")
                    yield DAGEvent(type="step_end", step_id=step.id, level=level_idx,
                                   message=f"Step {step.id}: {status} ({sr.duration_ms:.0f}ms, {sr.retries} retries)")

            yield DAGEvent(type="level_end", level=level_idx, message=f"Level {level_idx + 1}: complete")

        yield DAGEvent(type="dag_end", message="DAG execution complete")

    def _filter_conditional(self, level: list[DAGStep], results: dict[str, StepResult]) -> list[DAGStep]:
        """过滤当前层级中不满足条件表达式的步骤，将跳过的步骤标记为 skipped。

        参数:
            level: 当前层级的步骤列表。
            results: 已执行步骤的结果字典，用于条件求值。

        返回:
            满足条件、需要实际执行的步骤列表。
        """
        ready = []
        for step in level:
            if step.condition and not self._eval_condition(step.condition, results):
                results[step.id] = StepResult(step_id=step.id, skipped=True, duration_ms=0.0)
                _logger.info("Step '%s' skipped: condition '%s' not met", step.id, step.condition)
                continue
            ready.append(step)
        return ready

    def _eval_condition(self, condition: str, results: dict[str, StepResult]) -> bool:
        """使用已完成的步骤输出作为命名空间，对条件表达式求值。

        参数:
            condition: Jinja2 或 Python 表达式字符串。
            results: 已完成步骤的结果字典。

        返回:
            求值结果布尔值；若求值失败则默认返回 True（保守策略，避免误跳过）。
        """
        try:
            namespace: dict[str, Any] = {}
            for sid, sr in results.items():
                if not sr.is_error and not sr.skipped:
                    namespace[f"step_{sid}"] = SimpleNamespace(output=sr.output)
            return bool(eval(condition, {"__builtins__": {}}, namespace))
        except Exception:
            _logger.warning("Failed to evaluate condition '%s', defaulting to True", condition, exc_info=True)
            return True

    async def _execute_step(
        self, step: DAGStep, results: dict[str, StepResult], executor
    ) -> StepResult:
        """执行单个 DAG 步骤，处理子 DAG、Fan-out、缓存、重试和错误处理。"""
        if step.sub_dag:
            return await self._execute_sub_dag(step, results, executor)

        resolved_args = self._resolve_inputs(step, results)

        if step.fan_out:
            return await self._execute_fan_out(step, resolved_args, results, executor)

        cache_key = self._build_cache_key(step, resolved_args)
        if cache_key and step.cache_policy != "none":
            if cache_key in self._cache:
                cached = self._cache[cache_key]
                _logger.info("Step '%s': cache hit", step.id)
                return StepResult(
                    step_id=step.id, output=cached.output,
                    duration_ms=0.0, cached=True,
                )

        total_retries = step.retry_policy.max_attempts - 1 if step.retry_policy else 0
        last_error: str | None = None

        for attempt in range(total_retries + 1):
            start = time.monotonic()
            try:
                call = ToolCallBlock(
                    type="tool_call", id=step.id, name=step.tool, arguments=resolved_args,
                )
                tool_results = await executor.execute_sequential([call])
                result = tool_results[0] if tool_results else ToolResult(
                    call_id=step.id, name=step.tool, output="", is_error=True,
                )
                duration_ms = (time.monotonic() - start) * 1000

                if result.is_error and attempt < total_retries:
                    _logger.info(
                        "Step '%s': attempt %d/%d failed: %s",
                        step.id, attempt + 1, total_retries + 1, result.output[:100],
                    )
                    last_error = result.output
                    if step.retry_policy:
                        delay = min(
                            step.retry_policy.initial_interval * (step.retry_policy.backoff_factor ** attempt),
                            step.retry_policy.max_interval,
                        )
                        await asyncio.sleep(delay)
                    continue

                sr = StepResult(
                    step_id=step.id, output=result.output,
                    is_error=result.is_error, duration_ms=duration_ms,
                    retries=attempt,
                )
                if cache_key and step.cache_policy != "none" and not result.is_error:
                    self._cache[cache_key] = sr
                return sr
            except Exception as e:
                if attempt < total_retries:
                    last_error = str(e)
                    if step.retry_policy:
                        delay = min(
                            step.retry_policy.initial_interval * (step.retry_policy.backoff_factor ** attempt),
                            step.retry_policy.max_interval,
                        )
                        await asyncio.sleep(delay)
                    continue
                return StepResult(
                    step_id=step.id, error=str(e), is_error=True,
                    duration_ms=(time.monotonic() - start) * 1000,
                    retries=attempt + 1,
                )

        if step.error_handler:
            try:
                call = ToolCallBlock(
                    type="tool_call", id=f"{step.id}_handler",
                    name=step.error_handler, arguments=resolved_args,
                )
                handler_results = await executor.execute_sequential([call])
                hr = handler_results[0] if handler_results else ToolResult(
                    call_id=f"{step.id}_handler", name=step.error_handler, output="", is_error=True,
                )
                return StepResult(
                    step_id=step.id, output=hr.output,
                    is_error=hr.is_error, duration_ms=0.0,
                    retries=total_retries,
                )
            except Exception as e:
                _logger.warning("Step '%s': error handler '%s' also failed: %s", step.id, step.error_handler, e)

        return StepResult(
            step_id=step.id, error=last_error or "all retries exhausted", is_error=True,
            duration_ms=0.0, retries=total_retries,
        )

    async def _execute_sub_dag(
        self, step: DAGStep, results: dict[str, StepResult], executor
    ) -> StepResult:
        """执行嵌套子 DAG，并将子结果聚合为当前步骤的输出。"""
        if not step.sub_dag:
            return StepResult(step_id=step.id, error="empty sub_dag", is_error=True, duration_ms=0.0)
        sub_result = await self.execute(step.sub_dag)
        if sub_result.failed:
            return StepResult(
                step_id=step.id, error=sub_result.error or "sub_dag failed",
                is_error=True, duration_ms=sub_result.total_duration_ms,
            )
        outputs = {s.step_id: s.output for s in sub_result.steps}
        return StepResult(step_id=step.id, output=outputs, duration_ms=sub_result.total_duration_ms)

    async def _execute_fan_out(
        self, step: DAGStep, resolved_args: dict[str, Any],
        results: dict[str, StepResult], executor,
    ) -> StepResult:
        """对 Fan-out 列表中的每一项并行执行工具调用，受 max_parallel 并发限制。"""
        items = self._resolve_fan_out(step, results)
        if not items:
            return StepResult(step_id=step.id, output=[], duration_ms=0.0)

        semaphore = asyncio.Semaphore(self._max_parallel)
        async def execute_one(item: Any, idx: int) -> Any:
            args = copy.deepcopy(resolved_args)
            args[step.fan_out_as] = item
            async with semaphore:
                call = ToolCallBlock(
                    type="tool_call", id=f"{step.id}_{idx}", name=step.tool, arguments=args,
                )
                tool_results = await executor.execute_sequential([call])
                r = tool_results[0] if tool_results else ToolResult(
                    call_id=f"{step.id}_{idx}", name=step.tool, output="", is_error=True,
                )
                return {"index": idx, "item": item, "output": r.output, "is_error": r.is_error}

        fan_results = await asyncio.gather(*[execute_one(item, i) for i, item in enumerate(items)])
        return StepResult(step_id=step.id, output=fan_results, duration_ms=0.0)

    def _resolve_inputs(self, step: DAGStep, results: dict[str, StepResult]) -> dict[str, Any]:
        """解析步骤的输入映射模板，将前置步骤的输出填充为实际参数。"""
        if not step.input_mapping:
            return dict(step.args)

        resolved = dict(step.args)
        for key, template in step.input_mapping.items():
            try:
                tpl = _jinja_env.from_string(template)
                resolved[key] = self._render_template(tpl, results)
            except Exception:
                _logger.warning("Step '%s': failed to resolve input '%s' template '%s'",
                                step.id, key, template, exc_info=True)
        return resolved

    def _resolve_fan_out(self, step: DAGStep, results: dict[str, StepResult]) -> list:
        """解析 Fan-out 模板，获取需要批量处理的目标列表。"""
        if not step.fan_out:
            return []
        try:
            tpl = _jinja_env.from_string(step.fan_out)
            value = self._render_template(tpl, results)
            if isinstance(value, list):
                return value
            return []
        except Exception:
            _logger.warning("Step '%s': failed to resolve fan_out '%s'", step.id, step.fan_out, exc_info=True)
            return []

    def _render_template(self, tpl, results: dict[str, StepResult]) -> Any:
        """渲染 Jinja2 模板，将结果字典注入为变量，并尝试将输出解析为 Python 字面量。"""
        namespace: dict[str, Any] = {}
        for sid, sr in results.items():
            if not sr.skipped:
                namespace[f"step_{sid}"] = {"output": sr.output, "error": sr.error}
        try:
            rendered = tpl.render(**namespace)
            import ast
            try:
                return ast.literal_eval(rendered)
            except (ValueError, SyntaxError):
                return rendered
        except UndefinedError:
            return ""

    def _build_cache_key(self, step: DAGStep, args: dict[str, Any]) -> str | None:
        """根据步骤 ID、参数和缓存策略生成缓存键（SHA256 哈希）。

        cache_policy 为 "none" 时返回 None；为 "always" 时不包含参数；
        其他情况包含参数以确保缓存准确性。
        """
        if step.cache_policy == "none":
            return None
        import hashlib
        import json
        if step.cache_policy == "always":
            raw = json.dumps({"step": step.id}, sort_keys=True)
        else:
            raw = json.dumps({"step": step.id, "args": args}, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()