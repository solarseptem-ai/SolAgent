"""反射服务，提供服务注册、解析和属性混入能力。

ReflectService 是 Cordis DI 容器的核心，负责维护服务实现（Impl）的存储和查找、
属性访问器（accessor）的声明以及 mixin 功能。通过事件通知机制，当服务注册或注销时
自动触发依赖该服务的 Fiber 重新检查依赖并更新状态。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from solagent.cordis.traceable import get_traceable



class Impl:
    """服务实现包装器，将服务值与其所属的 Fiber 和可用性检查绑定。

    属性说明：
        name: 服务名称。
        fiber: 提供该服务的 Fiber 实例。
        value: 服务的实际值。
        check: 可选的可用性检查函数。
    """
    __slots__ = ("name", "fiber", "value", "check")

    def __init__(self, name: str, fiber: Any, value: Any = None, check: Callable[[], bool] | None = None) -> None:
        self.name = name
        self.fiber = fiber
        self.value = value
        self.check = check


class ReflectService:
    """Cordis 反射服务，实现服务的注册、解析、通知和属性混入。

    核心职责：
        - store: 全局服务实现存储（按作用域键索引）。
        - props: 属性声明（accessor / service）。
        - provide: 注册服务并返回 dispose 函数。
        - notify: 服务变更时通知所有受影响的 Fiber 重新检查依赖。
        - mixin: 将其他服务的属性混入到上下文中。
    """

    def __init__(self, ctx: Any) -> None:
        self.root_ctx = ctx
        self.store: dict[Any, Impl] = {}   # 作用域键 -> Impl
        self.props: dict[str, Any] = {}    # 属性名 -> {type, get, set}

        # 将核心方法混入到 ctx，使 ctx.get、ctx.provide 等可直接调用
        self.mixin("reflect", ["get", "set", "provide", "accessor", "mixin"])
        self.mixin("events", ["on", "once", "parallel", "emit", "serial", "bail", "waterfall"])

    def _scope_key(self, caller_ctx: Any, name: str) -> Any:
        """根据调用者上下文的隔离配置计算服务的作用域键。

        若该名称在 isolate 中有特殊标记，则使用标记值作为键，实现服务的隔离作用域。
        """
        label = caller_ctx._isolate.get(name)
        return label if label is not None else name

    def provide(self, caller_ctx: Any, name: str, value: Any = None,
                check: Callable[[], bool] | None = None) -> Callable[[], None]:
        """在当前上下文中注册一个服务，返回用于注销的 dispose 函数。

        若服务名称已被声明为 accessor，则抛出 TypeError。
        注册时会自动将服务关联到 Fiber 的 store，并在 Fiber 活跃时通知依赖方。

        Args:
            caller_ctx: 调用者的 Cordis 上下文。
            name: 服务名称。
            value: 服务的值。
            check: 可选的可用性检查函数。

        Returns:
            调用后可注销该服务的 dispose 函数。
        """
        if name in self.props and self.props[name].get("type") == "accessor":
            raise TypeError(f"cannot provide '{name}': declared as accessor")

        self.props[name] = {"type": "service"}

        key = self._scope_key(caller_ctx, name)
        fiber = caller_ctx.fiber
        impl = Impl(name, fiber, value, check)
        self.store[key] = impl

        if fiber is not None and fiber.store is not None:
            fiber.store[name] = impl

        # Fiber 处于 ACTIVE 状态时立即通知依赖方
        if fiber is not None and fiber.state == 2:  # FIBER_ACTIVE
            self.notify([name])

        disposed = False

        def _dispose() -> None:
            nonlocal disposed
            if disposed:
                return
            disposed = True
            if self.store.get(key) is impl:
                del self.store[key]
            if fiber is not None and fiber.store is not None and fiber.store.get(name) is impl:
                del fiber.store[name]
            self.notify([name])

        # 将清理函数注册到 Fiber 的 effect 系统，确保 Fiber 释放时自动注销服务
        if fiber is not None:
            fiber.effect(_dispose)

        return _dispose

    def _get_impl(self, caller_ctx: Any, name: str) -> Any:
        """获取服务实现（Impl）对象，不返回具体值。

        查找顺序：全局 store -> Fiber store -> 父 Fiber store（沿 parent 链向上）。
        """
        key = self._scope_key(caller_ctx, name)
        impl = self.store.get(key)
        if impl is not None:
            return impl

        fiber = caller_ctx.fiber
        while fiber is not None:
            impl = fiber.store.get(name) if fiber.store is not None else None
            if impl is not None:
                return impl
            parent_ctx = fiber.parent
            fiber = getattr(parent_ctx, "fiber", None) if parent_ctx is not None else None
        return None

    def _resolve_chain(self, caller_ctx: Any, name: str) -> Any:
        """沿依赖链解析服务的实际值。

        查找顺序与 _get_impl 类似，但遇到所需的 inject 服务未就绪时会抛出 KeyError，
        最终未找到服务时也会抛出 KeyError。
        """
        key = self._scope_key(caller_ctx, name)

        if key != name:
            impl = self.store.get(key)
            if impl is not None and impl.fiber is not None and impl.fiber.uid is not None:
                return impl.value

        fiber = caller_ctx.fiber
        while fiber is not None:
            impl = fiber.store.get(name) if fiber.store is not None else None
            if impl is not None:
                return impl.value
            if name in fiber.inject:
                raise KeyError(f"cannot get required service '{name}' in inactive context")
            if fiber.runtime is None:
                break
            fiber = fiber.parent.fiber if fiber.parent is not None else None

        impl = self.store.get(key)
        if impl is not None and impl.fiber is not None and impl.fiber.uid is not None:
            return impl.value
        raise KeyError(f"service '{name}' not found")

    def get(self, caller_ctx: Any, name: str, strict: bool = True) -> Any:
        """获取指定名称的服务值。

        Args:
            caller_ctx: 调用者的 Cordis 上下文。
            name: 服务名称。
            strict: 为 True 时，若服务由已释放的 Fiber 提供则抛出 KeyError。

        Returns:
            服务的实际值。

        Raises:
            KeyError: 服务不存在或由已释放 Fiber 提供（strict 模式下）。
        """
        impl = self._get_impl(caller_ctx, name)
        if impl is None:
            raise KeyError(f"service '{name}' not found")
        if strict and impl.fiber is not None and impl.fiber.uid is None:
            raise KeyError(f"service '{name}' provided by disposed fiber")
        return impl.value

    def set(self, caller_ctx: Any, name: str, value: Any) -> bool:
        """设置指定名称的服务值，仅限由当前 Fiber 提供的服务。

        隔离作用域的服务直接修改；非隔离作用域的服务需沿 Fiber 链查找，
        确认当前 Fiber 是该服务的提供者后才能修改。

        Args:
            caller_ctx: 调用者的 Cordis 上下文。
            name: 服务名称。
            value: 新值。

        Returns:
            是否成功设置。

        Raises:
            KeyError: 服务从未被提供过。
            RuntimeError: 服务由其他 Fiber 提供，不允许修改。
        """
        key = self._scope_key(caller_ctx, name)
        is_isolated = key != name

        if is_isolated:
            impl = self.store.get(key)
            if impl is None:
                raise KeyError(f"cannot set '{name}': never provided")
            impl.value = value
            return True

        fiber = caller_ctx.fiber
        while fiber is not None:
            impl = fiber.store.get(name) if fiber.store is not None else None
            if impl is not None:
                if impl.fiber is caller_ctx.fiber:
                    impl.value = value
                    return True
                raise RuntimeError(f"cannot set '{name}': provided by another fiber")
            parent_ctx = fiber.parent
            fiber = getattr(parent_ctx, "fiber", None) if parent_ctx is not None else None

        raise KeyError(f"cannot set '{name}': never provided")

    def notify(self, names: list[str]) -> list[Any]:
        """通知指定服务名称的变更，触发所有依赖这些服务的 Fiber 重新检查依赖。

        遍历注册表中所有运行时和 Fiber，检查 inject 依赖是否受此次变更影响，
        并触发 Fiber 的依赖刷新。同时发射 internal/service 事件供外部监听。

        Args:
            names: 发生变更的服务名称列表。

        Returns:
            受影响的 Fiber 列表。
        """
        affected: list[Any] = []
        registry = getattr(self.root_ctx, "registry", None)
        if registry is None:
            return affected

        for runtime in registry.values():
            for fiber in runtime.fibers:
                if fiber.uid is None:
                    continue
                if not any(n in fiber.inject for n in names):
                    continue
                affected.append(fiber)
                for n in names:
                    if n in fiber.inject:
                        fiber._check_impl(n)
                fiber._refresh()

        for name in names:
            self.root_ctx.events.emit("internal/service", self.root_ctx, name,
                                       self._get_impl(self.root_ctx, name))
        return affected

    def accessor(self, name: str, getter: Callable[[Any], Any],
                 setter: Callable[[Any, Any], bool] | None = None) -> Callable[[], None]:
        """声明一个属性访问器，拦截对指定名称的属性访问。

        Args:
            name: 属性名称。
            getter: 获取属性的回调函数。
            setter: 可选的设置属性的回调函数。

        Returns:
            调用后可移除该访问器声明的 dispose 函数。

        Raises:
            TypeError: 若该名称已被声明为属性。
        """
        if name in self.props:
            raise TypeError(f"property '{name}' already declared")
        self.props[name] = {"type": "accessor", "get": getter, "set": setter}

        def _dispose() -> None:
            self.props.pop(name, None)

        return _dispose

    def mixin(self, source: str, mixins: list[str] | dict[str, str]) -> Callable[[], None]:
        """将其他服务的属性混入到当前上下文中，使 ctx.attr 可代理到 ctx.source.attr。

        Args:
            source: 源服务名称。
            mixins: 要混入的属性列表，或 {属性名: 源服务属性名} 映射字典。

        Returns:
            调用后可移除所有混入声明的 dispose 函数。
        """
        if isinstance(mixins, list):
            mixin_map = {m: m for m in mixins}
        else:
            mixin_map = mixins

        disposers = []
        for attr, service_name in mixin_map.items():
            def _get(_self: Any, _attr: str = attr, _svc: str = service_name) -> Any:
                service = _self.reflect.get(_self, _svc)
                return getattr(service, _attr)

            def _set(_self: Any, value: Any, _attr: str = attr, _svc: str = service_name) -> bool:
                service = _self.reflect.get(_self, _svc)
                setattr(service, _attr, value)
                return True

            disposers.append(self.accessor(attr, _get, _set))

        def _dispose() -> None:
            for d in disposers:
                d()

        return _dispose

    def trace(self, value: Any) -> Any:
        """将值包装为可追踪对象，绑定到根上下文。"""
        return get_traceable(self.root_ctx, value)

    def bind(self, callback: Callable[..., Any]) -> Callable[..., Any]:
        """绑定回调函数，自动追踪其参数并绑定到当前上下文。

        包装后的函数在调用时，所有参数都会通过 trace() 进行上下文绑定。
        """
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            traced_args = [self.trace(a) for a in args]
            traced_kwargs = {k: self.trace(v) for k, v in kwargs.items()}
            return callback(*traced_args, **traced_kwargs)

        return wrapper