"""Agent 构建器模块。

提供链式 API 的 AgentBuilder，用于按需组装 Agent 运行所需的全部依赖：
配置、LLM 提供者、工具注册表、钩子、中间件、记忆、技能、MCP、插件、权限、
人机协同、守卫、工具注入器等。

构建完成后调用 run() 或 run_stream() 即可执行 Agent，适用于需要灵活定制
Agent 能力的场景。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from solagent.agents.base import AgentContext, AgentStep
from solagent.agents.hooks import AgentHooks
from solagent.agents.memory.manager import MemoryManager
from solagent.agents.middleware.chain import MiddlewareChain
from solagent.agents.modes.registry import ModeRegistry
from solagent.agents.session.surface import SurfaceManager
from solagent.agents.tools.extensions import ExtensionRunner
from solagent.agents.tools.hooks import BeforeResult, ToolHooks
from solagent.agents.tools.injector import ToolDisclosureConfig, ToolInjector
from solagent.agents.tools.registry import ToolRegistry
from solagent.core.session_log import SessionLog
from solagent.schema.agent import AgentConfig, AgentResult
from solagent.schema.messages import MessageRole

if TYPE_CHECKING:
    from solagent.llms.credentials import CredentialResolver

_logger = logging.getLogger(__name__)


def _make_permission_hook(permission):
    async def perm_hook(tool_name, params, call):
        from solagent.agents.tools.permission import PermissionDecision
        perm_result = permission.check(tool_name, call.arguments, is_read_only=False)
        if perm_result.decision == PermissionDecision.DENY:
            return BeforeResult(allowed=False, reason=perm_result.reason)
        return BeforeResult(allowed=True)
    return perm_hook


def _make_hitl_hook(hitl):
    async def hitl_hook(tool_name, params, call):
        from solagent.agents.hitl import HITLDecision
        from solagent.agents.tools.permission import PermissionDecision
        try:
            hitl_response = await asyncio.wait_for(
                hitl.request_approval(tool_name, call.arguments, f"Approve execution of '{tool_name}'?", "normal"),
                timeout=60.0,
            )
            if hitl_response.decision == HITLDecision.REJECTED:
                return BeforeResult(allowed=False, reason=hitl_response.reason)
        except TimeoutError:
            return BeforeResult(allowed=False, reason="HITL approval timed out")
        return BeforeResult(allowed=True)
    return hitl_hook


def _make_guard_hook(guard):
    async def guard_hook(tool_name, params, call):
        guard_decision = guard.check_by_name(tool_name, call)
        if not guard_decision.allowed:
            return BeforeResult(allowed=False, reason=guard_decision.reason)
        return BeforeResult(allowed=True)
    return guard_hook



class AgentBuilder:
    """Agent 链式构建器。

    通过 with_* 方法逐步注入依赖，最终调用 run() 或 run_stream() 执行 Agent。
    自动处理工具发现、技能过滤、守卫链组装、MCP 连接、插件生命周期管理等复杂逻辑。

    典型用法:
        result = await AgentBuilder()
            .with_config(config)
            .with_provider(provider)
            .with_tools(tools)
            .run(messages)
    """

    def __init__(self):
        self._config: AgentConfig | None = None
        self._provider = None
        self._tools = ToolRegistry()
        self._hooks = AgentHooks()
        self._middleware = MiddlewareChain()
        self._memory: MemoryManager | None = None
        self._skill_manager = None
        self._mcp_manager = None
        self._mcp_initialized = False
        self._agent = None
        self._permission = None
        self._hitl = None
        self._guard = None
        self._extensions = ()
        self._credential_resolver = None
        self._tool_injector = None
        self._plugin_manager = None
        self._cordis_ctx = None
        self._plugin_started = False
        self._metadata: dict = {}

    def with_config(self, config: AgentConfig) -> "AgentBuilder":
        """设置 Agent 配置。"""
        self._config = config
        return self

    def with_provider(self, provider) -> "AgentBuilder":
        """设置 LLM 提供者。"""
        self._provider = provider
        return self

    def with_tools(self, tools: ToolRegistry) -> "AgentBuilder":
        """设置工具注册表。"""
        self._tools = tools
        return self

    def with_hooks(self, hooks: AgentHooks) -> "AgentBuilder":
        """设置 Agent 生命周期钩子。"""
        self._hooks = hooks
        return self

    def with_middleware(self, middleware: MiddlewareChain) -> "AgentBuilder":
        """设置中间件链。"""
        self._middleware = middleware
        return self

    def with_memory(self, memory: MemoryManager) -> "AgentBuilder":
        """设置记忆管理器。"""
        self._memory = memory
        return self

    def with_skills(self, skill_manager) -> "AgentBuilder":
        """设置技能管理器，用于加载和过滤 Agent 可用技能。"""
        self._skill_manager = skill_manager
        return self

    def with_mcp(self, mcp_manager) -> "AgentBuilder":
        """设置 MCP（Model Context Protocol）管理器，用于连接外部工具服务。"""
        self._mcp_manager = mcp_manager
        return self

    def with_extensions(self, *extensions) -> "AgentBuilder":
        """设置需要加载的工具扩展。"""
        self._extensions = extensions
        return self

    def use_plugin_manager(self) -> "AgentBuilder":
        from solagent.cordis import Context, PluginManagerService
        from solagent.plugins.middleware import (
            CircuitBreakerPlugin,
            EventBusPlugin,
            GuardPlugin,
            HookPlugin,
            MemoryPlugin,
            MiddlewarePlugin,
            PermissionPlugin,
            RetryPlugin,
            ToolRegistryPlugin,
        )
        from solagent.plugins.agent import AgentPlugin
        from solagent.plugins.strategies import (
            CheckpointPlugin,
            LearningStrategyPlugin,
            PromptRegistryPlugin,
            ResultStoragePlugin,
            SandboxProviderPlugin,
            ToolDiscoveryPlugin,
        )

        self._cordis_ctx = Context()
        self._plugin_manager = PluginManagerService(self._cordis_ctx)
        self._plugin_manager.register(EventBusPlugin)
        self._plugin_manager.register(ToolRegistryPlugin)
        self._plugin_manager.register(GuardPlugin)
        self._plugin_manager.register(PermissionPlugin)
        self._plugin_manager.register(RetryPlugin)
        self._plugin_manager.register(CircuitBreakerPlugin)
        self._plugin_manager.register(MemoryPlugin)
        self._plugin_manager.register(HookPlugin)
        self._plugin_manager.register(MiddlewarePlugin)
        self._plugin_manager.register(AgentPlugin)
        self._plugin_manager.register(ResultStoragePlugin)
        self._plugin_manager.register(SandboxProviderPlugin)
        self._plugin_manager.register(ToolDiscoveryPlugin)
        self._plugin_manager.register(LearningStrategyPlugin)
        self._plugin_manager.register(CheckpointPlugin)
        self._plugin_manager.register(PromptRegistryPlugin)
        self._plugin_started = False
        return self

    def with_plugin(self, plugin_cls: type, config: dict | None = None) -> "AgentBuilder":
        """向插件管理器注册单个插件类及可选配置。"""
        from solagent.cordis import Context, PluginManagerService
        if self._cordis_ctx is None:
            self._cordis_ctx = Context()
            self._plugin_manager = PluginManagerService(self._cordis_ctx)
        self._plugin_manager.register(plugin_cls, config)
        return self

    def _build_context(self, messages: list) -> AgentContext:
        """根据当前构建器状态组装 AgentContext。

        包括：工具自动发现与过滤、技能加载与过滤、5 层守卫链组装、
        SessionLog 与 Surface 初始化、工具绑定（SubagentTool、SkillViewTool）、
        本地适配器端口创建等。

        参数:
            messages: 初始消息列表。

        返回:
            完整的 AgentContext 实例。

        异常:
            ValueError: 未设置 config 或 provider。
        """
        if not self._config or not self._provider:
            raise ValueError("Config and provider must be set")

        # 若未显式提供工具，自动发现内置工具
        if len(self._tools) == 0:
            self._tools.auto_discover("solagent.agents.tools.builtins")

        # 按配置中的 tools 列表过滤，仅保留指定工具
        if self._config.tools and len(self._config.tools) > 0:
            config_tool_names = set(self._config.tools)
            for name in self._tools.list():
                if name not in config_tool_names:
                    self._tools.unregister(name)

        # 加载技能并基于技能策略进一步过滤工具
        active_skills = []
        filtered_tools = self._tools
        if self._skill_manager and self._config.skills:
            self._skill_manager.load(self._config.skills)
            active_skills = self._skill_manager.get_active()
            skill_names = [s.name for s in active_skills]
            filtered_tools = self._tools.filter(active_skills=skill_names)
            policy = self._skill_manager.get_tool_policy()
            for name in list(filtered_tools.list()):
                if not policy.is_allowed(name):
                    filtered_tools.unregister(name)

        # 组装 5 层安全守卫链（Bash 扫描、文件安全、循环检测、速率限制）
        from solagent.agents.guard import BashCommandScanner, FileSafetyGuard, LoopDetector, RateGuard, CompositeGuard

        if self._guard is None:
            self._guard = CompositeGuard([
                BashCommandScanner(),
                FileSafetyGuard(),
                LoopDetector(),
                RateGuard(),
            ])

        ctx = AgentContext(config=self._config, provider=self._provider, tools=filtered_tools,
                           hooks=self._hooks, middleware=self._middleware, memory=self._memory,
                           messages=list(messages),
                           metadata=dict(self._metadata),
                           active_skills=active_skills,
                           permission=self._permission, hitl=self._hitl, guard=self._guard,
                           plugin_ctx=self._cordis_ctx if self._cordis_ctx else None)

        surface = SurfaceManager()
        session_log = SessionLog()
        session_log.attach_surface(surface)
        ctx.session_log = session_log
        ctx.surface = surface

        for msg in messages:
            if msg.role == MessageRole.USER:
                event_type = "user/message"
            elif msg.role == MessageRole.ASSISTANT:
                event_type = "assistant/message"
            elif msg.role == MessageRole.TOOL:
                event_type = "tool/result"
            else:
                event_type = "system/inject"
            session_log.append(event_type, data={"message": msg.model_dump(mode="json")})

        if self._tool_injector is not None:
            ctx.tool_injector = ToolInjector(filtered_tools, self._tool_injector)

        if self._memory is not None:
            self._memory._event_bus = ctx.event_bus

        from solagent.agents.tools.builtins.subagent import SubagentTool
        for tool_name in ctx.tools.list():
            tool = ctx.tools.get(tool_name)
            if isinstance(tool, SubagentTool):
                tool.bind_parent_ctx(lambda: ctx)

        if self._skill_manager:
            from solagent.agents.tools.builtins.skill_view import SkillViewTool
            for tool_name in ctx.tools.list():
                tool = ctx.tools.get(tool_name)
                if isinstance(tool, SkillViewTool):
                    tool.bind_skill_manager(self._skill_manager)

        from solagent.adapters.local.agent import LocalAgentAdapter
        from solagent.adapters.local.event import LocalEventAdapter
        from solagent.adapters.local.llm import LocalLLMAdapter
        from solagent.adapters.local.tool import LocalToolAdapter

        ctx._agent_port = LocalAgentAdapter(self._agent) if self._agent else None
        ctx._tool_port = LocalToolAdapter(filtered_tools)
        ctx._event_port = LocalEventAdapter(ctx.event_bus)
        ctx._llm_port = LocalLLMAdapter(self._provider)

        return ctx

    async def run(self, messages: list) -> AgentResult:
        """非流式执行 Agent，返回最终结果。

        首次执行时会启动插件管理器（若已配置）并连接 MCP 服务。
        """
        if self._plugin_manager is not None and not self._plugin_started:
            self._provide_services_to_cordis()
            await self._plugin_manager.start_all()
            if self._provider:
                self._cordis_ctx.provide("llm", self._provider)
            self._plugin_started = True
        ctx = self._build_context(messages)
        if self._mcp_manager:
            if self._mcp_initialized:
                await self._mcp_manager.refresh(ctx.tools)
            else:
                await self._mcp_manager.connect_all()
                await self._mcp_manager.discover()
                self._mcp_manager.register_to_registry(ctx.tools)
                self._mcp_initialized = True
        if self._extensions:
            runner = ExtensionRunner(ctx.tools)
            await runner.load_all(*self._extensions)
        self._agent = ModeRegistry.create(self._config.mode, ctx)
        return await self._agent.run()

    def _provide_services_to_cordis(self) -> None:
        """将构建器中的核心服务注册到 Cordis 上下文，供插件系统使用。"""
        if self._cordis_ctx is None:
            return
        self._cordis_ctx.provide("tool_registry", self._tools)
        self._cordis_ctx.provide("hooks", self._hooks)
        self._cordis_ctx.provide("middleware", self._middleware)
        if self._memory is not None:
            self._cordis_ctx.provide("memory", self._memory)
        if self._permission is not None:
            self._cordis_ctx.provide("permission", self._permission)
        if self._hitl is not None:
            self._cordis_ctx.provide("hitl", self._hitl)

    async def run_stream(self, messages: list) -> AsyncIterator[AgentStep]:
        """流式执行 Agent，逐步产出 AgentStep。"""
        if self._plugin_manager is not None and not self._plugin_started:
            self._provide_services_to_cordis()
            await self._plugin_manager.start_all()
            if self._provider:
                self._cordis_ctx.provide("llm", self._provider)
            self._plugin_started = True
        ctx = self._build_context(messages)
        if self._mcp_manager:
            if self._mcp_initialized:
                await self._mcp_manager.refresh(ctx.tools)
            else:
                await self._mcp_manager.connect_all()
                await self._mcp_manager.discover()
                self._mcp_manager.register_to_registry(ctx.tools)
                self._mcp_initialized = True
        if self._extensions:
            runner = ExtensionRunner(ctx.tools)
            await runner.load_all(*self._extensions)
        self._agent = ModeRegistry.create(self._config.mode, ctx)
        async for step in self._agent.run_stream():
            yield step

    def with_permission(self, permission) -> "AgentBuilder":
        """设置权限引擎，用于控制工具调用的读写权限。"""
        self._permission = permission
        return self

    def with_hitl(self, hitl) -> "AgentBuilder":
        """设置人机协同管理器，用于关键操作的人工审批。"""
        self._hitl = hitl
        return self

    def with_guard(self, guard) -> "AgentBuilder":
        """设置自定义安全守卫，覆盖默认的 5 层守卫链。"""
        self._guard = guard
        return self

    def with_tool_injector(self, config: ToolDisclosureConfig | None = None) -> "AgentBuilder":
        """设置工具注入器配置，实现工具的渐进式披露策略。"""
        self._tool_injector = ToolDisclosureConfig() if config is None else config
        return self

    def with_credentials(self, resolver: "CredentialResolver") -> "AgentBuilder":
        """设置凭据解析器，用于动态获取 API 密钥等敏感信息。"""
        self._credential_resolver = resolver
        return self

    @property
    def messages(self) -> list:
        """获取当前 Agent 的消息列表（若已构建并执行）。"""
        if self._agent is not None:
            return self._agent.context.messages
        return []