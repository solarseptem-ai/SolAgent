"""插件管理器服务，支持批量插件注册、拓扑排序启动和停止。

本模块将传统的 PluginManager 重构为 Cordis Service，利用 Cordis 的依赖注入
和 Fiber 生命周期管理能力，实现插件的自动解析、拓扑排序启动和优雅停止。
"""

from __future__ import annotations

import asyncio
from typing import Any

from solagent.cordis.service import Service


class PluginManagerService(Service):
    """批量插件管理器，负责插件的注册、按依赖顺序启动、停止和注销。

    通过拓扑排序确保插件按依赖关系顺序启动（被依赖的先启动），
    停止时按逆序执行，保证依赖项在依赖方停止后才释放。
    """

    name = "plugin_manager"

    def __init__(self, ctx: Any) -> None:
        super().__init__(ctx, "plugin_manager")
        self._plugins: dict[str, Any] = {}       # name -> fiber
        self._plugins_cls: dict[str, type] = {}  # name -> plugin class

    def register(self, plugin_cls: type, config: dict[str, Any] | None = None) -> Any:
        """注册一个插件类，创建对应的 Cordis Fiber 并返回。

        自动提取插件的 inject 依赖声明，将其转换为 Cordis 可识别的格式。

        Args:
            plugin_cls: 插件类，需具有可选的 name、inject、start、stop 属性/方法。
            config: 插件配置字典。

        Returns:
            创建的 Cordis Fiber 实例。
        """
        name = getattr(plugin_cls, "name", None) or plugin_cls.__name__

        async def _plugin(ctx: Any, _config: Any) -> None:
            """插件的 Cordis 入口函数，负责实例化插件并管理生命周期。"""
            instance = plugin_cls(ctx)
            instance.ctx = ctx
            if hasattr(instance, "start"):
                await instance.start()
            # 注册停止时的清理副作用
            ctx.effect(lambda: asyncio.ensure_future(instance.stop()) if hasattr(instance, "stop") else None)
            return instance

        # 提取并规范化 inject 依赖声明
        inject = getattr(plugin_cls, "inject", {})
        if isinstance(inject, list):
            inject = {k: None for k in inject}
        _plugin.__dict__["inject"] = inject

        # 通过 Cordis Registry 创建 Fiber
        fiber = self.ctx.registry.plugin({"apply": _plugin, "inject": inject, "name": name}, config or {})
        child = self.ctx.extend()
        child.fiber = fiber
        fiber.ctx = child
        self._plugins[name] = fiber
        self._plugins_cls[name] = plugin_cls
        return fiber

    async def start_all(self) -> None:
        """按依赖拓扑顺序启动所有已注册的插件。

        使用拓扑排序确保被依赖的插件先于依赖方启动，
        单个插件启动失败不影响其他插件的启动流程。
        """
        ordered = self._topological_sort()
        for name in ordered:
            if name in self._plugins:
                try:
                    await self._plugins[name].await_start()
                except Exception:
                    pass

    async def stop_all(self) -> None:
        """按注册逆序停止所有已注册的插件。

        逆序停止确保依赖方先停止，被依赖方后释放，避免悬空引用。
        """
        for name in reversed(list(self._plugins.keys())):
            try:
                await self._plugins[name].dispose()
            except Exception:
                pass

    async def unregister(self, name: str) -> None:
        """注销指定名称的插件，释放其 Fiber 和相关资源。

        Args:
            name: 插件名称。

        Raises:
            KeyError: 若插件未注册。
        """
        if name not in self._plugins:
            raise KeyError(f"Plugin '{name}' not registered")
        fiber = self._plugins.pop(name)
        self._plugins_cls.pop(name, None)
        await fiber.dispose()

    def list(self) -> list[str]:
        """返回所有已注册插件的名称列表。"""
        return list(self._plugins.keys())

    def get(self, name: str) -> Any:
        """获取指定名称插件对应的 Fiber 实例。"""
        return self._plugins.get(name)

    def has(self, name: str) -> bool:
        """判断指定名称的插件是否已注册。"""
        return name in self._plugins

    def _topological_sort(self) -> list[str]:
        """基于插件 inject 依赖关系进行拓扑排序。

        构建入度表和依赖图后使用 Kahn 算法，返回按依赖顺序排列的插件名称列表。
        入度为 0 的插件（无依赖）排在前面。

        Returns:
            拓扑排序后的插件名称列表。
        """
        in_degree: dict[str, int] = {}
        deps: dict[str, list[str]] = {}

        for name, plugin_cls in self._plugins_cls.items():
            in_degree.setdefault(name, 0)
            inject = getattr(plugin_cls, "inject", {})
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
            for name2, dep_list in deps.items():
                if node in dep_list:
                    in_degree[name2] -= 1
                    if in_degree[name2] == 0:
                        queue.append(name2)

        return result