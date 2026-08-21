"""追踪代理模块，实现服务上下文的动态重绑定。

当通过 `ctx.service_name` 访问带有 tracker 的服务时，TraceableProxy 会拦截
属性访问和方法调用，将服务方法中的 `self` 替换为调用者的上下文而非提供者的上下文。
这使得 `ctx.on()` 能将监听器绑定到正确的 fiber，`ctx.logger()` 能获取正确的 fiber 名称。

核心组件：
    ShadowContext: 在服务方法调用中替代 self，重绑定 tracker.property。
    TraceableProxy: 包装服务值，拦截属性访问以实现上下文重绑定。
"""

from __future__ import annotations

from typing import Any

from solagent.cordis.symbols import ORIGINAL, SHADOW


class ShadowContext:
    """影子上下文，在服务方法调用中替代 self 对象。

    将 tracker 中声明的 property 字段重绑定到调用者的上下文，
    使服务方法能够感知到调用方所在的 Cordis 上下文环境。
    """

    def __init__(self, caller_ctx: Any, original: Any, tracker: dict[str, Any]) -> None:
        # 使用 object.__setattr__ 绕过自身的 __setattr__ 拦截
        object.__setattr__(self, "_caller_ctx", caller_ctx)
        object.__setattr__(self, "_original", original)
        object.__setattr__(self, "_tracker", tracker)

    def __getattr__(self, name: str) -> Any:
        """属性访问拦截：若访问的是 tracker.property 则返回调用者上下文，否则委托给原对象。"""
        if name.startswith("_"):
            raise AttributeError(name)
        if name == self._tracker.get("property"):
            return self._caller_ctx
        return getattr(self._original, name)

    def __setattr__(self, name: str, value: Any) -> None:
        """属性设置拦截：内部属性直接设置，其他属性委托给原对象。"""
        if name.startswith("_"):
            super().__setattr__(name, value)
            return
        setattr(self._original, name, value)


class TraceableProxy:
    """可追踪代理，包装服务值以拦截属性访问并重绑定上下文。

    当服务带有 tracker 配置时，通过该代理访问的属性会根据 tracker 规则
    自动重绑定到调用者的 Cordis 上下文，实现跨上下文的服务共享。
    """

    def __init__(self, ctx: Any, value: Any, tracker: dict[str, Any]) -> None:
        object.__setattr__(self, "_ctx", ctx)
        object.__setattr__(self, "_value", value)
        object.__setattr__(self, "_tracker", tracker)

    def __getattr__(self, name: str) -> Any:
        """属性访问拦截逻辑：

        1. 访问 ORIGINAL 返回被包装的原始值。
        2. 访问 tracker.property 返回当前绑定的上下文。
        3. 检查关联属性映射（associate）。
        4. 若内部值也有 tracker，递归包装。
        5. 若属性是可调用方法且未禁用 shadow，创建影子方法包装器。
        """
        if name == ORIGINAL:
            return self._value
        if name == self._tracker.get("property"):
            return self._ctx

        # 检查关联属性映射：若 ctx.reflect.props 中存在 assoc.name 则返回该属性
        assoc = self._tracker.get("associate")
        if assoc and hasattr(self._ctx, "reflect"):
            prop_key = f"{assoc}.{name}"
            if prop_key in self._ctx.reflect.props:
                return getattr(self._ctx, prop_key)

        inner = getattr(self._value, name)
        inner_tracker = getattr(inner, "tracker", None) or getattr(type(inner), "tracker", None)
        if inner_tracker:
            return get_traceable(self._ctx, inner, inner_tracker)

        if callable(inner) and not self._tracker.get("noShadow"):
            return _create_shadow_method(self._ctx, self._value, name, self._tracker)

        return inner

    def __setattr__(self, name: str, value: Any) -> None:
        """属性设置拦截，优先写入关联属性映射，其次写入被包装对象。"""
        if name.startswith("_"):
            super().__setattr__(name, value)
            return
        if name == self._tracker.get("property"):
            return
        assoc = self._tracker.get("associate")
        if assoc and hasattr(self._ctx, "reflect"):
            prop_key = f"{assoc}.{name}"
            if prop_key in self._ctx.reflect.props:
                setattr(self._ctx, prop_key, value)
                return
        setattr(self._value, name, value)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """支持将代理作为可调用对象使用，优先调用被包装值的 invoke 方法。"""
        if hasattr(self._value, "invoke") and callable(self._value.invoke):
            return self._value.invoke(self, *args, **kwargs)
        return self._value(*args, **kwargs)


def _create_shadow_method(ctx: Any, service: Any, method_name: str, tracker: dict[str, Any]) -> Any:
    """创建影子方法包装器，在调用时将 self 替换为 ShadowContext。

    Args:
        ctx: 调用者的 Cordis 上下文。
        service: 被调用的服务实例。
        method_name: 方法名称。
        tracker: 追踪器配置。

    Returns:
        包装后的方法，调用时自动将 self 替换为 ShadowContext。
    """
    func = getattr(type(service), method_name, None)
    if func is None:
        return getattr(service, method_name)

    shadow = ShadowContext(ctx, service, tracker)

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        result = func(shadow, *args, **kwargs)
        return get_traceable(ctx, result)

    return wrapper


def get_traceable(ctx: Any, value: Any) -> Any:
    """若值带有 tracker 配置，则将其包装在 TraceableProxy 中以重绑定上下文。

    基本类型的值直接返回，不进行包装。若值已有 SHADOW 标记则直接解包。
    对于 noShadow 服务，保留影子上下文（如 logger 需要原始 fiber 信息）。

    Args:
        ctx: 要绑定的 Cordis 上下文。
        value: 待包装的值。

    Returns:
        包装后的 TraceableProxy，或原始值（若无需包装）。
    """
    if not _is_object(value):
        return value
    # 解包已有的 shadow 标记
    if hasattr(value, SHADOW):
        return getattr(value, SHADOW)
    tracker = getattr(value, "tracker", None) or getattr(type(value), "tracker", None)
    if tracker is None:
        return value
    # noShadow 服务保留影子上下文（例如 logger 需要原始 fiber 名称）
    if getattr(ctx, SHADOW, None) and not tracker.get("noShadow"):
        ctx = getattr(ctx, "parent", ctx)
    return TraceableProxy(ctx, value, tracker)


def _is_object(value: Any) -> bool:
    """判断值是否为需要包装的对象类型（排除基本类型和容器类型）。"""
    return value is not None and not isinstance(value, (int, float, str, bool, bytes, list, tuple, dict, set))