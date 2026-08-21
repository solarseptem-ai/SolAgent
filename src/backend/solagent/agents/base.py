"""Agent 基础抽象类。

定义所有 Agent 执行模式的公共基类 BaseAgent，封装了通用的执行流程：
- 上下文准备（内存注入、技能加载、中间件执行）
- 流式/非流式执行入口（run / run_stream）
- 终止条件组装与检查
- 工具调用执行与结果压缩
- LLM 调用重试与熔断保护
- 事件发射与状态保存/恢复

子类只需实现 _execute_stream() 方法即可定义具体的 Agent 执行模式（如 ReAct、DAG 等）。
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, ClassVar

from solagent.agents.context import compress_tool_result_block, smart_trim_messages
from solagent.agents.hitl import HITLManager
from solagent.agents.hooks import AgentHooks
from solagent.agents.memory.manager import MemoryManager
from solagent.agents.middleware.chain import MiddlewareChain
from solagent.agents.tools.guard import ToolGuard
from solagent.agents.tools.permission import PermissionEngine
from solagent.agents.tools.registry import ToolRegistry
from solagent.core.logging import get_trace_id, set_trace_id
from solagent.agents.termination import TerminatedError
from solagent.errors.base import AgentError
from solagent.errors.circuit import CircuitBreaker
from solagent.errors.classifier import classify_error, is_stream_drop
from solagent.errors.llm import LLMError, RateLimitError
from solagent.events.bus import EventBus
from solagent.events.scope import EventScope
from solagent.events.types import AgentEvent, AgentEventType
from solagent.llms.retry import RetryPolicy
from solagent.llms.retry.policy import _is_retryable
from solagent.schema.abort import AbortError
from solagent.schema.agent import AgentConfig, AgentResult
from solagent.schema.llm import LLMRequest, LLMResponse, LLMStreamChunk, TokenUsage
from solagent.schema.messages import Message, MessageRole, TextBlock, ToolCallBlock, ToolResultBlock
from solagent.schema.tools import ToolResult

_logger = logging.getLogger(__name__)


@dataclass
class AgentContext:
    """Agent 执行上下文，聚合运行时的全部依赖和资源。

    包含配置、LLM 提供者、工具注册表、钩子、中间件、记忆、权限、守卫、
    消息历史、事件总线、熔断器等组件，是 Agent 执行过程中各模块共享的状态容器。
    """
    config: AgentConfig
    provider: Any
    tools: ToolRegistry = field(default_factory=ToolRegistry)
    hooks: AgentHooks = field(default_factory=AgentHooks)
    middleware: MiddlewareChain = field(default_factory=MiddlewareChain)
    memory: MemoryManager | None = None
    hitl: HITLManager | None = None
    permission: PermissionEngine | None = None
    guard: ToolGuard | None = None
    messages: list[Message] = field(default_factory=list)
    session_log: Any = field(default=None, repr=False)
    surface: Any = field(default=None, repr=False)
    metadata: dict[str, Any] = field(default_factory=dict)
    active_skills: list = field(default_factory=list)
    event_bus: EventBus = field(default_factory=EventBus)
    event_scope: EventScope = field(default_factory=EventScope)
    circuit_breaker: CircuitBreaker | None = None
    total_usage: TokenUsage = field(default_factory=TokenUsage)
    tool_injector: Any = None
    plugin_ctx: Any = None
    abort_signal: Any = field(default=None, repr=False)
    prompt_assembly: Any = field(default=None, repr=False)


@dataclass
class AgentStep:
    """Agent 执行过程中的单步记录。

    用于流式执行时向调用方产出中间状态，也用于最终结果的步骤回溯。

    属性:
        iteration: 当前迭代轮次。
        content: 步骤内容文本（如 LLM 回复摘要）。
        thinking: 模型的思考过程内容（如 DeepSeek R1 的 reasoning_content、Anthropic 的 thinking）。
        tool_calls: 该步骤产生的工具调用列表。
        tool_results: 工具执行结果列表。
        is_final: 是否为最终步骤。
        finish_reason: 结束原因（stop / max_iterations / error / timeout / tool_calls 等）。
    """
    iteration: int = 0
    content: str = ""
    thinking: str = ""
    tool_calls: list = field(default_factory=list)
    tool_results: list = field(default_factory=list)
    is_final: bool = False
    finish_reason: str = ""  # "stop", "max_iterations", "error", "return_directly", "timeout", "tool_calls"


class BaseAgent(ABC):
    """所有 Agent 执行模式的抽象基类。

    子类必须实现 _execute_stream() 方法以定义具体的执行循环逻辑。
    基类负责处理通用的生命周期管理：上下文准备、终止检查、工具执行、
    LLM 调用重试、事件发射、错误处理和资源清理。

    属性:
        context: 当前 Agent 的执行上下文（AgentContext）。
        config: 当前 Agent 的配置（AgentConfig）。
        provider: LLM 提供者实例。
        tools: 工具注册表。
    """

    def __init__(self, ctx: AgentContext):
        self._ctx = ctx
        self._total_usage = TokenUsage()
        self._steps: list[AgentStep] = []
        self._start_time = 0.0
        self._tool_results: list[ToolResult] = []
        self._use_agent_loop: bool = False
        self._tool_failure_count: dict[str, int] = {}
        self._termination = None
        self._pipeline_plugin = None

    @property
    def context(self) -> AgentContext:
        return self._ctx

    @property
    def config(self) -> AgentConfig:
        return self._ctx.config

    @property
    def provider(self) -> Any:
        return self._ctx.provider

    @property
    def tools(self) -> ToolRegistry:
        return self._ctx.tools

    async def _execute(self) -> AgentResult:
        """默认实现：消费 _execute_stream() 或委托给 AgentLoop。

        当 _use_agent_loop 为 True 时，创建 AgentLoop 作为内部驱动引擎，
        mode 不再需要实现 _execute_stream()。
        子类通常不需要重写此方法。
        """
        if self._use_agent_loop:
            return await self._execute_via_agent_loop()
        final_content = ""
        final_reason = "stop"
        async for step in self._execute_stream():
            if step.is_final:
                final_content = step.content
                final_reason = step.finish_reason or "stop"
        return self._make_result(final_content, list(self._ctx.messages), final_reason)

    async def _execute_via_agent_loop(self) -> AgentResult:
        from solagent.agents.inbox import Inbox
        from solagent.agents.loop import AgentLoop
        from solagent.core.session_log import SessionLog

        session_log = self._ctx.session_log or SessionLog()

        system_parts: list[str] = []
        user_messages: list[Message] = []
        for msg in self._ctx.messages:
            if msg.role == MessageRole.SYSTEM:
                for block in msg.content:
                    if isinstance(block, TextBlock) and block.text.strip():
                        system_parts.append(block.text)
            else:
                user_messages.append(msg)

        loop = AgentLoop(
            inbox=Inbox(),
            llm_provider=self._ctx.provider,
            tool_registry=self._ctx.tools,
            tool_executor=self._make_executor(),
            system_prompt="\n\n".join(system_parts),
            model=self._ctx.config.model,
            temperature=self._ctx.config.temperature,
            max_tokens=self._ctx.config.max_tokens,
            session_log=session_log,
            ctx=self._ctx.plugin_ctx,
        )

        # ponytail: send only user messages not already in the session log;
        # resume callers should pre-send new input via loop.send() for continuation
        existing_user = {m.model_dump(mode="json") for m in session_log.derive_messages()
                         if m.role == MessageRole.USER}
        for msg in user_messages:
            if msg.model_dump(mode="json") not in existing_user:
                loop.send(msg)

        await loop.kick()
        await loop.when_idle()
        final_messages = session_log.derive_messages()
        last_content = ""
        if final_messages:
            last = final_messages[-1]
            if hasattr(last, "content"):
                c = last.content
                if isinstance(c, list) and c:
                    last_content = str(getattr(c[-1], "text", str(c[-1])))
                elif isinstance(c, str):
                    last_content = c
        return self._make_result(last_content, final_messages, "stop")

    @abstractmethod
    async def _execute_stream(self) -> AsyncIterator[AgentStep]:
        """流式执行 agent 循环。每个 mode 必须实现此方法。

        约定：
        - 必须直接修改 self._ctx.messages（不用局部副本）
        - 每个有意义的步骤调用 self._add_step()
        - 最终步骤必须设置 is_final=True 和 finish_reason
        """
        ...

    async def _prepare_context(self) -> None:
        """执行运行前的上下文准备工作，被 run() 和 run_stream() 共享调用。

        包括：触发 before_loop 钩子、注入记忆系统提示、加载活跃技能、
        提取并注入原始任务描述、启动插件流水线、执行中间件链。
        """
        await self._ctx.hooks.trigger(self._ctx.hooks.before_loop, {"config": self._ctx.config})

        if self._ctx.prompt_assembly is not None:
            prompt = self._ctx.prompt_assembly.assemble(self._ctx)
            if prompt:
                self._inject_system_message(prompt)
        else:
            if self._ctx.memory:
                memory_block = await self._ctx.memory.system_prompt_block()
                if memory_block:
                    self._inject_system_message(f"<memory-context>\n{memory_block}\n</memory-context>")

            if self._ctx.active_skills:
                skill_lines = ["## Available Skills"]
                for skill in self._ctx.active_skills:
                    desc = getattr(skill, "description", "") or ""
                    skill_lines.append(f"- {skill.name}: {desc}")
                skill_lines.append("To load a skill's full instructions, call skill_view('<skill_name>').")
                self._inject_system_message("\n".join(skill_lines))

            original_task = self._extract_original_task()
            if original_task:
                self._inject_system_message(
                    f"<original-task>\nYour original task is: {original_task}\n"
                    "Keep this task in mind throughout execution. Do not drift or change scope.\n"
                    "</original-task>"
                )

        if self._ctx.plugin_ctx is not None:
            from solagent.cordis.events import BeforeAgentLoopEvent
            from solagent.plugins.pipeline import ToolPipelinePlugin
            self._pipeline_plugin = ToolPipelinePlugin(self._ctx.plugin_ctx)
            await self._pipeline_plugin.start()
            self._ctx.plugin_ctx.waterfall(BeforeAgentLoopEvent(
                messages=self._ctx.messages,
                config=self._ctx.config,
            ))

        self._ctx.middleware.inject_provider(self._ctx.provider)
        context = {"messages": self._ctx.messages, "config": self._ctx.config}
        context = await self._ctx.middleware.execute(context)
        self._ctx.messages = context.get("messages", self._ctx.messages)

    def _inject_system_message(self, text: str) -> None:
        """注入系统消息到 messages 和 SessionLog（如果存在）。"""
        msg = Message.system(text)
        if self._ctx.session_log is not None:
            from solagent.core.session_log import DurableEventType
            self._ctx.session_log.append(DurableEventType.SYSTEM_INJECT, data={"message": msg.model_dump(mode="json")})
        self._ctx.messages.insert(0, msg)

    def _log_step_start(self, iteration: int) -> None:
        if self._ctx.session_log is not None:
            from solagent.core.session_log import DurableEventType
            self._ctx.session_log.append(DurableEventType.STEP_START, data={"iteration": iteration})

    def _log_step_end(self, iteration: int) -> None:
        if self._ctx.session_log is not None:
            from solagent.core.session_log import DurableEventType
            self._ctx.session_log.append(DurableEventType.STEP_END, data={"iteration": iteration})

    def _extract_original_task(self) -> str | None:
        """从消息历史中查找第一条用户消息的文本内容，作为原始任务摘要（最多 2000 字符）。"""
        for msg in self._ctx.messages:
            if msg.role == MessageRole.USER:
                for block in msg.content:
                    if isinstance(block, TextBlock) and block.text.strip():
                        text = block.text.strip()
                        return text[:2000] if len(text) > 2000 else text
        return None

    async def _check_termination(self, step: AgentStep) -> None:
        """检查当前步骤是否满足终止条件，满足则抛出 TerminatedError 中断执行。"""
        if self._termination is None:
            self._termination = self._build_termination()
        self._ctx.total_usage = self._total_usage
        if await self._termination.should_stop(self._ctx, step):
            raise TerminatedError(f"Termination condition met at step {step.iteration}")

    def _build_termination(self):
        """组装终止条件检查器。

        优先使用配置中指定的终止条件列表，未配置时回退到默认行为：
        最大迭代次数 + 可选的超时限制。
        """
        from solagent.agents.termination import (
            CompositeTermination,
            ExternalTermination,
            MaxIterationsTermination,
            TextMentionTermination,
            TimeoutTermination,
            TokenBudgetTermination,
        )

        condition_map = {
            "max_iterations": lambda c: MaxIterationsTermination(
                c.get("max_iterations", self._ctx.config.max_iterations)
            ),
            "timeout": lambda c: TimeoutTermination(c.get("timeout_seconds", self._ctx.config.max_execution_time)),
            "text_mention": lambda c: TextMentionTermination(c.get("texts", [])),
            "token_budget": lambda c: TokenBudgetTermination(c.get("max_total_tokens", self._ctx.config.max_tokens)),
            "external": lambda c: ExternalTermination(),
        }

        conditions: list = []
        configured = self._ctx.config.termination_conditions

        if configured:
            for entry in configured:
                cond_type = entry.get("type", "")
                factory = condition_map.get(cond_type)
                if factory:
                    conditions.append(factory(entry))
        else:
            conditions.append(MaxIterationsTermination(self._ctx.config.max_iterations))
            if self._ctx.config.max_execution_time > 0:
                conditions.append(TimeoutTermination(self._ctx.config.max_execution_time))

        return CompositeTermination(conditions)

    async def run(self) -> AgentResult:
        """非流式执行 Agent，返回最终的 AgentResult。

        处理超时、取消、终止和各类异常，确保无论成功或失败都有完整的结果对象返回。
        """
        self._start_time = time.monotonic()
        set_trace_id(get_trace_id())
        await self._prepare_context()
        event_id = f"agent-{id(self)}-{int(self._start_time)}"
        self._ctx.event_scope.push(event_id)
        if self._ctx.session_log is not None:
            from solagent.core.session_log import DurableEventType
            self._ctx.session_log.append(DurableEventType.TURN_START, turn=1, step=0)
        await self._emit_event(AgentEventType.AGENT_START, {"agent_class": self.__class__.__name__}, event_id=event_id)
        await self._emit_event(AgentEventType.AGENT_STATE_CHANGE, {"from": "idle", "to": "running"}, event_id=event_id)
        try:
            if self._ctx.config.max_execution_time > 0:
                result = await asyncio.wait_for(self._execute(), timeout=self._ctx.config.max_execution_time)
            else:
                result = await self._execute()
        except TimeoutError:
            await self._emit_event(AgentEventType.AGENT_ERROR, {"error": f"timed out after {self._ctx.config.max_execution_time}s"}, event_id=event_id)
            await self._emit_event(AgentEventType.AGENT_STATE_CHANGE, {"from": "running", "to": "error"}, event_id=event_id)
            return self._make_result(f"Agent timed out after {self._ctx.config.max_execution_time}s", list(self._ctx.messages), "timeout")
        except asyncio.CancelledError:
            await self._emit_event(AgentEventType.AGENT_ERROR, {"error": "cancelled"}, event_id=event_id)
            await self._emit_event(AgentEventType.AGENT_STATE_CHANGE, {"from": "running", "to": "error"}, event_id=event_id)
            await self._ctx.hooks.trigger(self._ctx.hooks.on_error, {"error": "cancelled", "hitl": self._ctx.hitl})
            return self._make_result("Agent execution cancelled", list(self._ctx.messages), "cancelled")
        except AbortError as e:
            await self._emit_event(AgentEventType.AGENT_ERROR, {"error": str(e)}, event_id=event_id)
            await self._emit_event(AgentEventType.AGENT_STATE_CHANGE, {"from": "running", "to": "error"}, event_id=event_id)
            return self._make_result(str(e), list(self._ctx.messages), "aborted")
        except TerminatedError as e:
            await self._emit_event(AgentEventType.AGENT_ERROR, {"error": str(e)}, event_id=event_id)
            await self._emit_event(AgentEventType.AGENT_STATE_CHANGE, {"from": "running", "to": "error"}, event_id=event_id)
            return self._make_result(str(e), list(self._ctx.messages), "terminated")
        except AgentError as e:
            _logger.error("Agent error in %s: %s", self.__class__.__name__, e)
            await self._emit_event(AgentEventType.AGENT_ERROR, {"error": str(e)}, event_id=event_id)
            await self._emit_event(AgentEventType.AGENT_STATE_CHANGE, {"from": "running", "to": "error"}, event_id=event_id)
            await self._ctx.hooks.trigger(self._ctx.hooks.on_error, {"error": e, "hitl": self._ctx.hitl})
            return self._make_result(f"Agent error: {e}", list(self._ctx.messages), "error")
        except Exception as e:
            _logger.exception("Unexpected error in %s", self.__class__.__name__)
            await self._emit_event(AgentEventType.AGENT_ERROR, {"error": str(e)}, event_id=event_id)
            await self._emit_event(AgentEventType.AGENT_STATE_CHANGE, {"from": "running", "to": "error"}, event_id=event_id)
            await self._ctx.hooks.trigger(self._ctx.hooks.on_error, {"error": e, "hitl": self._ctx.hitl})
            return self._make_result(f"Unexpected error: {e}", list(self._ctx.messages), "error")
        finally:
            if self._ctx.session_log is not None:
                from solagent.core.session_log import DurableEventType
                self._ctx.session_log.append(DurableEventType.TURN_END, turn=1, step=0)
        await self._emit_event(AgentEventType.AGENT_STATE_CHANGE, {"from": "running", "to": "done"}, event_id=event_id)
        await self._emit_event(AgentEventType.AGENT_END, {"content": result.content[:200]}, event_id=event_id)
        await self._ctx.hooks.trigger(self._ctx.hooks.after_loop, {"result": result})
        if self._ctx.plugin_ctx is not None:
            from solagent.cordis.events import AfterAgentLoopEvent
            self._ctx.plugin_ctx.emit(AfterAgentLoopEvent(messages=self._ctx.messages, result=result))
        self._ctx.event_scope.pop(event_id)
        return result

    async def run_stream(self) -> AsyncIterator[AgentStep]:
        """流式执行 Agent，逐步产出 AgentStep。

        适用于需要实时展示 Agent 思考过程、工具调用和中间结果的前端场景。
        """
        self._start_time = time.monotonic()
        await self._prepare_context()
        event_id = f"agent-{id(self)}-{int(self._start_time)}"
        self._ctx.event_scope.push(event_id)
        await self._emit_event(AgentEventType.AGENT_START, {"agent_class": self.__class__.__name__}, event_id=event_id)
        await self._emit_event(AgentEventType.AGENT_STATE_CHANGE, {"from": "idle", "to": "running"}, event_id=event_id)
        try:
            async for step in self._execute_stream():
                # _execute_stream() manages self._steps via _add_step() — do not double-append
                yield step
        except asyncio.CancelledError:
            await self._emit_event(AgentEventType.AGENT_ERROR, {"error": "cancelled"}, event_id=event_id)
            await self._emit_event(AgentEventType.AGENT_STATE_CHANGE, {"from": "running", "to": "error"}, event_id=event_id)
            yield AgentStep(iteration=0, content="Agent execution cancelled", is_final=True)
        except AgentError as e:
            _logger.error("Agent error in %s (stream): %s", self.__class__.__name__, e)
            await self._emit_event(AgentEventType.AGENT_ERROR, {"error": str(e)}, event_id=event_id)
            await self._emit_event(AgentEventType.AGENT_STATE_CHANGE, {"from": "running", "to": "error"}, event_id=event_id)
            yield AgentStep(iteration=0, content=f"Agent error: {e}", is_final=True)
        except Exception as e:
            _logger.exception("Unexpected error in %s (stream)", self.__class__.__name__)
            await self._emit_event(AgentEventType.AGENT_ERROR, {"error": str(e)}, event_id=event_id)
            await self._emit_event(AgentEventType.AGENT_STATE_CHANGE, {"from": "running", "to": "error"}, event_id=event_id)
            yield AgentStep(iteration=0, content=f"Unexpected error: {e}", is_final=True)
        else:
            await self._emit_event(AgentEventType.AGENT_STATE_CHANGE, {"from": "running", "to": "done"}, event_id=event_id)
            await self._emit_event(AgentEventType.AGENT_END, {"content": str(self._steps[-1].content)[:200] if self._steps else ""}, event_id=event_id)
        await self._ctx.hooks.trigger(self._ctx.hooks.after_loop, {"result": None})
        if self._ctx.plugin_ctx is not None:
            from solagent.cordis.events import AfterAgentLoopEvent
            self._ctx.plugin_ctx.emit(AfterAgentLoopEvent(messages=self._ctx.messages, result=None))
        self._ctx.event_scope.pop(event_id)
    
    def save_state(self) -> dict:
        """保存 Agent 当前状态为字典，用于检查点持久化。"""
        return {
            "messages": [m.model_dump() for m in self._ctx.messages],
            "total_usage": self._total_usage.model_dump(),
            "steps": len(self._steps),
            "metadata": self._ctx.metadata,
        }
    
    def load_state(self, state: dict) -> None:
        """从检查点字典恢复 Agent 状态（消息历史、token 用量、元数据）。"""
        self._ctx.messages = [Message.model_validate(m) for m in state.get("messages", [])]
        self._total_usage = TokenUsage.model_validate(state.get("total_usage", {}))
        self._ctx.metadata = state.get("metadata", {})
    
    def _make_result(self, content: str, messages: list[Message], finish_reason: str = "stop") -> AgentResult:
        """组装 AgentResult，包含内容、消息历史、token 用量、耗时和步骤记录。"""
        duration_ms = int((time.monotonic() - self._start_time) * 1000)
        return AgentResult(content=content, messages=messages, token_usage=self._total_usage,
                          finish_reason=finish_reason, duration_ms=duration_ms, tool_results=list(self._tool_results),
                          steps=[{"iteration": s.iteration, "content": s.content, "tool_calls": s.tool_calls,
                                  "tool_results": s.tool_results, "is_final": s.is_final} for s in self._steps])
    
    def _add_step(self, iteration: int, content: str = "", tool_calls: list | None = None,
                  tool_results: list | None = None, is_final: bool = False) -> AgentStep:
        """向步骤历史中添加一条 AgentStep 并返回该步骤。"""
        step = AgentStep(iteration=iteration, content=content, tool_calls=tool_calls or [],
                        tool_results=tool_results or [], is_final=is_final)
        self._steps.append(step)
        return step

    def _make_executor(self):
        """创建工具执行器实例，传入当前工具注册表和守卫配置。"""
        from solagent.agents.tools.executor import ToolExecutor
        pipeline = getattr(self._pipeline_plugin, '_pipeline', None) if self._pipeline_plugin else None
        executor = ToolExecutor(self.tools, guard=self._ctx.guard, tool_pipeline=self._pipeline_plugin, pipeline=pipeline)
        executor._abort_signal = self._ctx.abort_signal
        return executor

    def _build_tool_calls(self, response) -> list[ToolCallBlock]:
        """将 LLM 响应中的 tool_calls 转换为内部 ToolCallBlock 列表。"""
        return [ToolCallBlock(type="tool_call", id=tc.id, name=tc.name, arguments=tc.arguments) for tc in response.tool_calls]

    def _get_tool_definitions(self) -> list:
        """获取当前可用的工具定义列表，支持工具注入器的渐进式披露策略。"""
        from solagent.schema.tools import ToolListContext
        if self._ctx.tool_injector is not None:
            import json
            ctx = ToolListContext(
                token_budget=self._ctx.config.max_tokens,
                active_skills=[s.name for s in self._ctx.active_skills],
            )
            injection = self._ctx.tool_injector.prepare(["core", "memory", "search", "interaction"], ctx)
            tools = []
            for entry in injection.immediate:
                tools.append(entry.tool)
            if injection.deferred:
                func = self._ctx.tool_injector._make_tool_search_bridge(injection.deferred)
                from solagent.agents.tools.defs import ToolDef
                bridge = ToolDef()
                bridge.id = "tool_search"
                bridge.description = json.dumps(func["function"]["description"])
                tools.append(bridge)
            return tools
        return self.tools.get_definitions()

    async def _execute_tools_and_append(self, executor, calls: list[ToolCallBlock], all_messages: list[Message]) -> list[ToolResult]:
        """执行工具调用并将结果追加到消息列表，自动压缩过长输出。

        同时更新工具失败计数、触发工具调用事件、 enrich 错误提示信息。
        """
        await self._ctx.hooks.trigger(self._ctx.hooks.before_tool_call, {"calls": [c.model_dump() for c in calls]})
        for call in calls:
            await self._emit_event(AgentEventType.TOOL_CALL_START,
                                   {"tool_name": call.name, "tool_args": call.arguments},
                                   event_id=f"tool-{call.id}")
        try:
            results = await executor.execute_smart(calls)
        except Exception as e:
            for call in calls:
                await self._emit_event(AgentEventType.TOOL_CALL_ERROR,
                                       {"tool_name": call.name, "error": str(e)},
                                       event_id=f"tool-{call.id}")
            raise
        for call, r in zip(calls, results):
            try:
                tool_def = self.tools.get(call.name)
            except Exception:
                tool_def = None
            if tool_def and getattr(tool_def, "return_directly", False):
                r.metadata["return_directly"] = True
            result_block = ToolResultBlock(type="tool_result", tool_call_id=r.call_id, content=r.output, is_error=r.is_error)
            original_len = len(r.output)
            result_block = compress_tool_result_block(result_block, tool_name=call.name)
            result_block = self._enrich_tool_result(result_block, call.name, original_len)
            all_messages.append(Message.tool_result([result_block]))
            self._tool_results.append(r)
            if r.is_error:
                self._tool_failure_count[call.name] = self._tool_failure_count.get(call.name, 0) + 1
                await self._emit_event(AgentEventType.TOOL_CALL_ERROR,
                                       {"tool_name": call.name, "error": r.output[:200]},
                                       event_id=f"tool-{call.id}")
            else:
                self._tool_failure_count.pop(call.name, None)
                await self._emit_event(AgentEventType.TOOL_CALL_END,
                                       {"tool_name": call.name, "output": r.output[:200]},
                                       event_id=f"tool-{call.id}")
        await self._ctx.hooks.trigger(self._ctx.hooks.after_tool_call, {"results": [r.model_dump() for r in results]})
        for call in calls:
            await self._emit_event(AgentEventType.TOOL_CALL_STATE_CHANGE,
                                   {"tool_call_id": call.id, "tool_name": call.name, "state": call.state.value},
                                   event_id=f"tool-{call.id}")
        return results

    _ERROR_SUGGESTIONS: ClassVar[dict[str, str]] = {
        "file not found": "Check the file path — it may be relative, incorrect, or the file doesn't exist yet. Use list_dir to explore available files.",
        "not found": "The resource was not found. Verify the name/path and try again with correct parameters.",
        "permission denied": "You don't have permission to access this. Consider using read_file instead of write_file, or check the file mode.",
        "invalid": "The input was invalid. Check the parameter format — it may need to be a different type or structure.",
        "timeout": "The operation timed out. The resource may be too large or unresponsive. Try with smaller scope or add a timeout.",
        "syntax error": "The code has a syntax error. Check indentation, quotes, brackets, and import statements.",
        "module not found": "The Python module is not installed. Try `uv pip install <module>` or check the import name.",
        "unknown": "The tool name or command is not recognized. Check available tools with get_tool_definitions or use list_dir/read_file to explore.",
    }

    def _enrich_tool_result(self, block: ToolResultBlock, tool_name: str, original_len: int) -> ToolResultBlock:
        """增强工具结果文本：为错误结果附加建议提示，为截断结果附加省略说明。"""
        enriched = block.content

        if block.is_error:
            failure_count = self._tool_failure_count.get(tool_name, 0) + 1
            error_lower = block.content.lower()
            for pattern, suggestion in self._ERROR_SUGGESTIONS.items():
                if pattern in error_lower:
                    enriched += f"\n\n[Suggestion] {suggestion}"
                    break
            if failure_count >= 2:
                enriched += (
                    f"\n\n[Consecutive Failures] {tool_name} has failed {failure_count} times in a row. "
                    "Consider using a different tool or approach instead of retrying the same call."
                )
        else:
            if len(block.content) < original_len:
                omitted = original_len - len(block.content)
                enriched += f"\n\n[Truncated] {omitted} chars omitted. Output was truncated to fit context window."

        if enriched == block.content:
            return block
        return ToolResultBlock(
            type=block.type,
            tool_call_id=block.tool_call_id,
            content=enriched,
            is_error=block.is_error,
        )

    async def _chat_with_retry(self, request: LLMRequest, max_retries: int = 3) -> LLMResponse:
        """带重试的 LLM 调用，集成熔断器、错误分类和指数退避。

        在熔断器打开时会快速失败，避免对不可用的 LLM 提供者持续施压。
        """
        cb = self._ctx.circuit_breaker
        if cb is not None and not await cb.allow_request():
            _logger.warning("Circuit breaker open, failing fast on LLM call")
            raise LLMError("Circuit breaker is open — LLM provider temporarily unavailable")

        policy = RetryPolicy(max_retries=max_retries - 1, base_delay=1.0, max_delay=60.0, jitter=True)
        last_original_error: Exception | None = None
        event_id = f"llm-{id(self)}-{int(time.monotonic() * 1000)}"

        await self._emit_event(AgentEventType.LLM_CALL_START,
                               {"model": request.model, "message_count": len(request.messages)},
                               event_id=event_id)

        async def on_retry(attempt: int, exc: Exception, delay: float) -> None:
            await self._emit_event(AgentEventType.RETRY_ATTEMPT,
                                   {"model": request.model, "attempt": attempt, "error": str(exc), "delay": delay},
                                   event_id=event_id)
            if isinstance(exc, RateLimitError):
                await self._emit_event(AgentEventType.RATE_LIMITED,
                                       {"model": request.model, "retry_after": getattr(exc, "retry_after", None)},
                                       event_id=event_id)

        async def _call():
            nonlocal last_original_error
            try:
                return await self.provider.chat(request)
            except RetryPolicy.RETRYABLE_EXCEPTIONS:
                raise
            except Exception as e:
                last_original_error = e
                raise LLMError(str(e)) from e

        try:
            result = await policy.execute(_call, on_retry=on_retry)
            if cb is not None:
                await cb.record_success()
            await self._emit_event(AgentEventType.LLM_CALL_END,
                                   {"model": request.model, "content": result.content[:200] if result.content else ""},
                                   event_id=event_id)
            return result
        except LLMError:
            if last_original_error is not None:
                await self._emit_event(AgentEventType.LLM_CALL_ERROR,
                                       {"model": request.model, "error": str(last_original_error)},
                                       event_id=event_id)
                if cb is not None:
                    retriable, _ = classify_error(last_original_error)
                    if retriable:
                        await cb.record_failure()
                raise last_original_error
            raise
        except Exception as e:
            await self._emit_event(AgentEventType.LLM_CALL_ERROR,
                                   {"model": request.model, "error": str(e)},
                                   event_id=event_id)
            if cb is not None:
                retriable, _ = classify_error(e)
                if retriable:
                    await cb.record_failure()
            raise

    async def _chat_stream_with_retry(self, request: LLMRequest, max_retries: int = 3) -> AsyncIterator[LLMStreamChunk]:
        """带重试的流式 LLM 调用。

        一旦开始产出 chunk 则不再重试；累积流中的 token 用量到 self._total_usage。
        """
        event_id = f"llm-stream-{id(self)}-{int(time.monotonic() * 1000)}"
        chunk_count = 0
        for attempt in range(max_retries):
            has_yielded = False
            last_usage: TokenUsage | None = None
            try:
                async for chunk in self.provider.chat_stream(request):
                    if chunk is None:
                        continue
                    has_yielded = True
                    if chunk.usage:
                        last_usage = chunk.usage
                    yield chunk
                    chunk_count += 1
                    await self._emit_event(AgentEventType.STREAM_DELTA,
                                           {"content": chunk.content, "is_thinking": chunk.is_thinking,
                                            "tool_call_id": chunk.tool_call_id},
                                           event_id=event_id)
                if last_usage:
                    self._total_usage = self._total_usage + last_usage
                await self._emit_event(AgentEventType.STREAM_END,
                                       {"total_chunks": chunk_count},
                                       event_id=event_id)
                return
            except Exception as e:
                if has_yielded:
                    raise
                if attempt == max_retries - 1:
                    raise
                if not _is_retryable(e):
                    raise
                delay = min(1.0 * (2 ** attempt), 30.0)
                await self._emit_event(AgentEventType.RETRY_ATTEMPT,
                                       {"model": request.model, "attempt": attempt + 1,
                                        "error": str(e), "delay": delay},
                                       event_id=event_id)
                if isinstance(e, RateLimitError):
                    await self._emit_event(AgentEventType.RATE_LIMITED,
                                           {"model": request.model,
                                            "retry_after": getattr(e, "retry_after", None)},
                                           event_id=event_id)
                await asyncio.sleep(delay)

    def _enforce_token_limit(self, messages: list[Message], max_tokens: int = 100000) -> list[Message]:
        """强制将消息列表裁剪到 token 限制内，使用基于重要性的智能裁剪算法。"""
        return smart_trim_messages(messages, max_tokens=max_tokens,
                               keep_last=self._ctx.config.compact_keep_last,
                               min_keep=self._ctx.config.compact_min_keep)

    async def _emit_event(self, event_type: AgentEventType, data: dict, event_id: str | None = None) -> None:
        """向事件总线发射 Agent 生命周期事件，同时向插件上下文广播（若存在）。"""
        event_id_str = event_id or self.__class__.__name__
        topic = f"{event_type.value}/{self.__class__.__name__}"
        parent_id = self._ctx.event_scope.current or None
        event = AgentEvent(
            event_type=event_type,
            data=data,
            session_id=self._ctx.event_bus._session_id,
            topic=topic,
            source=event_id_str,
            parent_event_id=parent_id,
        )
        self._ctx.event_bus.emit(event)

        if self._ctx.plugin_ctx is not None:
            from solagent.cordis.events import AgentLifecycleEvent
            self._ctx.plugin_ctx.emit(AgentLifecycleEvent(
                event_type=event_type.value,
                data=data,
                source=event_id_str,
            ))