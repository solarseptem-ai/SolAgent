"""Agent 插件模块。

定义 Agent 生命周期事件（请求、响应、步骤前后）以及两类 Agent 插件：
- AgentPlugin：通用基类，订阅 Agent 循环事件，自动记录对话到记忆。
- ReActAgentPlugin：ReAct 推理-行动循环实现，支持工具调用与多轮迭代。
"""
from solagent.cordis.events import AfterAgentLoopEvent, AgentLifecycleEvent, BeforeAgentLoopEvent  # noqa: F401 — re-export
from solagent.plugins import Plugin, PluginEvent


class AgentRequestEvent(PluginEvent):
    """Agent 请求事件，携带用户消息与生成参数。"""
    messages: list = []
    model: str = ""
    temperature: float = 0.0
    max_tokens: int = 4096


class AgentResponseEvent(PluginEvent):
    """Agent 响应事件，携带模型生成的内容与工具调用。"""
    content: str = ""
    tool_calls: list = []


class AgentPreStepEvent(PluginEvent):
    """Agent 单步执行前事件，可被 middleware 拦截修改消息。"""
    messages: list = []


class AgentPostStepEvent(PluginEvent):
    """Agent 单步执行后事件，携带模型输出与工具执行结果。"""
    content: str = ""
    tool_results: list = []


class AgentPlugin(Plugin):
    """通用 Agent 插件基类。

    依赖注入大量核心服务（工具注册表、事件总线、守卫、记忆等），
    并在 Agent 循环的关键节点注册事件处理器。
    """
    name = "agent"
    inject = {
        "tool_registry": None,
        "event_bus": None,
        "event_scope": None,
        "guard": None,
        "permission": None,
        "retry_policy": None,
        "circuit_breaker": None,
        "memory": None,
        "hooks": None,
        "middleware": None,
    }

    async def start(self):
        """注册 Agent 生命周期事件处理器。"""
        self.ctx.on(BeforeAgentLoopEvent, self._on_before_loop, mode="waterfall")
        self.ctx.on(AfterAgentLoopEvent, self._on_after_loop, mode="emit")
        self.ctx.on(AgentPreStepEvent, self._on_pre_step, mode="waterfall")
        self.ctx.on(AgentPostStepEvent, self._on_post_step, mode="emit")

    def _on_before_loop(self, event: BeforeAgentLoopEvent, nxt):
        """循环开始前注入 LLM provider 到 middleware。"""
        middleware = self.ctx.middleware
        if middleware:
            try:
                provider = self.ctx.root._services.get("_provider")
            except AttributeError:
                provider = None
            if provider:
                middleware.inject_provider(provider)
        return nxt()

    async def _on_after_loop(self, event: AfterAgentLoopEvent):
        """循环结束后将结果写入记忆。"""
        memory = self.ctx.memory
        if memory and event.result:
            from solagent.schema.memory import MemoryCategory, MemoryRecord
            import uuid
            content = getattr(event.result, "content", str(event.result))
            record = MemoryRecord(
                id=str(uuid.uuid4()),
                content=content,
                category=MemoryCategory.CONVERSATION,
            )
            await memory.add(record)

    async def _on_pre_step(self, event: AgentPreStepEvent, nxt):
        """单步执行前：若 guard 缺少 check_by_name 则提供默认放行实现。"""
        import asyncio
        guard = self.ctx.guard
        if guard:
            guard.check_by_name = getattr(guard, 'check_by_name', lambda *a: type('', (), {'allowed': True})())
        return nxt()

    async def _on_post_step(self, event: AgentPostStepEvent):
        """单步执行后将模型输出写入记忆。"""
        memory = self.ctx.memory
        if memory and event.content:
            from solagent.schema.memory import MemoryCategory, MemoryRecord
            import uuid
            record = MemoryRecord(
                id=str(uuid.uuid4()),
                content=event.content,
                category=MemoryCategory.CONVERSATION,
            )
            await memory.add(record)


class ReActAgentPlugin(AgentPlugin):
    """ReAct（Reasoning + Acting）Agent 插件。

    实现经典的思考-行动-观察循环：
    1. 向 LLM 发送当前消息历史与可用工具定义。
    2. 若 LLM 返回 tool_calls，则执行第一个工具并将结果追加到消息历史。
    3. 若 LLM 返回纯文本，则作为最终答案返回。
    最多迭代 _max_iterations 轮（默认 10）。
    """
    name = "react_agent"
    inject = {
        "tool_registry": None,
        "event_bus": None,
        "event_scope": None,
        "guard": None,
        "permission": None,
        "retry_policy": None,
        "circuit_breaker": None,
        "memory": None,
        "hooks": None,
        "middleware": None,
        "llm": None,
    }

    async def start(self):
        """初始化父类事件处理器，并设置迭代上限与消息缓存。"""
        await super().start()
        self._max_iterations = 10
        self._messages: list = []

    async def run(self, task: str, messages: list | None = None) -> str:
        """执行 ReAct 循环。

        Args:
            task: 用户输入的任务文本（当 messages 为 None 时使用）。
            messages: 可选的初始消息列表，直接覆盖 task。

        Returns:
            最终模型输出的文本；若达到最大迭代次数则返回提示信息。
        """
        from solagent.schema.messages import Message, MessageRole, TextBlock
        from solagent.schema.llm import LLMRequest

        # 构建初始消息列表
        if messages:
            self._messages = messages
        else:
            self._messages = [Message(role=MessageRole.USER, content=[TextBlock(type="text", text=task)])]

        provider = self.ctx.llm
        tools = self.ctx.tool_registry.get_definitions()

        for i in range(self._max_iterations):
            self.ctx.emit(AgentPreStepEvent(messages=self._messages))

            request = LLMRequest(
                messages=self._messages,
                model=getattr(provider, 'default_model', ''),
                tools=tools,
            )
            response = await provider.chat(request)

            if response.tool_calls:
                # 模型请求调用工具：记录 assistant 消息并执行工具
                content = response.content or ""
                tc = response.tool_calls[0]
                self._messages.append(Message(
                    role=MessageRole.ASSISTANT,
                    content=[TextBlock(type="text", text=content)],
                    tool_calls=[tc],
                ))
                from solagent.agents.tools.executor import ToolExecutor
                executor = ToolExecutor(self.ctx.tool_registry, guard=self.ctx.guard)
                results = await executor._execute_one(tc)
                if results:
                    self._messages.append(Message(
                        role=MessageRole.TOOL,
                        content=[TextBlock(type="text", text=results[0].output)],
                        tool_call_id=tc.id,
                    ))
                self.ctx.emit(AgentPostStepEvent(content=content, tool_results=[r.output for r in results] if results else []))
            else:
                # 模型直接返回文本，作为最终答案
                self.ctx.emit(AgentPostStepEvent(content=response.content))
                return response.content

        return "Max iterations reached"