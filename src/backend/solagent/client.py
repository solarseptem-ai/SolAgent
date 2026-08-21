"""SolAgent SDK 客户端 — 统一外部接口封装。

将 AgentBuilder + SessionLog + EventBus 收敛为简洁的 SDK 调用接口，
提供 run() / run_stream() / session() 三种模式。

典型用法:
    async with SolAgentClient(model="gpt-4o") as client:
        result = await client.run("Hello, world!")

    async with SolAgentClient(model="gpt-4o") as client:
        session = await client.session()
        await session.run("我是小明")
        await session.run("我叫什么？")
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import AsyncIterator

from solagent.agents.builder import AgentBuilder
from solagent.events.bus import EventBus
from solagent.events.types import AgentEvent
from solagent.llms.factory import LLMFactory
from solagent.schema.agent import AgentConfig, AgentMode
from solagent.schema.messages import Message

_logger = logging.getLogger(__name__)


@dataclass
class RunResult:
    """Agent 单次运行结果。"""

    content: str
    finish_reason: str = "stop"
    token_usage: dict = field(default_factory=dict)
    tool_calls: list = field(default_factory=list)
    duration_ms: int = 0
    steps: list = field(default_factory=list)
    error: str = ""


@dataclass
class StreamChunk:
    """Agent 流式输出块。"""

    type: str = "content"
    iteration: int = 0
    content: str = ""
    thinking: str = ""
    tool_calls: list = field(default_factory=list)
    tool_results: list = field(default_factory=list)
    is_final: bool = False


class SolAgentSession:
    """持久会话句柄，维护消息历史支持多轮对话。"""

    def __init__(self, client: SolAgentClient, session_id: str | None = None) -> None:
        self._client = client
        self.id = session_id or str(uuid.uuid4())
        self._builder: AgentBuilder = client._create_builder()
        self._event_bus = EventBus()
        self._messages: list[Message] = []

    async def run(self, input: str | list[dict] | list[Message]) -> RunResult:
        """发送 prompt 并等待 Agent 完成。

        Args:
            input: 用户输入，支持纯文本字符串、dict 列表或 Message 列表。

        Returns:
            RunResult 包含最终回复、token 用量、工具调用、耗时等。
        """
        self._messages.extend(self._normalize_input(input))
        result = await self._client._run_internal(self._builder, list(self._messages), self._event_bus)
        if result.content and not result.error:
            self._messages.append(Message.assistant(result.content))
        return result

    async def run_stream(self, input: str | list[dict] | list[Message]) -> AsyncIterator[StreamChunk]:
        """流式发送 prompt，逐步产出 Agent 中间步骤。

        Args:
            input: 用户输入，同 run()。

        Yields:
            StreamChunk 包含每一步的文本、工具调用、工具结果。
        """
        self._messages.extend(self._normalize_input(input))
        async for chunk in self._client._stream_internal(self._builder, list(self._messages), self._event_bus):
            yield chunk

    def on_event(self, listener) -> None:
        """注册事件监听器，回调签名: async def listener(event: AgentEvent)。"""
        self._event_bus.subscribe("*", listener)

    @property
    def messages(self) -> list[Message]:
        """返回当前会话的全部消息历史。"""
        return list(self._messages)

    def clear(self) -> None:
        """清空会话的消息历史，保留会话 ID 和事件总线。"""
        self._messages.clear()

    def _normalize_input(self, input: str | list[dict] | list[Message]) -> list[Message]:
        if isinstance(input, str):
            return [Message.user(input)]
        if isinstance(input, list) and input and isinstance(input[0], Message):
            return input  # type: ignore[return-value]
        return [Message.user(m["content"]) for m in input]  # type: ignore[index]


class SolAgentClient:
    """SolAgent 统一 SDK 客户端。

    封装 LLMFactory 自动发现、AgentBuilder 构建流程和 EventBus 事件订阅，
    提供一体化的 Agent 调用接口。支持 async with 上下文管理器自动清理。

    参数:
        model: 模型名称，如 "gpt-4o"、"deepseek-v3"。为空时自动选择第一个可用模型。
        provider: 提供商名称，如 "openai"、"deepseek"。为空时自动匹配模型。
        mode: Agent 执行模式，默认 "chat"。可选 "react"、"plan_execute" 等。
        system_prompt: 系统提示词，默认 "You are a helpful AI assistant."。
        max_iterations: 最大迭代次数，默认 10。
        max_tokens: 最大输出 token 数，默认 4096。
        temperature: 采样温度，默认 0.7。
        tools: 启用的工具名称列表，空列表启用全部内置工具。
        skills: 启用的技能名称列表。
    """

    def __init__(
        self,
        model: str = "",
        provider: str = "",
        mode: str = "chat",
        system_prompt: str = "",
        max_iterations: int = 10,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: list[str] | None = None,
        skills: list[str] | None = None,
    ) -> None:
        self._model = model
        self._provider_name = provider
        self._mode = AgentMode(mode)
        self._system_prompt = system_prompt or "You are a helpful AI assistant."
        self._max_iterations = max_iterations
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._tool_names = tools or []
        self._skill_names = skills or []

        self._factory = LLMFactory()
        self._provider = None
        self._config: AgentConfig | None = None
        self._sessions: dict[str, SolAgentSession] = {}
        self._closed = False

    async def _ensure_initialized(self) -> None:
        if self._provider is not None:
            return
        if self._model:
            self._provider = self._factory.create(self._model)
        else:
            profiles = self._factory.list_providers()
            if not profiles:
                raise RuntimeError("No LLM providers found. Set API key env vars (OPENAI_API_KEY, etc.).")
            self._provider = self._factory.create(profiles[0].default_model)
            self._model = profiles[0].default_model

        self._config = AgentConfig(
            name="solagent-client",
            system_prompt=self._system_prompt,
            model=self._model,
            mode=self._mode,
            max_iterations=self._max_iterations,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            tools=self._tool_names,
            skills=self._skill_names,
        )

    def _create_builder(self) -> AgentBuilder:
        return AgentBuilder().with_config(self._config).with_provider(self._provider)

    async def run(self, input: str | list[dict] | list[Message]) -> RunResult:
        """单次执行 Agent，无状态。

        Args:
            input: 用户输入，支持纯文本字符串、dict 列表或 Message 列表。

        Returns:
            RunResult 包含最终回复、token 用量、工具调用、耗时等。
        """
        await self._ensure_initialized()
        messages = self._normalize_input(input)
        builder = self._create_builder()
        return await self._run_internal(builder, messages, EventBus())

    async def run_stream(self, input: str | list[dict] | list[Message]) -> AsyncIterator[StreamChunk]:
        """单次流式执行 Agent。

        Args:
            input: 用户输入，同 run()。

        Yields:
            StreamChunk 包含每一步的文本、工具调用、工具结果。
        """
        await self._ensure_initialized()
        messages = self._normalize_input(input)
        builder = self._create_builder()
        async for chunk in self._stream_internal(builder, messages, EventBus()):
            yield chunk

    async def session(self, session_id: str | None = None) -> SolAgentSession:
        """创建持久会话句柄，用于多轮对话。

        Args:
            session_id: 会话 ID，None 则自动生成 UUID。

        Returns:
            SolAgentSession 实例，支持 run() / run_stream() / on_event()。
        """
        await self._ensure_initialized()
        session = SolAgentSession(self, session_id)
        self._sessions[session.id] = session
        return session

    def on_event(self, listener) -> None:
        """注册全局事件监听器。"""
        _logger.warning("on_event must be called on a session, not the client. Use client.session().on_event()")

    async def close(self) -> None:
        """关闭客户端，清理所有会话资源。"""
        if self._closed:
            return
        self._closed = True
        self._sessions.clear()

    async def __aenter__(self) -> "SolAgentClient":
        await self._ensure_initialized()
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()

    async def _run_internal(self, builder: AgentBuilder, messages: list[Message], event_bus: EventBus) -> RunResult:
        try:
            result = await builder.run(messages)
            return RunResult(
                content=result.content,
                finish_reason=result.finish_reason,
                token_usage=result.token_usage.model_dump() if result.token_usage else {},
                tool_calls=[tc.model_dump() for tc in result.tool_results] if result.tool_results else [],
                duration_ms=result.duration_ms,
                steps=result.steps,
            )
        except Exception as e:
            _logger.exception("Agent run error")
            return RunResult(content=str(e), error=str(e), finish_reason="error")

    async def _stream_internal(
        self, builder: AgentBuilder, messages: list[Message], event_bus: EventBus
    ) -> AsyncIterator[StreamChunk]:
        try:
            async for step in builder.run_stream(messages):
                yield StreamChunk(
                    type="content",
                    iteration=step.iteration,
                    content=step.content,
                    thinking=step.thinking,
                    tool_calls=step.tool_calls,
                    tool_results=step.tool_results,
                    is_final=step.is_final,
                )
        except Exception as e:
            _logger.exception("Agent stream error")
            yield StreamChunk(type="error", content=str(e), is_final=True)

    def _normalize_input(self, input: str | list[dict] | list[Message]) -> list[Message]:
        if isinstance(input, str):
            return [Message.user(input)]
        if isinstance(input, list) and input and isinstance(input[0], Message):
            return input  # type: ignore[return-value]
        return [Message.user(m["content"]) for m in input]  # type: ignore[index]

    @property
    def provider(self):
        """返回当前使用的 LLM provider。"""
        return self._provider

    @property
    def model(self) -> str:
        """返回当前使用的模型名称。"""
        return self._model