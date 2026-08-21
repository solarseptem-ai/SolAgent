"""注册表服务，管理插件运行时记录和 Fiber 创建。

RegistryService 负责解析各种形式的插件定义（函数、类、字典等），
为每个唯一的回调创建共享的 PluginRuntime 记录，并管理该插件的所有 Fiber 实例。
同时提供 @Inject 装饰器用于声明服务依赖。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from typing import Any

from solagent.cordis.fiber import Fiber
from solagent.cordis.symbols import CHECK_PROTO, METADATA

Plugin = Callable[..., Any]


class PluginRuntime:
    """插件运行时记录，保存插件的元数据和所有活跃的 Fiber 实例。

    同一个插件回调的所有 Fiber 实例共享一个 PluginRuntime，
    便于集中管理和状态追踪。

    属性说明：
        name: 插件名称。
        callback: 插件的可执行回调。
        fibers: 该插件的所有活跃 Fiber 列表。
        Config: 插件的配置模型或验证器。
    """

    __slots__ = ("name", "callback", "fibers", "Config")

    def __init__(self, name: str | None, callback: Callable[..., Any]) -> None:
        self.name = name
        self.callback = callback
        self.fibers: list[Fiber] = []
        self.Config: Any = None


class Inject:
    """依赖注入装饰器，用于在类或方法上声明服务依赖。

    类级别使用：@Inject("logger") → 设置 cls.inject["logger"] = config。
    方法级别使用：@Inject("logger") → 在元数据中存储依赖信息供 initHooks 使用。
    """

    def __init__(self, name: str, config: Any = None) -> None:
        self._name = name
        self._config = config

    def __call__(self, target: Any) -> Any:
        """将依赖声明应用到目标类或方法上。"""
        if isinstance(target, type):
            if not hasattr(target, "inject"):
                setattr(target, "inject", {})
            target.inject[self._name] = self._config
            return target
        else:
            meta = getattr(target, METADATA, None) or {}
            inject = meta.get("inject", {})
            inject[self._name] = self._config
            meta["inject"] = inject
            setattr(target, METADATA, meta)
            return target

    @staticmethod
    def resolve(inject: Any, result: dict[str, Any] | None = None) -> dict[str, Any]:
        """将各种形式的 inject 元数据（数组、对象、继承链）解析为统一的字典。

        Args:
            inject: inject 元数据，可能是 list、dict 或 None。
            result: 用于递归合并的初始结果字典。

        Returns:
            解析后的 {服务名: 配置} 字典。
        """
        if result is None:
            result = {}
        if inject is None:
            return result
        if isinstance(inject, list):
            for name in inject:
                result[name] = None
            return result
        if isinstance(inject, dict):
            if inject.get(CHECK_PROTO):
                Inject.resolve(inject.get("__parent__"), result)
            for name, value in inject.items():
                if name != CHECK_PROTO and name != "__parent__":
                    result[name] = value if value is not None else None
            return result
        return result


class RegistryService:
    """插件注册表，负责解析插件形态、创建 Fiber 和管理运行时记录。

    核心职责：
        - resolve: 从各种插件定义中提取可执行回调。
        - plugin: 创建 Fiber 并关联到 PluginRuntime。
        - 维护 callback -> PluginRuntime 的映射，实现运行时复用。
    """

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self._counter = 0
        self._runtimes: dict[int, PluginRuntime] = {}  # id(callback) -> runtime

    @property
    def counter(self) -> int:
        """自增计数器，用于为每个新 Fiber 分配唯一 UID。"""
        self._counter += 1
        return self._counter

    @property
    def size(self) -> int:
        """返回当前注册表中不同插件回调的数量。"""
        return len(self._runtimes)

    def resolve(self, plugin: Any) -> Callable[..., Any] | None:
        """从插件定义中提取可执行回调。

        支持的插件形态：
            - 普通函数或类（callable）。
            - 具有 apply 属性的对象。
            - 包含 "apply" 键的字典。

        Args:
            plugin: 插件定义。

        Returns:
            可执行回调，若无法解析则返回 None。
        """
        if callable(plugin) and not hasattr(plugin, "apply"):
            return plugin
        if hasattr(plugin, "apply"):
            return plugin.apply
        if isinstance(plugin, dict) and "apply" in plugin:
            return plugin["apply"]
        return None

    def _key(self, callback: Callable[..., Any]) -> int:
        """计算回调的唯一键，用于运行时复用。优先使用 __func__ 的 id。"""
        return id(getattr(callback, "__func__", callback))

    def get(self, plugin: Any) -> PluginRuntime | None:
        """获取插件对应的 PluginRuntime 记录。"""
        callback = self.resolve(plugin)
        return self._runtimes.get(self._key(callback)) if callback else None

    def has(self, plugin: Any) -> bool:
        """判断插件是否已在注册表中。"""
        callback = self.resolve(plugin)
        return self._key(callback) in self._runtimes if callback else False

    def delete(self, plugin: Any) -> PluginRuntime | None:
        """从注册表中移除插件，并异步释放其所有 Fiber。

        Args:
            plugin: 插件定义。

        Returns:
            被移除的 PluginRuntime，若不存在则返回 None。
        """
        callback = self.resolve(plugin)
        if callback is None:
            return None
        runtime = self._runtimes.pop(self._key(callback), None)
        if runtime:
            for fiber in list(runtime.fibers):
                asyncio.ensure_future(fiber.dispose())
        return runtime

    def keys(self) -> Iterator[int]:
        """返回所有运行时键的迭代器。"""
        return iter(self._runtimes.keys())

    def values(self) -> Iterator[PluginRuntime]:
        """返回所有 PluginRuntime 的迭代器。"""
        return iter(self._runtimes.values())

    def entries(self) -> Iterator[tuple[int, PluginRuntime]]:
        """返回所有 (键, PluginRuntime) 元组的迭代器。"""
        return iter(self._runtimes.items())

    def inject(self, inject: dict[str, str], callback: Callable[..., Any]) -> Fiber:
        """基于依赖映射创建插件 Fiber。

        Args:
            inject: 依赖名称映射字典。
            callback: 插件回调函数。

        Returns:
            创建的 Fiber 实例。
        """
        deps = {v: None for v in inject.values()}
        return self.plugin({"apply": callback, "inject": deps})

    def plugin(self, plugin: Any, config: Any = None) -> Fiber:
        """注册插件并创建其 Fiber 实例。

        流程：
            1. 解析插件回调。
            2. 查找或创建 PluginRuntime 记录。
            3. 解析 inject 依赖声明。
            4. 创建 Fiber 并触发依赖检查。

        Args:
            plugin: 插件定义。
            config: 插件配置。

        Returns:
            创建的 Fiber 实例。

        Raises:
            TypeError: 若插件定义无效。
        """
        callback = self.resolve(plugin)
        if callback is None:
            raise TypeError(f"invalid plugin: {plugin}")

        key = self._key(callback)
        runtime = self._runtimes.get(key)
        if runtime is None:
            # 提取插件名称
            name = getattr(plugin, "name", None)
            if name is None and isinstance(plugin, dict):
                name = plugin.get("name")
            if name is None and callable(plugin) and not isinstance(plugin, type):
                name = getattr(plugin, "__name__", None)
            if name == "apply":
                name = None
            # 提取配置模型
            if isinstance(plugin, dict):
                runtime_config = plugin.get("Config")
            else:
                runtime_config = getattr(plugin, "Config", None)
            runtime = PluginRuntime(name, callback)
            runtime.Config = runtime_config
            self._runtimes[key] = runtime

        # 解析依赖注入声明
        inject = None
        if isinstance(plugin, dict):
            inject = plugin.get("inject")
        else:
            inject = getattr(plugin, "inject", None)
        inject = Inject.resolve(inject) if inject else {}

        fiber = Fiber(
            self.ctx,
            config=config,
            inject=inject,
            uid=self.counter,
            runtime=runtime,
            callback=callback,
        )
        runtime.fibers.append(fiber)

        # 初始依赖检查和状态刷新
        fiber._check_all_deps()
        fiber._refresh()

        return fiber