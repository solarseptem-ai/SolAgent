"""工具调用管道插件模块。

实现完整的工具执行流水线，将一次工具调用拆解为多个有序阶段：
解析 -> 校验 -> 守卫 -> 缓存 -> 人工审批 -> 钩子 -> 超时 -> 执行 -> 后处理 -> 终结化。
每个阶段都是独立的 PipelineStage，可灵活插拔或自定义。
同时提供 HITL（Human-In-The-Loop）审批通道插件。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from solagent.plugins import Plugin, PluginEvent
from solagent.schema.messages import ToolCallBlock, ToolCallState
from solagent.schema.tools import ToolCallContext, ToolResult
from solagent.agents.tools.pipeline import ToolPipeline

_logger = logging.getLogger(__name__)


@dataclass
class PipelineContext:
    """工具管道执行上下文，贯穿整个流水线各阶段。

    Attributes:
        tool_call_name: 被调用工具的名称。
        arguments: 原始参数字典。
        call: 关联的 ToolCallBlock 实例（可选）。
        data: 各阶段共享的中间数据字典。
        result: 最终工具执行结果。
        error: 错误信息（若发生）。
        skipped: 是否被某阶段跳过（短路后续阶段）。
        cached: 结果是否来自缓存。
        timeout: 当前工具的超时秒数。
    """
    tool_call_name: str
    arguments: dict[str, Any]
    call: ToolCallBlock | None = None
    data: dict[str, Any] = field(default_factory=dict)
    result: ToolResult | None = None
    error: str | None = None
    skipped: bool = False
    cached: bool = False
    timeout: float = 420.0


class PipelineStage(Plugin):
    """管道阶段的抽象基类，所有具体阶段需重写 execute 方法。"""
    async def execute(self, ctx: PipelineContext) -> PipelineContext:
        return ctx


class ResolveStage(PipelineStage):
    """解析阶段：通过 tool_registry 查找工具定义。"""
    name = "resolve_stage"

    async def execute(self, ctx: PipelineContext) -> PipelineContext:
        if ctx.skipped:
            return ctx
        try:
            ctx.data["tool"] = self.ctx.tool_registry.get(ctx.tool_call_name)
        except Exception:
            ctx.error = f"Tool '{ctx.tool_call_name}' not found"
            ctx.skipped = True
        return ctx


class ParseStage(PipelineStage):
    """解析阶段：将原始参数解析并尝试修复格式问题。"""
    name = "parse_stage"

    async def execute(self, ctx: PipelineContext) -> PipelineContext:
        if ctx.skipped:
            return ctx
        from solagent.agents.tools.validator import ToolArgumentError, parse_and_repair_arguments
        try:
            ctx.data["parsed_args"] = parse_and_repair_arguments(ctx.arguments)
        except ToolArgumentError as e:
            ctx.error = f"Invalid arguments: {e}"
            ctx.skipped = True
        return ctx


class ValidateStage(PipelineStage):
    """校验阶段：使用 Pydantic 模型校验参数合法性。"""
    name = "validate_stage"

    async def execute(self, ctx: PipelineContext) -> PipelineContext:
        if ctx.skipped:
            return ctx
        if ctx.call:
            ctx.call.state = ToolCallState.VALIDATING
        tool = ctx.data.get("tool")
        if tool is None:
            ctx.error = "No tool resolved"
            ctx.skipped = True
            return ctx
        try:
            ctx.data["params"] = tool.params_model.model_validate(ctx.data["parsed_args"])
        except PydanticValidationError as e:
            ctx.error = f"Argument validation failed: {e}"
            ctx.skipped = True
        return ctx


class GuardStage(PipelineStage):
    """守卫阶段：调用 guard 进行安全检查（命令、文件、循环、频率）。"""
    name = "guard_stage"

    async def execute(self, ctx: PipelineContext) -> PipelineContext:
        if ctx.skipped:
            return ctx
        try:
            guard = self.ctx.guard
        except AttributeError:
            return ctx
        if guard is None:
            return ctx
        guard_ctx = self.ctx.root._services.get("_guard_context")
        if guard_ctx is None:
            return ctx
        result = await guard.check(ctx.tool_call_name, ctx.arguments, guard_ctx)
        if result.blocked:
            ctx.error = f"Blocked by guard [{result.code}]: {result.reason}"
            ctx.skipped = True
            if ctx.call:
                ctx.call.state = ToolCallState.DENIED
        return ctx


class CacheStage(PipelineStage):
    """缓存阶段：若工具配置了 cache_ttl 且命中缓存，则短路返回。"""
    name = "cache_stage"

    async def execute(self, ctx: PipelineContext) -> PipelineContext:
        if ctx.skipped:
            return ctx
        try:
            cache = self.ctx.tool_cache
        except AttributeError:
            return ctx
        if cache is None:
            return ctx
        tool = ctx.data.get("tool")
        if tool is None:
            return ctx
        ttl = getattr(tool, "cache_ttl", 0)
        if ttl == 0:
            return ctx
        cached = cache.get(tool.id, ctx.arguments)
        if cached is not None:
            ctx.result = cached
            ctx.cached = True
            ctx.skipped = True
            if ctx.call:
                ctx.call.state = ToolCallState.FINISHED
        return ctx


class HookStage(PipelineStage):
    """钩子阶段：在工具执行前调用 before 钩子，可拦截或修改参数。"""
    name = "hook_stage"

    async def execute(self, ctx: PipelineContext) -> PipelineContext:
        if ctx.skipped:
            return ctx
        try:
            hooks = self.ctx.tool_hooks
        except AttributeError:
            return ctx
        if hooks is None:
            return ctx
        tool = ctx.data.get("tool")
        params = ctx.data.get("params")
        if tool is None or params is None:
            return ctx
        for hook in hooks.before:
            before_result = await hook(tool.id, params, ctx.call)
            if not before_result.allowed:
                ctx.error = f"Blocked: {before_result.reason}"
                ctx.skipped = True
                if ctx.call:
                    ctx.call.state = ToolCallState.DENIED
                return ctx
            if before_result.modified_params is not None:
                ctx.data["params"] = before_result.modified_params
        if ctx.call:
            ctx.call.state = ToolCallState.ALLOWED
        return ctx


class TimeoutStage(PipelineStage):
    """工具超时策略 — 从 ToolDef.timeout_ms 读取超时，设置 deadline。"""

    name = "timeout_stage"
    default_timeout: float = 420.0

    async def execute(self, ctx: PipelineContext) -> PipelineContext:
        if ctx.skipped:
            return ctx
        tool = ctx.data.get("tool")
        if tool is not None:
            timeout_ms = getattr(tool, "timeout_ms", 0)
            if timeout_ms > 0:
                ctx.timeout = timeout_ms / 1000.0
            else:
                ctx.timeout = self.default_timeout
        return ctx


class ExecuteStage(PipelineStage):
    """执行阶段：真正调用工具的 execute 方法，带超时控制与错误钩子。"""
    name = "execute_stage"

    async def execute(self, ctx: PipelineContext) -> PipelineContext:
        if ctx.skipped:
            return ctx
        tool = ctx.data["tool"]
        params = ctx.data["params"]
        if ctx.call:
            ctx.call.state = ToolCallState.EXECUTING
        call_ctx = ToolCallContext(tool_call_id=ctx.call.id if ctx.call else "")
        start = time.monotonic()
        try:
            result = await asyncio.wait_for(
                tool.execute(params, call_ctx),
                timeout=ctx.timeout,
            )
        except TimeoutError:
            ctx.error = f"Tool timed out after {ctx.timeout}s"
            ctx.skipped = True
            if ctx.call:
                ctx.call.state = ToolCallState.FINISHED
            return ctx
        except Exception as e:
            # 先尝试由 on_error 钩子处理异常
            try:
                hooks = self.ctx.tool_hooks
            except AttributeError:
                hooks = None
            if hooks:
                for hook in hooks.on_error:
                    handled = await hook(tool.id, params, e, ctx.call)
                    if handled is not None:
                        ctx.result = handled
                        if ctx.call:
                            ctx.call.state = ToolCallState.FINISHED
                        return ctx
            ctx.error = str(e)
            ctx.skipped = True
            if ctx.call:
                ctx.call.state = ToolCallState.FINISHED
            return ctx
        ctx.data["_duration"] = time.monotonic() - start
        ctx.result = result
        return ctx


class PostProcessStage(PipelineStage):
    """后处理阶段：执行 after 钩子、写入缓存、记录工具历史到 guard 上下文。"""
    name = "post_process_stage"

    async def execute(self, ctx: PipelineContext) -> PipelineContext:
        if ctx.skipped:
            return ctx
        result = ctx.result
        if result is None:
            return ctx
        tool = ctx.data.get("tool")
        params = ctx.data.get("params")
        duration = ctx.data.get("_duration", 0.0)

        # 调用 after 钩子，允许修改结果
        try:
            hooks = self.ctx.tool_hooks
        except AttributeError:
            hooks = None
        if hooks and tool:
            for hook in hooks.after:
                result = await hook(tool.id, params, result, duration, ctx.call)

        # 若结果成功且工具有缓存配置，则写入缓存
        try:
            cache = self.ctx.tool_cache
        except AttributeError:
            cache = None
        if cache and tool and not result.is_error:
            ttl = getattr(tool, "cache_ttl", 0)
            if ttl != 0:
                cache.set(tool.id, ctx.arguments, result, ttl=ttl)

        # 将本次工具调用历史记录到 guard，用于循环检测
        try:
            guard = self.ctx.guard
        except AttributeError:
            guard = None
        if guard:
            from solagent.agents.guard.loop_detector import IDEMPOTENT_TOOLS
            guard_ctx = self.ctx.root._services.get("_guard_context")
            if guard_ctx is not None:
                from solagent.agents.guard.base import ToolHistoryEntry
                entry = ToolHistoryEntry(
                    tool_name=ctx.tool_call_name,
                    tool_args_hash=hashlib.sha256(
                        json.dumps(ctx.arguments, sort_keys=True, default=str).encode()
                    ).hexdigest(),
                    success=not result.is_error,
                    result_hash=hashlib.sha256(result.output.encode()).hexdigest()
                    if ctx.tool_call_name in IDEMPOTENT_TOOLS else "",
                )
                guard_ctx.tool_history.append(entry)

        ctx.result = result
        if ctx.call:
            ctx.call.state = ToolCallState.FINISHED
        return ctx


class HITLStage(PipelineStage):
    """HITL 审批阶段 — 在 Guard 之后、Execute 之前，检查是否需要人工审批。"""

    name = "hitl_stage"

    async def execute(self, ctx: PipelineContext) -> PipelineContext:
        if ctx.skipped:
            return ctx
        try:
            channel = self.ctx.hitl_channel
        except AttributeError:
            return ctx
        if channel is None:
            return ctx

        tool = ctx.data.get("tool")
        if tool is None:
            return ctx
        if not getattr(tool, "requires_approval", False):
            return ctx

        message = f"Approve tool '{ctx.tool_call_name}' with args: {json.dumps(ctx.arguments, default=str)[:500]}"
        approved = await channel.request_approval(ctx.tool_call_name, message, timeout=120.0)
        if not approved:
            ctx.error = f"Tool '{ctx.tool_call_name}' rejected by user"
            ctx.skipped = True
            if ctx.call:
                ctx.call.state = ToolCallState.DENIED
        return ctx


class FinalizeStage(PipelineStage):
    """内容终结化 — 对标 deepseek-harness finalizeContent()。

    对工具输出进行截断、格式化、结构化错误处理。
    """

    name = "finalize_stage"
    max_output: int = 8000
    max_error_output: int = 2000

    async def execute(self, ctx: PipelineContext) -> PipelineContext:
        if ctx.skipped or ctx.result is None:
            return ctx
        result = ctx.result
        if result.is_error and len(result.output) > self.max_error_output:
            result = result.model_copy(update={"output": result.output[:self.max_error_output] + "...[truncated]"})
        elif len(result.output) > self.max_output:
            result = result.model_copy(update={"output": result.output[:self.max_output] + "...[truncated]"})
        ctx.result = result
        return ctx


class ToolPipelinePlugin(Plugin):
    """工具管道总控插件，组合所有阶段并提供 stage 增删与运行入口。"""
    name = "tool_pipeline"
    inject = {"tool_registry": None}

    def __init__(self, ctx):
        super().__init__(ctx)
        self._stages: list[PipelineStage] = []
        self._pipeline = ToolPipeline()

    async def start(self):
        """初始化 guard 上下文，注册 HITL 与 Finalize 预/后处理器，组装默认阶段列表。"""
        from solagent.agents.guard.base import GuardContext
        self.ctx.root._services.setdefault("_guard_context", GuardContext())

        self._pipeline.add_pre(_make_hitl_handler(self.ctx))
        self._pipeline.add_post(_make_finalize_handler())

        self._stages = [
            ResolveStage(self.ctx),
            ParseStage(self.ctx),
            ValidateStage(self.ctx),
            GuardStage(self.ctx),
            CacheStage(self.ctx),
            HITLStage(self.ctx),
            HookStage(self.ctx),
            TimeoutStage(self.ctx),
            ExecuteStage(self.ctx),
            PostProcessStage(self.ctx),
            FinalizeStage(self.ctx),
        ]
        self.ctx.on(PipelineStageEvent, self._on_stage_event, mode="waterfall")

    def add_stage(self, stage: PipelineStage, position: int | None = None):
        """在管道末尾或指定位置插入新阶段。"""
        if position is None:
            self._stages.append(stage)
        else:
            self._stages.insert(position, stage)

    def remove_stage(self, stage_name: str):
        """按名称移除阶段。"""
        self._stages = [s for s in self._stages if s.name != stage_name]

    async def run(self, pctx: PipelineContext) -> ToolResult:
        """运行完整管道，出错时返回包含错误信息的 ToolResult。"""
        await self._run_pipeline(pctx)
        if pctx.error and pctx.result is None:
            return ToolResult(
                call_id=pctx.call.id if pctx.call else "",
                name=pctx.tool_call_name,
                output=pctx.error,
                is_error=True,
            )
        return pctx.result

    async def _run_pipeline(self, ctx: PipelineContext) -> PipelineContext:
        """依次执行各阶段，并在每阶段前后触发 PipelineStageEvent。"""
        for stage in self._stages:
            if ctx.skipped:
                break
            try:
                if self.ctx is not None:
                    self.ctx.waterfall(PipelineStageEvent(
                        phase="pre-execute",
                        stage_name=stage.name,
                        tool_name=ctx.tool_call_name,
                        pipeline_context=ctx,
                    ))
                ctx = await stage.execute(ctx)
                if self.ctx is not None:
                    self.ctx.waterfall(PipelineStageEvent(
                        phase="post-execute",
                        stage_name=stage.name,
                        tool_name=ctx.tool_call_name,
                        pipeline_context=ctx,
                    ))
            except Exception as e:
                ctx.error = str(e)
                break
        return ctx

    def _on_stage_event(self, event: PipelineStageEvent, next_fn):
        """阶段事件的默认透传处理器。"""
        return next_fn()


class PipelineStageEvent(PluginEvent):
    """工具管道阶段事件 — waterfall 模式，前/后阶段可拦截。"""
    phase: str = ""
    stage_name: str = ""
    tool_name: str = ""
    pipeline_context: PipelineContext | None = None


class HITLRequestEvent(PluginEvent):
    """人工审批请求事件，由 HITLChannelPlugin 发出等待外部响应。"""
    request_id: str = ""
    tool_name: str = ""
    message: str = ""


class HITLChannelPlugin(Plugin):
    """人工审批通道插件，基于 asyncio.Future 实现异步等待用户决策。"""
    name = "hitl_channel"
    inject = {}

    def __init__(self, ctx):
        super().__init__(ctx)
        self._pending: dict[str, asyncio.Future] = {}

    async def start(self):
        """向上下文暴露 hitl_channel 服务。"""
        self.ctx.provide("hitl_channel", self)

    async def request_approval(self, tool_name: str, message: str, timeout: float = 60.0) -> bool:
        """发起审批请求，通过 Future 阻塞等待外部响应，超时视为拒绝。

        Args:
            tool_name: 待审批工具名称。
            message: 审批提示信息。
            timeout: 等待超时秒数，默认 60 秒。

        Returns:
            True 表示审批通过，False 表示拒绝或超时。
        """
        import uuid
        request_id = str(uuid.uuid4())
        fut: asyncio.Future = asyncio.Future()
        self._pending[request_id] = fut
        self.ctx.emit(HITLRequestEvent(
            request_id=request_id,
            tool_name=tool_name,
            message=message,
        ))
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except TimeoutError:
            self._pending.pop(request_id, None)
            return False

    def respond(self, request_id: str, approved: bool) -> None:
        """外部调用此方法来响应审批请求。"""
        fut = self._pending.pop(request_id, None)
        if fut and not fut.done():
            fut.set_result(approved)

    def reject_all(self) -> None:
        """拒绝所有 pending 的审批请求，用于系统关闭或安全中断场景。"""
        for rid, fut in list(self._pending.items()):
            if not fut.done():
                fut.set_result(False)
            self._pending.pop(rid, None)


def _make_hitl_handler(ctx):
    """构造 ToolPipeline 预处理器：在执行前检查是否需要人工审批。"""
    async def hitl_handler(call, tool, params, next_fn):
        requires_approval = getattr(tool, "requires_approval", False)
        if not requires_approval:
            return await next_fn()
        try:
            hitl_channel = ctx.root._services.get("hitl_channel")
        except Exception:
            return await next_fn()
        if hitl_channel is None:
            return await next_fn()
        approved = await hitl_channel.request_approval(
            tool_name=call.name,
            message=f"Approve execution of '{call.name}'?",
            timeout=120.0,
        )
        if not approved:
            from solagent.agents.tools.executor import PreResult
            return PreResult(blocked=True, error=f"HITL denied: {call.name}")
        return await next_fn()
    return hitl_handler


def _make_finalize_handler():
    """构造 ToolPipeline 后处理器：对输出结果进行截断控制。"""
    MAX_ERROR = 2000
    MAX_OUTPUT = 8000

    async def finalize_handler(call, tool, params, result, next_fn):
        r = await next_fn()
        if r.is_error and len(r.output) > MAX_ERROR:
            r.output = r.output[:MAX_ERROR] + "...[truncated]"
        elif not r.is_error and len(r.output) > MAX_OUTPUT:
            r.output = r.output[:MAX_OUTPUT] + "...[truncated]"
        return r
    return finalize_handler