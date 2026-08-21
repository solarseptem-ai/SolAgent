"""事件总线服务，支持 5 种分发模式、内部事件钩子和基于类型的事件。

EventsService 是 Cordis 框架的中央事件总线，支持字符串事件和类型事件两种注册方式。
提供 emit（同步广播）、parallel（并发执行）、serial（顺序执行）、bail（短路返回）、
waterfall（值传递）五种分发模式，满足不同场景下的事件处理需求。
同时支持与外部 EventBus 的桥接，实现跨系统的事件转发。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from solagent.cordis.utils import is_bailed
from solagent.plugins import PluginEvent as _PluginEvent

_logger = logging.getLogger(__name__)

# 事件监听器类型别名
Listener = Callable[..., Any]


class Hook:
    """事件钩子封装，保存监听器回调及其注册时的元数据。

    属性说明：
        ctx: 注册钩子的上下文。
        callback: 监听器回调函数。
        prepend: 是否为前置钩子（排在队列前面）。
        global_: 是否为全局监听器。
        mode: 分发模式（emit、parallel、serial、bail、waterfall）。
    """
    __slots__ = ("ctx", "callback", "prepend", "global_", "mode")

    def __init__(self, ctx: Any, callback: Listener, prepend: bool = False, global_: bool = False, mode: str = "emit") -> None:
        self.ctx = ctx
        self.callback = callback
        self.prepend = prepend
        self.global_ = global_
        self.mode = mode


class EventsService:
    """中央事件总线，支持字符串事件、类型事件和外部 EventBus 桥接。

    五种分发模式：
        - emit: 同步广播，不等待监听器完成，不收集返回值。
        - parallel: 并发执行所有异步监听器，等待全部完成后返回。
        - serial: 顺序执行监听器，任一监听器返回 bail 值则提前终止。
        - bail: 顺序执行监听器，任一监听器返回 bail 值则立即返回该值。
        - waterfall: 顺序执行监听器，将上一个监听器的返回值传递给下一个。
    """

    def __init__(self) -> None:
        self._hooks: dict[str, list[Hook]] = {}       # 字符串事件 -> 钩子列表
        self._type_hooks: dict[type, list[Hook]] = {}  # 类型事件 -> 钩子列表
        self.event_bus: Any = None  # 外部事件总线桥接

    def _get_hooks(self, name: str) -> list[Hook]:
        """获取指定字符串事件的钩子列表，不存在则自动创建。"""
        return self._hooks.setdefault(name, [])

    def _get_type_hooks(self, event_type: type) -> list[Hook]:
        """获取指定类型事件的钩子列表，不存在则自动创建。"""
        return self._type_hooks.setdefault(event_type, [])

    def on(self, name: str | type, listener: Listener, prepend: bool = False, _global: bool = False, mode: str = "emit") -> Callable[[], None]:
        """注册事件监听器，返回用于注销的函数。

        支持字符串事件和类型事件两种方式。对于字符串事件，会先触发 internal/listener
        内部钩子，允许其他组件拦截或修改监听器注册行为。

        Args:
            name: 事件名称（字符串）或事件类型（类）。
            listener: 监听器回调函数。
            prepend: 为 True 时将监听器插入队列头部。
            _global: 标记是否为全局监听器。
            mode: 分发模式。

        Returns:
            调用后可注销该监听器的函数。
        """
        if isinstance(name, type):
            hooks = self._get_type_hooks(name)
            hook = Hook(ctx=None, callback=listener, prepend=prepend, global_=_global, mode=mode)
            if prepend:
                hooks.insert(0, hook)
            else:
                hooks.append(hook)

            def _off() -> None:
                try:
                    hooks.remove(hook)
                except ValueError:
                    pass

            return _off

        # 触发内部钩子，允许拦截监听器注册
        result = self.bail("internal/listener", name, listener, prepend)
        if result is not None:
            return result

        hooks = self._get_hooks(name)
        hook = Hook(ctx=None, callback=listener, prepend=prepend, global_=_global)
        if prepend:
            hooks.insert(0, hook)
        else:
            hooks.append(hook)

        def _off() -> None:
            try:
                hooks.remove(hook)
            except ValueError:
                pass

        return _off

    def once(self, name: str | type, listener: Listener, prepend: bool = False) -> Callable[[], None]:
        """注册一次性事件监听器，触发后自动注销。

        Args:
            name: 事件名称或类型。
            listener: 监听器回调函数。
            prepend: 是否前置插入。

        Returns:
            注销函数（也可用于提前手动注销）。
        """
        fired = False

        def _once(*args: Any, **kwargs: Any) -> Any:
            nonlocal fired
            if fired:
                return None
            fired = True
            _off()
            return listener(*args, **kwargs)

        _off = self.on(name, _once, prepend=prepend)
        return _off

    def _dispatch(self, mode: str, name: str, args: tuple[Any, ...]) -> list[Hook]:
        """内部调度准备：触发 internal/dispatch 钩子，返回目标事件的监听器副本。"""
        if not name.startswith("internal/"):
            try:
                self.emit("internal/dispatch", mode, name, list(args), None)
            except Exception:
                pass
        return list(self._hooks.get(name, []))

    def _dispatch_type(self, event: Any) -> list[Hook]:
        """根据事件实例的类型获取对应的监听器列表。"""
        return list(self._type_hooks.get(type(event), []))

    def _forward_to_event_bus(self, event: Any) -> None:
        """将类型事件转发到外部事件总线（若已配置桥接）。"""
        if self.event_bus is not None:
            try:
                self.event_bus.emit(event)
            except Exception:
                pass

    # ---- 字符串事件分发 ----

    def emit(self, name: str, *args: Any) -> None:
        """同步广播模式：逐个调用监听器，不等待异步结果，不收集返回值。

        若事件名为字符串，使用字符串分发；否则使用类型分发。
        """
        if isinstance(name, str):
            for hook in self._dispatch("emit", name, args):
                try:
                    result = hook.callback(*args)
                    if asyncio.iscoroutine(result):
                        pass  # emit 模式不等待协程
                except Exception:
                    _logger.warning("listener for %s raised", name, exc_info=True)
        else:
            self._emit_type(name)

    async def parallel(self, name: str, *args: Any) -> None:
        """并发模式：并行执行所有返回协程的监听器，等待全部完成后返回。

        若任一监听器抛出异常，将所有异常打包为 ExceptionGroup 抛出。
        """
        tasks = []
        for hook in self._dispatch("parallel", name, args):
            try:
                result = hook.callback(*args)
                if asyncio.iscoroutine(result):
                    tasks.append(result)
            except Exception:
                _logger.warning("listener for %s raised", name, exc_info=True)
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            errors = [e for e in results if isinstance(e, Exception)]
            if errors:
                raise ExceptionGroup(f"{len(errors)} listener(s) failed for '{name}'", errors)

    async def serial(self, name: str, *args: Any) -> Any:
        """串行模式：顺序执行监听器，若任一监听器返回 bail 值则提前终止。

        Args:
            name: 事件名称或类型。
            *args: 传递给监听器的参数。

        Returns:
            第一个返回 bail 值的监听器结果，或 None。
        """
        if isinstance(name, str):
            for hook in self._dispatch("serial", name, args):
                try:
                    result = hook.callback(*args)
                    if asyncio.iscoroutine(result):
                        result = await result
                    if is_bailed(result):
                        return result
                except Exception:
                    _logger.warning("listener for %s raised", name, exc_info=True)
            return None
        else:
            return await self._serial_type(name)

    def bail(self, name: str, *args: Any) -> Any:
        """短路模式：顺序执行监听器，第一个返回 bail 值的监听器结果立即返回。

        与 serial 的区别在于 bail 在同步上下文中执行，不等待协程。
        """
        for hook in self._dispatch("bail", name, args):
            try:
                result = hook.callback(*args)
                if is_bailed(result):
                    return result
            except Exception:
                _logger.warning("listener for %s raised", name, exc_info=True)
        return None

    async def waterfall(self, name: str, value: Any = None, *args: Any) -> Any:
        """瀑布模式：顺序执行监听器，将上一个监听器的返回值传递给下一个。

        任一监听器返回非 None 值时，该值会作为后续监听器调用的第一个参数。
        适用于需要逐步修改或累积结果的场景。
        """
        if isinstance(name, str):
            for hook in self._dispatch("waterfall", name, (value, *args)):
                try:
                    result = hook.callback(value, *args)
                    if asyncio.iscoroutine(result):
                        result = await result
                    if result is not None:
                        value = result
                except Exception:
                    _logger.warning("listener for %s raised", name, exc_info=True)
            return value
        else:
            return self._waterfall_type(name)

    def waterfall_next(self, name: str, *args: Any, next_fn: Callable[[], Any] | None = None) -> Any:
        """支持 next 回调的瀑布模式，监听器可通过调用 next 决定是否继续传递。

        适用于需要显式控制是否继续执行后续监听器的场景。
        """
        cbs = self._dispatch("waterfall", name, args)

        def _chain(remaining: list[Hook]) -> Any:
            if not remaining:
                if next_fn is not None:
                    return next_fn()
                return None
            hook = remaining[0]

            def _next() -> Any:
                return _chain(remaining[1:])

            try:
                return hook.callback(*args, _next)
            except Exception:
                _logger.warning("listener for %s raised", name, exc_info=True)
                return _next()

        return _chain(cbs)

    def clear(self) -> None:
        """清空所有字符串事件和类型事件的监听器。"""
        self._hooks.clear()
        self._type_hooks.clear()

    def remove_all_listeners(self, name: str | None = None) -> None:
        """移除指定事件的所有监听器，或全部事件的监听器（name 为 None 时）。"""
        if name is None:
            self._hooks.clear()
            self._type_hooks.clear()
        else:
            self._hooks.pop(name, None)

    def listener_count(self, name: str) -> int:
        """返回指定字符串事件的监听器数量。"""
        return len(self._hooks.get(name, []))

    def event_names(self) -> list[str]:
        """返回当前注册了监听器的所有字符串事件名称列表。"""
        return [name for name, hooks in self._hooks.items() if hooks]

    # ---- 类型事件分发（PluginEvent 兼容性） ----

    def _emit_type(self, event: Any) -> None:
        """类型事件的 emit 分发，将异步结果包装为后台任务。"""
        for hook in self._dispatch_type(event):
            if hook.mode != "emit":
                continue
            try:
                result = hook.callback(event)
                if asyncio.iscoroutine(result):
                    asyncio.create_task(result)
            except Exception:
                _logger.warning("type listener raised", exc_info=True)
        self._forward_to_event_bus(event)

    async def _parallel_type(self, event: Any) -> None:
        """类型事件的 parallel 分发。"""
        tasks = []
        for hook in self._dispatch_type(event):
            if hook.mode != "parallel":
                continue
            try:
                result = hook.callback(event)
                if asyncio.iscoroutine(result):
                    tasks.append(result)
            except Exception:
                _logger.warning("type listener raised", exc_info=True)
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            errors = [e for e in results if isinstance(e, Exception)]
            if errors:
                raise ExceptionGroup("type event dispatch errors", errors)

    async def _serial_type(self, event: Any) -> Any:
        """类型事件的 serial 分发。"""
        for hook in self._dispatch_type(event):
            if hook.mode != "serial":
                continue
            try:
                result = hook.callback(event)
                if asyncio.iscoroutine(result):
                    result = await result
                if is_bailed(result):
                    return result
            except Exception:
                _logger.warning("type listener raised", exc_info=True)
        return None

    def _waterfall_type(self, event: Any) -> Any:
        """类型事件的 waterfall 分发。"""
        hooks = [h for h in self._dispatch_type(event) if h.mode == "waterfall"]
        if not hooks:
            return None

        def _run(index: int, evt: Any) -> Any:
            if index >= len(hooks):
                return None
            hook = hooks[index]
            try:
                return hook.callback(evt, lambda: _run(index + 1, evt))
            except Exception:
                _logger.warning("type waterfall listener raised", exc_info=True)
                return _run(index + 1, evt)

        return _run(0, event)


# ---- Agent 生命周期事件（从 plugins/agent.py 迁移） ----

class BeforeAgentLoopEvent(_PluginEvent):
    """Agent 执行循环开始前触发的事件。"""
    messages: list = []
    config: Any = None


class AfterAgentLoopEvent(_PluginEvent):
    """Agent 执行循环结束后触发的事件。"""
    messages: list = []
    result: Any = None


class AgentLifecycleEvent(_PluginEvent):
    """Agent 生命周期状态变更事件。"""
    event_type: str = ""
    data: dict = {}