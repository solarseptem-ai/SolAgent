"""AgentLoop — 生产级统一驱动：Phase 状态机 + kick/turn/step + 可插拔扩展点。

扩展点（对标 ReactLoopAgent 的 Durable Events + Live Extension Points）：
- agent/request waterfall — 插件可在 LLM 请求前修改 model/temperature/tools
- agent/turn-stopping serial  — 插件可决定 turn 是否结束
- agent/request-error waterfall — 插件可决定重试/放弃
- Session-driven: SessionLog 作为状态真实来源，支持重放恢复
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Protocol

from solagent.agents.inbox import Inbox
from solagent.agents.stream_assembler import StreamAssembler
from solagent.agents.tools.executor import ToolExecutor
from solagent.agents.tools.registry import ToolRegistry
from solagent.core.session_log import DurableEventType, SessionLog
from solagent.plugins import PluginEvent
from solagent.schema.llm import LLMFinishReason, LLMRequest, LLMStreamChunk
from solagent.schema.messages import (
    Message,
    MessageRole,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
)
from solagent.schema.tools import ToolDefinition, ToolResult

_logger = logging.getLogger(__name__)


class PhaseKind(Enum):
    IDLE = auto()
    RUNNING = auto()
    MAINTENANCE = auto()


class StepEndReason(Enum):
    TURN_END = "turn_end"
    NEXT_STEP = "next_step"
    ERROR = "error"
    INTERRUPTED = "interrupted"
    MAX_TOKENS = "max_tokens"


class PreStepDecision(Enum):
    ENTER = "enter"
    REJECT = "reject"


class RetryDecision(Enum):
    RETRY = "retry"
    ABORT = "abort"


class TurnStopDecision(Enum):
    CONTINUE = "continue"
    STOP = "stop"


# ── 可插拔事件 ──

class AgentRequestEvent(PluginEvent):
    """agent/request waterfall — 插件可在 LLM 请求前修改参数。"""
    model: str = ""
    temperature: float = 0.0
    max_tokens: int = 4096
    tools: list = field(default_factory=list)
    messages: list = field(default_factory=list)
    session_id: str = ""


class AgentRequestErrorEvent(PluginEvent):
    """agent/request-error waterfall — 插件可决定重试/放弃。"""
    error: str = ""
    attempt: int = 0
    retry: bool = False
    retry_after: float = 0.0


class AgentTurnStoppingEvent(PluginEvent):
    """agent/turn-stopping serial — 插件可决定 turn 是否继续。"""
    reason: str = StepEndReason.TURN_END.value
    continue_turn: bool = False


class StepStartEvent(PluginEvent):
    step: int = 0


class StepEndEvent(PluginEvent):
    step: int = 0
    reason: str = ""


@dataclass
class Phase:
    kind: PhaseKind = PhaseKind.IDLE
    turn: int = 0
    step: int = 0
    abort: asyncio.Event | None = None
    wake_requested: bool = False

    @property
    def is_idle(self) -> bool:
        return self.kind == PhaseKind.IDLE

    @property
    def is_running(self) -> bool:
        return self.kind == PhaseKind.RUNNING


@dataclass
class TurnContext:
    turn: int
    metadata: dict[str, Any] = field(default_factory=dict)
    max_tokens_hit: bool = False


class AgentLoop:
    """生产级 Agent 驱动 — 可插拔扩展点。

    用法:
        loop = AgentLoop(inbox, llm_provider=provider, ctx=plugin_ctx)
        loop.send(Message.user("hello"))
        await loop.kick()
    """

    MAX_RETRIES = 3
    MAX_STEPS_PER_TURN = 50

    def __init__(
        self,
        inbox: Inbox,
        llm_provider=None,
        tool_registry: ToolRegistry | None = None,
        tool_executor: ToolExecutor | None = None,
        system_prompt: str = "",
        model: str = "",
        temperature: float = 0.0,
        max_tokens: int = 4096,
        session_log: SessionLog | None = None,
        ctx: Any = None,
        session_id: str = "",
        agent_ctx: Any = None,
        on_chunk: Callable[[LLMStreamChunk], None] | None = None,
    ):
        self.inbox = inbox
        self._llm = llm_provider
        self._session_log = session_log or SessionLog()
        inbox._session_log = self._session_log
        self._tool_registry = tool_registry
        self._tool_executor = tool_executor
        self._system_prompt = system_prompt
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._ctx = ctx
        self._session_id = session_id
        self._agent_ctx = agent_ctx
        self._on_chunk = on_chunk

        self.phase = Phase(kind=PhaseKind.IDLE)
        self._current_turn: TurnContext | None = None
        self._total_usage: dict[str, int] = {"input": 0, "output": 0}
        self._pending_work = False
        self._idle_event = asyncio.Event()
        self._idle_event.set()
        self._disposed = False
        self._context_hash: str = ""

        self._restore_from_session_log()

    # ── Session-driven 恢复 ──

    def _restore_from_session_log(self) -> None:
        last_turn = self._session_log.last_turn()
        if last_turn > 0:
            self.phase = Phase(kind=PhaseKind.IDLE, turn=last_turn)

    # ── Phase 管理 ──

    def wake(self) -> None:
        if self._disposed:
            return
        if self.phase.is_idle and self.inbox.has_pending:
            self._enter_running()
        elif self.phase.is_running:
            self.phase.wake_requested = True
        elif self.phase.kind == PhaseKind.MAINTENANCE:
            self.phase.wake_requested = True

    def cancel(self) -> None:
        if self.phase.abort is not None:
            self.phase.abort.set()

    async def cancel_and_wait(self) -> None:
        self.cancel()
        await self.when_idle()

    async def when_idle(self) -> None:
        await self._idle_event.wait()

    async def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        self.cancel()
        await self.when_idle()
        self.inbox.clear()
        self._session_log.clear()

    async def run_maintenance(self, job: Callable) -> None:
        self._enter_maintenance()
        try:
            await job()
        finally:
            self._enter_idle()

    async def compact(self, turn_end: int | None = None) -> int:
        """压缩旧消息为摘要。

        将 [0, turn_end) 范围的消息调用 LLM 总结，标记原消息为 compacted，
        注入摘要消息。turn_end 为 None 时压缩到当前 turn 之前。
        返回压缩的消息数。
        """
        if self._llm is None:
            return 0
        if turn_end is None:
            turn_end = self.phase.turn
        if turn_end <= 1:
            return 0

        old_messages = self._session_log.derive_messages(0)
        if not old_messages:
            return 0

        conversation_text = "\n".join(
            f"{m.role.value}: {_message_text(m)}" for m in old_messages
        )
        summary_prompt = (
            "Summarize the following conversation into a concise summary that preserves "
            "key facts, decisions, and context:\n\n" + conversation_text
        )
        request = LLMRequest(
            messages=[Message.user(summary_prompt)],
            model=self._model,
            max_tokens=min(self._max_tokens, 2000),
            stream=False,
        )
        summary = ""
        try:
            async for chunk in self._llm.chat_stream(request):
                summary += chunk.content
        except Exception:
            _logger.exception("Compaction summarization failed")
            return 0

        compacted = self._session_log.compact(0, turn_end - 1)
        self._session_log.add_summary(turn_end - 1, summary)
        return compacted

    def _enter_running(self) -> None:
        self._idle_event.clear()
        self.phase = Phase(
            kind=PhaseKind.RUNNING,
            turn=self.phase.turn + 1,
            abort=asyncio.Event(),
        )

    def _enter_idle(self) -> None:
        wake = self.phase.wake_requested
        self.phase = Phase(kind=PhaseKind.IDLE, turn=self.phase.turn)
        if wake and self.inbox.has_pending:
            self._enter_running()
            asyncio.create_task(self.kick())
        else:
            self._idle_event.set()

    def _enter_maintenance(self) -> None:
        self.phase = Phase(kind=PhaseKind.MAINTENANCE, turn=self.phase.turn, abort=asyncio.Event())

    # ── 驱动循环 ──

    async def kick(self) -> None:
        if self._disposed:
            return
        if not self.phase.is_running:
            self._enter_running()
        try:
            while self.phase.is_running and self.inbox.has_pending:
                should_continue = await self._turn()
                if not should_continue:
                    break
        except Exception:
            _logger.exception("AgentLoop kick failed")
        finally:
            if self.phase.is_running:
                self._enter_idle()

    async def _turn(self) -> bool:
        turn = self.phase.turn
        self._current_turn = TurnContext(turn=turn)
        self._pending_work = True
        self._log(DurableEventType.TURN_START, data={"turn": turn})

        self.phase.step = 0
        try:
            while self.phase.is_running and self.phase.step < self.MAX_STEPS_PER_TURN and self._pending_work:
                if self.phase.abort and self.phase.abort.is_set():
                    break
                decision = await self._pre_step()
                if decision == PreStepDecision.REJECT:
                    break
                reason = await self._step()
                self.phase.step += 1

                # agent/turn-stopping serial — 插件可决定是否继续
                stop_decision = await self._check_turn_stopping(reason)
                if stop_decision == TurnStopDecision.STOP:
                    break
                if reason == StepEndReason.ERROR:
                    break
        finally:
            self._log(DurableEventType.TURN_END, data={"turn": turn})
            self._current_turn = None

        return self.phase.is_running and self.inbox.has_pending

    async def _check_turn_stopping(self, reason: StepEndReason) -> TurnStopDecision:
        if reason == StepEndReason.ERROR or reason == StepEndReason.INTERRUPTED:
            return TurnStopDecision.STOP

        if self._current_turn and self._current_turn.max_tokens_hit:
            return TurnStopDecision.STOP

        if self._ctx is not None:
            event = AgentTurnStoppingEvent(
                reason=reason.value,
                continue_turn=reason != StepEndReason.TURN_END,
            )
            self._ctx.waterfall(event)
            if event.continue_turn:
                return TurnStopDecision.CONTINUE
            return TurnStopDecision.STOP

        if reason == StepEndReason.TURN_END:
            return TurnStopDecision.STOP
        if self._pending_work:
            return TurnStopDecision.CONTINUE
        return TurnStopDecision.STOP

    async def _pre_step(self) -> PreStepDecision:
        claimed = self.inbox.claim()
        if claimed:
            return PreStepDecision.ENTER
        if self._pending_work:
            return PreStepDecision.ENTER
        return PreStepDecision.REJECT

    async def _step(self) -> StepEndReason:
        self._log(DurableEventType.STEP_START, step=self.phase.step)
        if self._ctx is not None:
            self._ctx.emit(StepStartEvent(step=self.phase.step))

        reason = StepEndReason.TURN_END
        try:
            for attempt in range(self.MAX_RETRIES + 1):
                try:
                    reason = await self._step_once()
                    break
                except Exception as e:
                    retry_decision = await self._on_request_error(e, attempt)
                    if retry_decision == RetryDecision.ABORT or attempt >= self.MAX_RETRIES:
                        raise
                    _logger.warning("Step retry %d/%d: %s", attempt + 1, self.MAX_RETRIES, e)
        except asyncio.CancelledError:
            reason = StepEndReason.INTERRUPTED
        except Exception:
            _logger.exception("Step failed after retries")
            reason = StepEndReason.ERROR

        self._log(DurableEventType.STEP_END, step=self.phase.step)
        if self._ctx is not None:
            self._ctx.emit(StepEndEvent(step=self.phase.step, reason=reason.value))
        return reason

    async def _step_once(self) -> StepEndReason:
        messages = self._build_messages()

        # agent/request waterfall — 插件可修改请求参数
        model = self._model
        temperature = self._temperature
        max_tokens = self._max_tokens
        tools = self._get_tool_definitions()

        if self._ctx is not None:
            request_event = AgentRequestEvent(
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools,
                messages=messages,
                session_id=self._session_id,
            )
            self._ctx.waterfall(request_event)
            model = request_event.model
            temperature = request_event.temperature
            max_tokens = request_event.max_tokens
            tools = request_event.tools
            messages = request_event.messages

        request = LLMRequest(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            stream=True,
        )

        assembler = StreamAssembler()
        async for chunk in self._llm.chat_stream(request):
            assembler.push(chunk)
            if self._on_chunk:
                self._on_chunk(chunk)
            if self.phase.abort and self.phase.abort.is_set():
                return StepEndReason.INTERRUPTED

        content, tool_calls = assembler.build()
        assistant_msg = Message.assistant_with_tool_calls(content, tool_calls)
        if assembler.finish_reason == LLMFinishReason.LENGTH:
            self._current_turn.max_tokens_hit = True
        self._log(
            DurableEventType.ASSISTANT_MESSAGE,
            data={"message": assistant_msg.model_dump(mode="json"), "tool_calls": len(tool_calls), "text": assembler.text[:200]},
        )

        if not tool_calls:
            self._pending_work = False
            return StepEndReason.TURN_END

        self._pending_work = True
        results = await self._execute_tool_calls(tool_calls)
        if results:
            for result in results:
                tool_msg = _tool_result_message(result)
                self._log(
                    DurableEventType.TOOL_RESULT,
                    data={"message": tool_msg.model_dump(mode="json"), "name": result.name, "is_error": result.is_error},
                )

        return StepEndReason.NEXT_STEP

    async def _execute_tool_calls(self, tool_calls: list[ToolCallBlock]) -> list[ToolResult]:
        if self._tool_executor:
            return await self._tool_executor.execute_smart(tool_calls)
        if not self._tool_registry:
            return []
        executor = ToolExecutor(self._tool_registry)
        return await executor.execute_smart(tool_calls)

    def _build_messages(self) -> list[Message]:
        result: list[Message] = []
        if self._system_prompt:
            result.append(Message.system(self._system_prompt))
        result.extend(self._session_log.derive_messages())
        return result

    def _get_tool_definitions(self) -> list[ToolDefinition]:
        if not self._tool_registry:
            return []
        return self._tool_registry.get_definitions()

    async def _on_request_error(self, error: Exception, attempt: int) -> RetryDecision:
        # agent/request-error waterfall — 插件可覆盖重试决策
        if self._ctx is not None:
            error_event = AgentRequestErrorEvent(
                error=str(error),
                attempt=attempt,
                retry=False,
                retry_after=0.0,
            )
            self._ctx.waterfall(error_event)
            if error_event.retry:
                if error_event.retry_after > 0:
                    await asyncio.sleep(error_event.retry_after)
                else:
                    await asyncio.sleep(min(2 ** attempt, 60))
                return RetryDecision.RETRY
            return RetryDecision.ABORT

        if hasattr(error, "status_code"):
            status = getattr(error, "status_code", 0)
            if status in (429, 500, 502, 503, 504):
                delay = min(2 ** attempt, 60)
                await asyncio.sleep(delay)
                return RetryDecision.RETRY
        return RetryDecision.ABORT

    def _log(self, event_type: str, step: int | None = None, data: dict[str, Any] | None = None) -> None:
        self._session_log.append(
            event_type,
            turn=self.phase.turn,
            step=step if step is not None else self.phase.step,
            data=data or {},
        )

    # ── 输入路由 ──

    def send(self, message: Message) -> None:
        if self._disposed:
            return
        self._log(DurableEventType.USER_MESSAGE, data={"message": message.model_dump(mode="json")})
        self.inbox.append("next-turn", message)
        self.wake()

    def inject(self, message: Message) -> None:
        if self._disposed:
            return
        self._log(DurableEventType.USER_MESSAGE, data={"message": message.model_dump(mode="json")})
        self.inbox.append("next-step", message)

    def inject_context(self, context: str) -> bool:
        """差分注入上下文 — 仅在内容变化时注入，避免重复。

        对标 deepseek-harness RuntimeContextProjection。
        返回 True 表示实际注入了新上下文。
        """
        import hashlib
        ctx_hash = hashlib.sha256(context.encode()).hexdigest()
        if ctx_hash == self._context_hash:
            return False
        self._context_hash = ctx_hash
        self.inject(Message.system(context))
        return True


def _tool_result_message(result: ToolResult) -> Message:
    content = result.output
    return Message(
        role=MessageRole.TOOL,
        content=[ToolResultBlock(tool_call_id=result.call_id, content=content, is_error=result.is_error)],
    )


def _message_text(msg: Message) -> str:
    parts = []
    for block in msg.content:
        if isinstance(block, TextBlock):
            parts.append(block.text)
        elif isinstance(block, ToolCallBlock):
            parts.append(f"[tool_call:{block.name}]")
        elif isinstance(block, ToolResultBlock):
            parts.append(f"[tool_result:{block.content[:200]}]")
    return " ".join(parts)


class AgentLoopFactory:
    """Agent 工厂 — 创建/追踪/拆卸级联。

    对标 ReactLoopAgent 的 FactoryOwnership：
    - 工厂追踪所有创建的 Agent
    - dispose_all() 级联拆卸所有 Agent
    - 拆卸记忆化：多次调用等同一静止
    """

    def __init__(self):
        self._agents: set[AgentLoop] = set()

    def create(
        self,
        inbox: Inbox,
        llm_provider=None,
        tool_registry: ToolRegistry | None = None,
        tool_executor: ToolExecutor | None = None,
        system_prompt: str = "",
        model: str = "",
        temperature: float = 0.0,
        max_tokens: int = 4096,
        session_log: SessionLog | None = None,
        ctx: Any = None,
        session_id: str = "",
    ) -> AgentLoop:
        agent = AgentLoop(
            inbox=inbox,
            llm_provider=llm_provider,
            tool_registry=tool_registry,
            tool_executor=tool_executor,
            system_prompt=system_prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            session_log=session_log,
            ctx=ctx,
            session_id=session_id,
        )
        self._agents.add(agent)
        return agent

    async def dispose_all(self) -> None:
        agents = list(self._agents)
        await asyncio.gather(*(a.dispose() for a in agents))
        self._agents.clear()

    @property
    def agent_count(self) -> int:
        return len(self._agents)