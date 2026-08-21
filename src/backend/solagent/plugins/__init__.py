"""
插件系统核心模块。

提供插件的生命周期管理：Plugin 抽象基类、PluginContext 依赖注入容器、
Fiber 状态机、PluginManager 注册与拓扑排序激活。
支持事件监听（emit/parallel/serial/bail/waterfall 五种模式）和副作用清理。
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from enum import Enum, auto
from typing import Any, ClassVar

from pydantic import BaseModel

from solagent.events.types import AgentEvent, AgentEventType


class PluginEvent(AgentEvent):
    """插件事件 — 继承 AgentEvent，统一事件流。可序列化、可跨进程传输。"""
    event_type: AgentEventType = AgentEventType.PLUGIN_EVENT
    source: str = ""


class PluginState(Enum):
    """插件生命周期状态枚举。"""
    PENDING = auto()    # 待激活
    LOADING = auto()    # 加载中（等待依赖）
    ACTIVE = auto()     # 已激活
    DISPOSED = auto()   # 已卸载


# 可清理资源类型和事件监听器类型别名
Disposable = Callable[[], Any]
Listener = Callable[..., Coroutine[Any, Any, Any]]


class Plugin(ABC):
    """插件抽象基类，所有插件需继承此类。

    Attributes:
        name: 插件名称类属性。
        inject: 声明依赖的服务名称字典。
        Config: 可选的 Pydantic 配置模型。
        ctx: 插件上下文，由管理器注入。
    """

    name: ClassVar[str] = ""
    inject: ClassVar[dict[str, Any]] = {}
    Config: ClassVar[type[BaseModel] | None] = None

    def __init__(self, ctx: PluginContext):
        self.ctx = ctx

    async def start(self) -> None:
        """插件启动钩子，子类可覆盖以执行初始化逻辑。"""
        pass

    async def stop(self) -> None:
        """插件停止钩子，子类可覆盖以执行清理逻辑。"""
        pass


class PluginContext:
    """插件上下文 — DI 容器 + 事件总线。

    __getattr__ 沿 fiber 树向上查找服务，支持声明式依赖注入。
    ctx.llm / ctx.tools / ctx.memory 等通过服务注册自动解析。
    事件分发委托给 EventBus 实现统一事件流。

    Attributes:
        root: 根上下文。
        fiber: 关联的 Fiber 实例。
        registry: 插件管理器引用。
        _services: 已注册的服务字典。
        _events: 事件监听器字典。
        _disposables: 待清理资源列表。
        event_bus: 可选的事件总线实例。
    """

    __slots__ = ('root', 'fiber', 'registry', '_services', '_events', '_disposables', 'logger', 'event_bus')

    def __init__(self, root: PluginContext | None = None):
        self.root = root or self
        self.fiber: Fiber | None = None
        self.registry: PluginManager | None = None
        self._services: dict[str, Any] = {}
        self._disposables: list[Disposable] = []
        self.event_bus = None
        if root is None:
            self._events: dict[type, list[tuple[Listener, str]]] = {}
        self.logger = None

    def __getattr__(self, name: str) -> Any:
        # 保护私有属性访问
        if name.startswith('_'):
            raise AttributeError(name)
        if name in self.__slots__:
            return object.__getattribute__(self, name)
        return self._resolve(name)

    def _resolve(self, name: str) -> Any:
        """沿上下文链解析服务名称，优先 root 服务，再沿 fiber 树向上查找激活中的服务。"""
        if name in self.root._services:
            return self.root._services[name]
        if name in self._services:
            return self._services[name]
        fiber = self.fiber
        while fiber is not None:
            impl = fiber._services.get(name)
            if impl is not None and fiber._state == PluginState.ACTIVE:
                return impl
            fiber = fiber.parent.fiber if fiber.parent else None
        raise AttributeError(f"service '{name}' not provided in any active plugin")

    def provide(self, name: str, value: Any) -> Disposable:
        """向根上下文注册一个服务，返回可调用以注销的清理函数。"""
        self.root._services[name] = value
        def _dispose():
            self.root._services.pop(name, None)
        self._disposables.append(_dispose)
        return _dispose

    def on(self, event_type: type[PluginEvent], callback: Listener, mode: str = "emit") -> None:
        """注册事件监听器。"""
        if event_type not in self.root._events:
            self.root._events[event_type] = []
        self.root._events[event_type].append((callback, mode))

    def emit(self, event: PluginEvent) -> None:
        """以 emit 模式触发事件，异步执行匹配监听器，并同步转发到 EventBus。"""
        for cb, mode in self.root._events.get(type(event), []):
            if mode == "emit":
                asyncio.create_task(cb(event))
        if self.root.event_bus is not None:
            self.root.event_bus.emit(event)

    async def parallel(self, event: PluginEvent) -> None:
        """以 parallel 模式触发事件，并发执行所有匹配监听器。"""
        tasks = [cb(event) for cb, mode in self.root._events.get(type(event), []) if mode == "parallel"]
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            errors = [r for r in results if isinstance(r, Exception)]
            if errors:
                raise ExceptionGroup("event dispatch errors", errors)

    async def serial(self, event: PluginEvent) -> Any:
        """以 serial 模式触发事件，顺序执行监听器，返回首个非 None/False 的结果。"""
        for cb, mode in self.root._events.get(type(event), []):
            if mode == "serial":
                result = await cb(event)
                if result is not None and result is not False:
                    return result
        return None

    def bail(self, event: PluginEvent) -> Any:
        """以 bail 模式触发事件，同步执行监听器，返回首个非 None/False 的结果。"""
        for cb, mode in self.root._events.get(type(event), []):
            if mode == "bail":
                result = cb(event)
                if result is not None and result is not False:
                    return result
        return None

    def waterfall(self, event: PluginEvent) -> Any:
        """以 waterfall 模式触发事件，支持链式调用 next_fn 传递控制权。"""
        hooks = [(cb, mode) for cb, mode in self.root._events.get(type(event), []) if mode == "waterfall"]
        if not hooks:
            return None

        def _run(index: int, evt: PluginEvent) -> Any:
            if index >= len(hooks):
                return None
            cb, _ = hooks[index]
            return cb(evt, lambda: _run(index + 1, evt))

        return _run(0, event)

    def effect(self, body: Callable) -> Disposable:
        """注册副作用，body 的执行结果会被收集为可清理资源。

        若 body 执行异常，自动触发清理。
        """
        disposed = False
        local_disposables: list[Disposable] = []

        async def dispose():
            nonlocal disposed
            if disposed:
                return
            disposed = True
            for d in reversed(local_disposables):
                result = d()
                if hasattr(result, '__await__'):
                    await result

        try:
            result = body()
            if callable(result):
                local_disposables.append(result)
            elif hasattr(result, '__aiter__'):
                async def _collect():
                    async for d in result:
                        local_disposables.append(d)
                asyncio.create_task(_collect())
            elif hasattr(result, '__iter__'):
                local_disposables.extend(result)
        except Exception:
            asyncio.create_task(dispose())
            raise

        self._disposables.append(dispose)
        return dispose

    async def dispose_all(self) -> None:
        """逆序清理所有已注册的可清理资源。"""
        for d in reversed(self._disposables):
            result = d()
            if hasattr(result, '__await__'):
                await result
        self._disposables.clear()


class Fiber:
    """插件运行时实例 — 简化 4 态状态机。

    Attributes:
        _plugin_cls: 插件类。
        _config: 插件配置字典。
        _state: 当前生命周期状态。
        _services: Fiber 本地服务字典。
        _inertia: 惯性任务（用于等待）。
        _error: 激活过程中的异常。
        plugin: 实例化的插件对象。
        parent: 父 PluginContext。
        ctx: 插件上下文。
    """

    PENDING = PluginState.PENDING
    LOADING = PluginState.LOADING
    ACTIVE = PluginState.ACTIVE
    DISPOSED = PluginState.DISPOSED

    def __init__(self, plugin_cls: type[Plugin], config: dict | None, ctx: PluginContext):
        self._plugin_cls = plugin_cls
        self._config = config or {}
        self._state = PluginState.PENDING
        self._services: dict[str, Any] = {}
        self._inertia: asyncio.Task | None = None
        self._error: Exception | None = None
        self.plugin: Plugin | None = None
        self.parent = ctx
        self.ctx = PluginContext(root=ctx.root)
        self.ctx.fiber = self
        self.ctx.registry = ctx.registry

    @property
    def state(self) -> PluginState:
        """当前生命周期状态。"""
        return self._state

    @property
    def is_active(self) -> bool:
        """是否已激活。"""
        return self._state == PluginState.ACTIVE

    async def activate(self) -> None:
        """激活插件：等待依赖 -> 校验配置 -> 实例化 -> 调用 start。"""
        if self._state != PluginState.PENDING:
            return
        self._state = PluginState.LOADING

        await self._wait_deps()
        if self._state == PluginState.DISPOSED:
            return

        config = self._validate_config()
        self.plugin = self._plugin_cls(self.ctx)
        self.plugin.ctx = self.ctx
        self.plugin._config = config

        try:
            await self.plugin.start()
        except Exception as e:
            self._error = e
            self._state = PluginState.DISPOSED
            raise

        self._state = PluginState.ACTIVE

    async def _wait_deps(self) -> None:
        """轮询等待 inject 声明的所有依赖就绪，最多等待 100 次（约 5 秒）。"""
        inject = getattr(self._plugin_cls, 'inject', {})
        if isinstance(inject, list):
            inject = {k: None for k in inject}
        if not inject:
            return

        for _ in range(100):
            if self._state == PluginState.DISPOSED:
                return
            all_ready = True
            for dep_name in inject:
                try:
                    self.ctx._resolve(dep_name)
                except AttributeError:
                    all_ready = False
                    break
            if all_ready:
                return
            await asyncio.sleep(0.05)
        raise TimeoutError(f"Timed out waiting for dependencies: {list(inject.keys())}")

    def _validate_config(self) -> dict:
        """若插件声明了 Config Pydantic 模型，则进行校验并返回字典。"""
        cfg_cls = getattr(self._plugin_cls, 'Config', None)
        if cfg_cls is None:
            return self._config
        validated = cfg_cls(**self._config)
        return validated.model_dump()

    async def dispose(self) -> None:
        """卸载插件，调用 stop 并清理上下文资源。"""
        if self._state == PluginState.DISPOSED:
            return
        if self.plugin:
            await self.plugin.stop()
        await self.ctx.dispose_all()
        self._state = PluginState.DISPOSED

    def __await__(self):
        return self._await().__await__()

    async def _await(self):
        """等待插件进入非 pending/loading 状态。"""
        while self._state in (PluginState.PENDING, PluginState.LOADING):
            if self._inertia:
                await self._inertia
            else:
                await asyncio.sleep(0.05)
        return self


class PluginManager:
    """插件管理器 — 注册、拓扑排序激活、卸载。

    Attributes:
        _plugins: 插件名称到 Fiber 的映射。
        _ctx: 根插件上下文。
    """

    def __init__(self):
        from solagent.events.bus import EventBus

        self._plugins: dict[str, Fiber] = {}
        self._ctx = PluginContext()
        self._ctx.event_bus = EventBus()

    def register(self, plugin_cls: type[Plugin], config: dict | None = None) -> Fiber:
        """注册一个插件类并创建对应的 Fiber。

        Args:
            plugin_cls: 插件类。
            config: 可选的配置字典。

        Returns:
            创建的 Fiber 实例。
        """
        name = plugin_cls.name or plugin_cls.__name__
        self._ctx.provide(name, None)
        fiber = Fiber(plugin_cls, config, self._ctx)
        self._plugins[name] = fiber
        return fiber

    async def start_all(self) -> None:
        """按拓扑排序顺序激活所有已注册的插件。"""
        ordered = self._topological_sort()
        for name in ordered:
            fiber = self._plugins[name]
            await fiber.activate()

    async def stop_all(self) -> None:
        """逆序卸载所有已注册的插件。"""
        for name in reversed(list(self._plugins.keys())):
            fiber = self._plugins[name]
            await fiber.dispose()

    async def unregister(self, name: str) -> None:
        """注销指定名称的插件。"""
        if name not in self._plugins:
            raise KeyError(f"Plugin '{name}' not registered")
        fiber = self._plugins.pop(name)
        await fiber.dispose()
        self._ctx.root._services.pop(name, None)

    def list(self) -> list[str]:
        """列出所有已注册的插件名称。"""
        return list(self._plugins.keys())

    def get(self, name: str) -> Plugin | None:
        """按名称获取已激活的插件实例。"""
        fiber = self._plugins.get(name)
        return fiber.plugin if fiber else None

    def has(self, name: str) -> bool:
        """检查是否注册了指定名称的插件。"""
        return name in self._plugins

    def _topological_sort(self) -> list[str]:
        """基于 inject 依赖关系对插件进行拓扑排序。

        依赖其他插件的插件会在被依赖插件之后激活。
        """
        in_degree: dict[str, int] = {}
        deps: dict[str, list[str]] = {}

        for name, fiber in self._plugins.items():
            if name not in in_degree:
                in_degree[name] = 0
            inject = getattr(fiber._plugin_cls, 'inject', {})
            if isinstance(inject, list):
                inject = {k: None for k in inject}
            deps[name] = list(inject.keys())
            for dep in inject:
                if dep in self._plugins:
                    in_degree[name] = in_degree.get(name, 0) + 1

        queue = [n for n, d in in_degree.items() if d == 0]
        result = []

        while queue:
            node = queue.pop(0)
            result.append(node)
            for name, dep_list in deps.items():
                if node in dep_list:
                    in_degree[name] -= 1
                    if in_degree[name] == 0:
                        queue.append(name)

        return result