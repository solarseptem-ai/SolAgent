"""Tool registry. 对标 hermes-agent tools/registry.py 自注册 + 工具集分组 + 自动发现。"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from dataclasses import dataclass, field
from typing import Callable

from pydantic import BaseModel

from solagent.agents.tools.defs import ToolDef
from solagent.schema.tools import (
    ToolDefinition,
    ToolListContext,
    ToolParameter,
    ToolParameterType,
)

_logger = logging.getLogger(__name__)

_TOOL_ALIASES: dict[str, str] = {
    "write_file": "write",
    "read_file": "read",
    "edit_file": "edit",
    "list_dir": "ls",
    "list_directory": "ls",
    "search_file": "glob",
    "search_files": "glob",
    "search_content": "grep",
    "run_shell": "shell",
    "run_command": "shell",
    "execute_command": "shell",
    "web_search": "web_search",
    "web_fetch": "web_fetch",
    "remember": "remember",
    "recall": "recall",
    "forget": "forget",
    "ask_user": "clarify",
    "present_file": "present_file",
    "skill_view": "skill_view",
    "subagent": "subagent",
    "get_current_time": "get_current_time",
    "get_token_usage": "get_token_usage",
    "tool_search": "tool_search",
    "apply_patch": "apply_patch",
}


@dataclass
class ToolEntry:
    tool: ToolDef
    toolset: str
    check_fn: Callable[[], bool] | None = None
    requires_env: list[str] = field(default_factory=list)
    priority: int = 0
    source: str = "builtin"


class ToolRegistry:
    """工具注册表 — 支持全局 + Agent 级 ScopedLayers。"""

    def __init__(self):
        self._tools: dict[str, ToolDef] = {}
        self._scopes: dict[str, dict[str, ToolDef]] = {}
        self._entries: list[ToolEntry] = []
        self._scope_entries: dict[str, list[ToolEntry]] = {}

    def register(self, tool: ToolDef, scope: str | None = None) -> None:
        if scope:
            if scope not in self._scopes:
                self._scopes[scope] = {}
            if tool.id in self._scopes[scope]:
                raise ValueError(f"Tool '{tool.id}' already registered in scope '{scope}'")
            self._scopes[scope][tool.id] = tool
        else:
            if tool.id in self._tools:
                raise ValueError(f"Tool '{tool.id}' already registered")
            self._tools[tool.id] = tool

    def register_entry(self, entry: ToolEntry, scope: str | None = None) -> None:
        if scope:
            if scope not in self._scope_entries:
                self._scope_entries[scope] = []
            self._scope_entries[scope].append(entry)
            if scope not in self._scopes:
                self._scopes[scope] = {}
            if entry.tool.id not in self._scopes[scope]:
                self._scopes[scope][entry.tool.id] = entry.tool
        else:
            self._entries.append(entry)
            if entry.tool.id not in self._tools:
                self._tools[entry.tool.id] = entry.tool

    def unregister(self, name: str, scope: str | None = None) -> None:
        if scope:
            if scope in self._scopes:
                self._scopes[scope].pop(name, None)
            if scope in self._scope_entries:
                self._scope_entries[scope] = [
                    e for e in self._scope_entries[scope] if e.tool.id != name
                ]
        else:
            self._tools.pop(name, None)
            self._entries = [e for e in self._entries if e.tool.id != name]

    def get(self, name: str, scope: str | None = None) -> ToolDef:
        if scope and scope in self._scopes and name in self._scopes[scope]:
            return self._scopes[scope][name]
        resolved = name
        if name not in self._tools and name in _TOOL_ALIASES:
            resolved = _TOOL_ALIASES[name]
        if resolved not in self._tools:
            similar = [n for n in self._tools if name.lower() in n.lower()][:5]
            hint = f" Similar: {similar}" if similar else ""
            from solagent.errors.tool import ToolNotFoundError
            raise ToolNotFoundError(name, f"Tool '{name}' not found.{hint}")
        return self._tools[resolved]

    def has(self, name: str, scope: str | None = None) -> bool:
        if scope and scope in self._scopes and name in self._scopes[scope]:
            return True
        if name in self._tools:
            return True
        resolved = _TOOL_ALIASES.get(name, name)
        return resolved in self._tools

    def list(self, scope: str | None = None) -> list[str]:
        names = set(self._tools.keys())
        if scope and scope in self._scopes:
            names.update(self._scopes[scope].keys())
        return list(names)

    def get_definitions(self, scope: str | None = None) -> list[ToolDefinition]:
        result: list[ToolDefinition] = []
        seen: set[str] = set()
        for tools in (self._scopes.get(scope, {}) if scope else {}, self._tools):
            for tool in tools.values():
                if tool.id in seen:
                    continue
                seen.add(tool.id)
                if tool.params_model is BaseModel:
                    _logger.warning("Skipping tool '%s': params_model is BaseModel, not a subclass", tool.id)
                    continue
                schema = tool.params_model.model_json_schema()
                params: list[ToolParameter] = []
                required_fields: list[str] = schema.get("required", [])
                for prop_name, prop_schema in schema.get("properties", {}).items():
                    prop_type = prop_schema.get("type", "string")
                    if prop_type == "array":
                        items = prop_schema.get("items", {})
                        if items.get("type") == "string":
                            tp = ToolParameterType.STRING
                        elif items.get("type") in ("number", "integer"):
                            tp = ToolParameterType.NUMBER
                        else:
                            tp = ToolParameterType.ARRAY
                    else:
                        tp = {
                            "string": ToolParameterType.STRING,
                            "number": ToolParameterType.NUMBER,
                            "integer": ToolParameterType.NUMBER,
                            "boolean": ToolParameterType.BOOLEAN,
                            "object": ToolParameterType.OBJECT,
                        }.get(prop_type, ToolParameterType.STRING)
                    params.append(ToolParameter(
                        name=prop_name,
                        type=tp,
                        description=prop_schema.get("description", prop_schema.get("title", "")),
                        required=prop_name in required_fields,
                    ))
                result.append(ToolDefinition(
                    name=tool.id,
                    description=tool.description,
                    parameters=params,
                ))
        return result

    def clear(self, scope: str | None = None) -> None:
        if scope:
            self._scopes.pop(scope, None)
            self._scope_entries.pop(scope, None)
        else:
            self._tools.clear()
            self._entries.clear()
            self._scopes.clear()
            self._scope_entries.clear()

    def filter(self, active_skills: list[str] | None = None, scope: str | None = None) -> ToolRegistry:
        filtered = ToolRegistry()
        tools_source = self._tools
        if scope and scope in self._scopes:
            tools_source = {**self._tools, **self._scopes[scope]}
        for name, tool in tools_source.items():
            requires = getattr(tool, "requires_skills", ())
            if requires and not set(requires) & set(active_skills or []):
                continue
            filtered._tools[name] = tool
        return filtered

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return self.has(name)

    def resolve(
        self, enabled_toolsets: list[str], ctx: ToolListContext, scope: str | None = None
    ) -> list[ToolEntry]:
        resolved: dict[str, ToolEntry] = {}
        entries = list(self._entries)
        if scope and scope in self._scope_entries:
            entries = entries + self._scope_entries[scope]
        for entry in entries:
            if entry.toolset not in enabled_toolsets:
                continue
            if entry.check_fn is not None and not entry.check_fn():
                continue
            if not entry.tool.should_show(ctx):
                continue
            existing = resolved.get(entry.tool.id)
            if existing is None or entry.priority > existing.priority:
                resolved[entry.tool.id] = entry
        return list(resolved.values())

    def auto_discover(self, *package_paths: str, scope: str | None = None) -> int:
        count = 0
        for package_path in package_paths:
            try:
                package = importlib.import_module(package_path)
            except ImportError:
                _logger.warning("Failed to import package %s", package_path, exc_info=True)
                continue
            if not hasattr(package, "__path__"):
                continue
            for _, module_name, _ in pkgutil.iter_modules(package.__path__, package.__name__ + "."):
                try:
                    mod = importlib.import_module(module_name)
                    for attr_name in dir(mod):
                        attr = getattr(mod, attr_name)
                        if hasattr(attr, "_tool_meta") and isinstance(attr, type):
                            meta = attr._tool_meta
                            self.register_entry(ToolEntry(
                                tool=attr(),
                                toolset=meta["toolset"],
                                priority=meta["priority"],
                                check_fn=meta["check_fn"],
                                requires_env=meta["requires_env"],
                            ), scope=scope)
                            count += 1
                except Exception:
                    _logger.warning("Tool discovery failed for %s", module_name, exc_info=True)
        return count

    def list_toolsets(self) -> list[str]:
        seen = set()
        for entry in self._entries:
            seen.add(entry.toolset)
        for entries in self._scope_entries.values():
            for entry in entries:
                seen.add(entry.toolset)
        return sorted(seen)

    def to_snapshot(self, scope: str | None = None) -> list:
        from solagent.schema.agent import ToolSnapshot
        snapshots = []
        tools_iter = self._tools
        if scope and scope in self._scopes:
            tools_iter = {**self._tools, **self._scopes[scope]}
        for name, tool in tools_iter.items():
            try:
                schema = tool.params_model.model_json_schema() if hasattr(tool.params_model, 'model_json_schema') else {}
            except Exception:
                schema = {}
            snapshots.append(ToolSnapshot(
                name=name,
                description=tool.description,
                parameters_schema=schema,
            ))
        return snapshots

    def restrict(self, scope: str, allow: list[str] | None = None, deny: list[str] | None = None) -> None:
        """限制 scope 内的工具可见性。allow 白名单优先，deny 黑名单。"""
        if scope not in self._scopes:
            return
        if allow is not None:
            self._scopes[scope] = {k: v for k, v in self._scopes[scope].items() if k in allow}
        if deny is not None:
            self._scopes[scope] = {k: v for k, v in self._scopes[scope].items() if k not in deny}

    @property
    def entries(self) -> list[ToolEntry]:
        return list(self._entries)

    def scope_entries(self, scope: str) -> list[ToolEntry]:
        return list(self._scope_entries.get(scope, []))