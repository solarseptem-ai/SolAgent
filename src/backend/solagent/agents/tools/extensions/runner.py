"""Extension runner. 对标 pi ExtensionRunner：activate/deactivate 生命周期。"""
from dataclasses import dataclass, field
from typing import Protocol

from solagent.agents.tools.registry import ToolEntry, ToolRegistry


class ExtensionAPI(Protocol):
    def register_tool(self, tool) -> None: ...
    def unregister_tool(self, tool_id: str) -> None: ...


@dataclass
class ExtensionContext:
    api: ExtensionAPI
    config: dict = field(default_factory=dict)


class Extension(Protocol):
    name: str
    version: str
    async def activate(self, ctx: ExtensionContext) -> None: ...
    async def deactivate(self) -> None: ...


class ExtensionRunner:
    def __init__(self, registry: ToolRegistry):
        self._registry = registry
        self._extensions: dict[str, Extension] = {}
        self._tools: dict[str, list[str]] = {}

    async def load(self, ext: Extension) -> None:
        api = self._make_api(ext.name)
        ctx = ExtensionContext(api=api, config={})
        await ext.activate(ctx)
        self._extensions[ext.name] = ext

    async def unload(self, name: str) -> None:
        ext = self._extensions.pop(name, None)
        if ext:
            for tool_id in self._tools.pop(name, []):
                self._registry.unregister(tool_id)
            await ext.deactivate()

    async def load_all(self, *extensions: Extension) -> None:
        for ext in extensions:
            await self.load(ext)

    def _make_api(self, ext_name: str) -> ExtensionAPI:
        runner = self
        class _API:
            def register_tool(self, tool):
                runner._registry.register_entry(ToolEntry(
                    tool=tool, toolset="extension", source="extension", priority=100,
                ))
                runner._tools.setdefault(ext_name, []).append(tool.id)
            def unregister_tool(self, tool_id):
                runner._registry.unregister(tool_id)
        return _API()
