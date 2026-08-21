"""全功能上下文 —— 支持插件生命周期的层级依赖注入容器。

Context 是 Cordis 框架的核心根容器，管理服务的注册、解析、作用域隔离和事件委托。
每个 Context 可以拥有父级链，形成层级化的 DI 树；子上下文自动继承父级的服务，
但可以通过 _isolate 和 _intercept 实现作用域隔离与配置拦截。

根上下文（parent=None）负责初始化所有核心服务：EventsService、ReflectService、
RegistryService、LoggerService 以及 Fiber 状态机。子上下文则共享这些服务实例。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from solagent.cordis.events import EventsService
from solagent.cordis.fiber import Fiber
from solagent.cordis.logger import LoggerService
from solagent.cordis.reflect import ReflectService
from solagent.cordis.registry import RegistryService
from solagent.cordis.traceable import get_traceable
from solagent.cordis.utils import ScopeDict


class Context:
    """Cordis 根依赖注入容器。

    每个 Context 拥有父级链、Fiber 生命周期状态机和服务注册表。
    通过 __getattr__ / __setattr__ 实现动态服务访问和属性代理，
    使 ctx.service_name 可直接访问已注册的服务或反射属性。
    """

    def __init__(self, parent: "Context | None" = None) -> None:
        """初始化上下文容器。

        Args:
            parent: 父级上下文，None 表示创建根上下文。
        """
        self.parent = parent
        self._store: dict[str, Any] = {}      # 当前层级独有的覆盖值
        self._services: dict[str, Any] = {}    # 向后兼容的扁平服务字典

        # 隔离作用域和拦截配置均使用原型链字典，子级自动继承父级
        if parent is None:
            self._isolate = ScopeDict()
            self._intercept = ScopeDict()
        else:
            self._isolate = ScopeDict(parent=parent._isolate)
            self._intercept = ScopeDict(parent=parent._intercept)

        if parent is None:
            # 根上下文：初始化核心服务和 Fiber 状态机
            self.fiber = Fiber(parent_ctx=None, uid=0, runtime=None)
            self.fiber.state = 2  # 直接设为 ACTIVE，根 Fiber 无需加载过程
            self.fiber._epoch = ""
            self._events = EventsService()
            self.reflect = ReflectService(self)
            self.registry = RegistryService(self)
            self.logger_svc = LoggerService(self)
        else:
            # 子上下文共享父级的核心服务实例
            self.fiber = parent.fiber
            self._events = parent._events
            self.reflect = parent.reflect
            self.registry = parent.registry
            self.logger_svc = parent.logger_svc

    @property
    def root(self) -> "Context":
        """沿父级链向上追溯，返回根上下文（parent 为 None 的节点）。"""
        ctx: Context = self
        while ctx.parent is not None:
            ctx = ctx.parent
        return ctx

    @property
    def events(self) -> EventsService:
        """返回当前上下文关联的事件总线服务。"""
        return self._events

    @property
    def event_bus(self) -> Any:
        """获取外部事件总线桥接器。"""
        return self._events.event_bus

    @event_bus.setter
    def event_bus(self, bus: Any) -> None:
        """设置外部事件总线桥接器，用于与外部事件系统（如 SolAgent EventBus）对接。"""
        self._events.event_bus = bus

    @property
    def logger(self) -> Any:
        """返回追踪代理包装后的日志服务，支持上下文感知的日志记录。"""
        return get_traceable(self, self.logger_svc)

    # ---- service access ----

    def provide(self, name: str, value: Any, check: Callable[[], bool] | None = None) -> Callable[[], None]:
        """在当前上下文注册一个服务，使其可通过 ctx.name 访问。

        Args:
            name: 服务名称。
            value: 服务实例或值。
            check: 可选的可用性检查函数。

        Returns:
            注销该服务的 dispose 函数。
        """
        # 同时存入根上下文的 _services 字典（向后兼容）和反射服务中
        self.root._services[name] = value
        return self.reflect.provide(self, name, value, check)

    def get(self, name: str) -> Any:
        """按名称从反射服务中解析值（沿 _resolve_chain 查找）。"""
        return self.reflect._resolve_chain(self, name)

    def set(self, name: str, value: Any) -> bool:
        """在反射服务中设置名称对应的值。"""
        return self.reflect.set(self, name, value)

    def has(self, name: str) -> bool:
        """检查指定名称的服务是否存在于当前上下文中。"""
        try:
            self.reflect.get(self, name)
            return True
        except KeyError:
            return False

    def __getattr__(self, name: str) -> Any:
        """动态属性访问：优先查找反射属性，其次解析服务链，最后触发 internal/get 瀑布事件。

        这是 ctx.service_name 语法的核心实现，支持 accessor 属性、服务实例和事件拦截。
        """
        if name == "_services":
            return self._services
        if name.startswith("_"):
            raise AttributeError(name)
        reflect = self.__dict__.get("reflect")
        if reflect is None:
            raise AttributeError(name)

        # 优先处理 accessor 类型的反射属性（如 getter/setter）
        if name in reflect.props:
            prop = reflect.props[name]
            if prop.get("type") == "accessor":
                return prop["get"](self)

        # 通过反射服务解析名称对应的服务或值
        try:
            value = self.reflect._resolve_chain(self, name)
            return get_traceable(self, value)
        except KeyError:
            pass

        # 若仍未找到，触发 internal/get 瀑布事件，允许其他插件拦截并提供值
        error = AttributeError(f"no service or attribute '{name}'")

        def default_next() -> Any:
            raise error

        result = self._events.waterfall_next("internal/get", self, name, error, next_fn=default_next)
        if result is not None:
            return result

        raise AttributeError(f"no service or attribute '{name}'") from None

    def __setattr__(self, name: str, value: Any) -> None:
        """动态属性设置：优先处理反射属性和服务注册，最后回退到普通属性赋值。"""
        if name.startswith("_"):
            super().__setattr__(name, value)
            return
        reflect = self.__dict__.get("reflect")
        if reflect is None:
            super().__setattr__(name, value)
            return

        # 若名称对应 accessor 属性，调用其 setter
        if name in reflect.props:
            prop = reflect.props[name]
            if prop.get("type") == "accessor":
                if prop.get("set"):
                    prop["set"](self, value)
                return
            else:
                try:
                    reflect.set(self, name, value)
                except KeyError:
                    super().__setattr__(name, value)
                return

        # 尝试通过反射服务设置，失败则回退到普通属性赋值
        try:
            reflect.set(self, name, value)
        except KeyError:
            super().__setattr__(name, value)

    # ---- scope management ----

    def extend(self) -> "Context":
        """创建当前上下文的子级副本，继承所有服务和作用域。"""
        child = Context(parent=self)
        return child

    def isolate(self, name: str, label: Any = None) -> "Context":
        """创建隔离子上下文，使指定名称的服务在独立作用域中解析。

        Args:
            name: 要隔离的服务名称。
            label: 可选的隔离标识，默认生成唯一对象。
        """
        child = self.extend()
        child._isolate = ScopeDict(parent=self._isolate, data={name: label if label is not None else object()})
        return child

    def intercept(self, name: str, config: Any) -> "Context":
        """创建拦截子上下文，为指定名称的服务附加拦截配置。

        Args:
            name: 要拦截的服务名称。
            config: 拦截配置字典，会在服务实例化时合并。
        """
        child = self.extend()
        child._intercept = ScopeDict(parent=self._intercept, data={name: config})
        return child

    def using(self, names: list[str], callback: Callable[..., Any]) -> Any:
        """注册一个一次性回调，当所有指定服务都可用时执行，然后自动释放。

        Args:
            names: 依赖的服务名称列表。
            callback: 所有依赖就绪后执行的回调函数。
        """
        async def _using(ctx: "Context", _config: Any) -> Any:
            return callback(ctx)

        return self.plugin({"apply": _using, "inject": names})

    def selector(self, predicate: Callable[["Context"], bool]) -> "Context":
        """创建带谓词过滤器的子上下文，仅当 predicate 返回 True 时事件监听器才会生效。

        Args:
            predicate: 接收 Context 返回 bool 的过滤函数。
        """
        child = self.extend()
        child._filter = predicate
        return child

    # ---- plugin lifecycle ----

    async def plugin(self, plugin: Any, config: Any = None) -> Fiber:
        """加载一个插件并返回其 Fiber 生命周期对象。

        Args:
            plugin: 插件定义，可以是类、函数或字典（含 apply/inject）。
            config: 插件配置。

        Returns:
            插件的 Fiber 对象，用于跟踪其生命周期状态。
        """
        child = self.extend()
        fiber = self.registry.plugin(plugin, config)
        child.fiber = fiber
        fiber.ctx = child

        # 若插件的 inject 项中包含字典，则将其合并为拦截配置（祖先优先，通过 ScopeDict 链继承）
        inject_entries = {k: v for k, v in fiber.inject.items() if isinstance(v, dict)}
        if inject_entries:
            child._intercept = ScopeDict(parent=child._intercept, data=inject_entries)

        try:
            await fiber.await_start()
        except Exception:
            # 插件加载过程中的异常由 Fiber 内部捕获并标记为 FAILED，此处忽略
            pass
        return fiber

    async def inject(self, deps: dict[str, str], callback: Callable[..., Any]) -> Fiber:
        """按名称解析依赖字典，然后将解析结果传递给回调函数执行。

        Args:
            deps: 依赖映射 {回调参数名: 服务名称}。
            callback: 接收解析后依赖字典的回调函数。

        Returns:
            插件的 Fiber 对象。
        """
        async def _plugin(ctx: "Context", _config: Any) -> Any:
            resolved = {key: ctx.get(name) for key, name in deps.items()}
            result = callback(resolved)
            if hasattr(result, "__await__"):
                return await result
            return result

        return await self.plugin(_plugin)

    # ---- event delegation ----

    def effect(self, callback: Callable[..., Any]) -> Callable[..., Any]:
        """注册一个副作用清理函数，当前 Fiber 卸载时自动调用。"""
        return self.fiber.effect(callback)

    def on(self, name: str | type, listener: Callable[..., Any], **kwargs: Any) -> Callable[[], None]:
        """注册事件监听器，并自动将其注销函数绑定到当前 Fiber 的生命周期中。

        当 Fiber 被卸载或释放时，监听器会自动移除，避免内存泄漏。
        """
        off = self._events.on(name, listener, **kwargs)
        if self.fiber is not None:
            self.fiber.effect(off)
        return off

    def once(self, name: str | type, listener: Callable[..., Any]) -> Callable[[], None]:
        """注册一次性事件监听器，触发后自动移除，并绑定到 Fiber 生命周期。"""
        off = self._events.once(name, listener)
        if self.fiber is not None:
            self.fiber.effect(off)
        return off

    def emit(self, name: str | Any, *args: Any) -> None:
        """同步触发事件。字符串事件直接广播参数；类型事件触发类型分发。"""
        if isinstance(name, str):
            self._events.emit(name, *args)
        else:
            self._events.emit(name)

    async def parallel(self, name: str, *args: Any) -> None:
        """并发触发事件，等待所有异步监听器完成。"""
        await self._events.parallel(name, *args)

    async def serial(self, name: str, *args: Any) -> Any:
        """顺序触发事件，任一监听器返回 bail 值则提前终止并返回结果。"""
        return await self._events.serial(name, *args)

    def bail(self, name: str, *args: Any) -> Any:
        """顺序触发事件，任一监听器返回非 None 且非 False 的值则立即返回该值。"""
        return self._events.bail(name, *args)

    def waterfall(self, name: str | Any, *args: Any) -> Any:
        """瀑布式触发事件，将上一个监听器的返回值依次传递给下一个。

        支持字符串事件和类型事件两种分发模式。
        """
        if isinstance(name, str):
            return self._events.waterfall(name, *args)
        else:
            return self._events._waterfall_type(name)

    # ---- teardown ----

    async def dispose(self) -> None:
        """释放当前上下文。根上下文会同时释放 Fiber、清理反射服务和事件总线。"""
        if self.parent is None:
            if hasattr(self, "fiber") and self.fiber is not None:
                await self.fiber.dispose()
            if hasattr(self, "reflect") and self.reflect is not None:
                self.reflect.store.clear()
                self.reflect.props.clear()
            self._events.clear()
            self._store.clear()

    async def dispose_all(self) -> None:
        """释放整个上下文树（从根上下文开始）。"""
        await self.dispose()