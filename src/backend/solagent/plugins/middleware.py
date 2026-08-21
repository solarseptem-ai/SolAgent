"""基础设施插件聚合模块。

为系统提供一组开箱即用的基础服务插件，每个插件负责初始化和注入一个核心能力：
守卫、权限、重试、熔断器、记忆、钩子、中间件链、工具注册表、事件总线。
所有插件均遵循"已存在则跳过"的懒加载策略，避免重复初始化。
"""
from solagent.plugins import Plugin


class GuardPlugin(Plugin):
    """安全守卫插件，组合多种扫描器提供统一的安全检查入口。"""
    name = "guard"
    inject = {}

    async def start(self):
        """若上下文中尚无 guard 实例，则组装默认的 CompositeGuard 并注入。"""
        if self.ctx.root._services.get("guard"):
            return
        from solagent.agents.guard import BashCommandScanner, CompositeGuard, FileSafetyGuard, LoopDetector, RateGuard

        guard = CompositeGuard([
            BashCommandScanner(),
            FileSafetyGuard(),
            LoopDetector(),
            RateGuard(),
        ])
        self.ctx.provide("guard", guard)


class PermissionPlugin(Plugin):
    """权限引擎插件，提供工具级权限控制。"""
    name = "permission"
    inject = {}

    async def start(self):
        """注入默认的 PermissionEngine。"""
        if self.ctx.root._services.get("permission"):
            return
        from solagent.agents.tools.permission import PermissionEngine

        permission = PermissionEngine()
        self.ctx.provide("permission", permission)


class RetryPlugin(Plugin):
    """重试策略插件，为 LLM 调用提供指数退避重试机制。"""
    name = "retry"
    inject = {}

    async def start(self):
        """注入默认 RetryPolicy（最多 2 次，基础延迟 1s，最大 60s，带抖动）。"""
        if self.ctx.root._services.get("retry_policy"):
            return
        from solagent.llms.retry import RetryPolicy

        policy = RetryPolicy(max_retries=2, base_delay=1.0, max_delay=60.0, jitter=True)
        self.ctx.provide("retry_policy", policy)


class CircuitBreakerPlugin(Plugin):
    """熔断器插件，防止下游服务故障级联扩散。"""
    name = "circuit_breaker"
    inject = {}

    async def start(self):
        """注入默认 CircuitBreaker 实例。"""
        if self.ctx.root._services.get("circuit_breaker"):
            return
        from solagent.errors.circuit import CircuitBreaker

        cb = CircuitBreaker()
        self.ctx.provide("circuit_breaker", cb)


class MemoryPlugin(Plugin):
    """记忆管理插件，注册存储后端并提供记忆读写能力。"""
    name = "memory"
    inject = {}

    async def start(self):
        """组装 MemoryManager + MemoryStorage 并注入。"""
        if self.ctx.root._services.get("memory"):
            return
        from solagent.agents.memory.manager import MemoryManager
        from solagent.agents.memory.storage import MemoryStorage

        storage = MemoryStorage()
        manager = MemoryManager()
        manager.register(storage)
        self.ctx.provide("memory", manager)


class HookPlugin(Plugin):
    """Agent 钩子插件，提供生命周期拦截点。"""
    name = "hooks"
    inject = {}

    async def start(self):
        """注入默认 AgentHooks 实例。"""
        if self.ctx.root._services.get("hooks"):
            return
        from solagent.agents.hooks import AgentHooks

        hooks = AgentHooks()
        self.ctx.provide("hooks", hooks)


class MiddlewarePlugin(Plugin):
    """中间件链插件，管理 Agent 请求/响应的拦截链。"""
    name = "middleware"
    inject = {}

    async def start(self):
        """复用已有中间件链或创建新的 MiddlewareChain，并注册循环前 bail 处理器。"""
        existing = self.ctx.root._services.get("middleware")
        if existing:
            self._chain = existing
        else:
            from solagent.agents.middleware.chain import MiddlewareChain
            self._chain = MiddlewareChain()
            self.ctx.provide("middleware", self._chain)
        from solagent.cordis.events import BeforeAgentLoopEvent
        self.ctx.on(BeforeAgentLoopEvent, self._on_before_loop, mode="bail")

    def _on_before_loop(self, event):
        """在循环开始前构造上下文字典（当前仅占位）。"""
        context = {"messages": event.messages, "config": event.config}
        return None


class ToolRegistryPlugin(Plugin):
    """工具注册表插件，自动发现内置工具并统一管理。"""
    name = "tool_registry"
    inject = {}

    async def start(self):
        """扫描 solagent.agents.tools.builtins 模块自动注册工具。"""
        if self.ctx.root._services.get("tool_registry"):
            return
        from solagent.agents.tools.registry import ToolRegistry

        registry = ToolRegistry()
        registry.auto_discover("solagent.agents.tools.builtins")
        self.ctx.provide("tool_registry", registry)


class EventBusPlugin(Plugin):
    """事件总线插件，提供全局/局部事件发布订阅能力。"""
    name = "event_bus"
    inject = {}

    async def start(self):
        """注入 EventBus 与 EventScope。"""
        if self.ctx.root._services.get("event_bus"):
            return
        from solagent.events.bus import EventBus
        from solagent.events.scope import EventScope

        bus = EventBus()
        scope = EventScope()
        self.ctx.provide("event_bus", bus)
        self.ctx.provide("event_scope", scope)