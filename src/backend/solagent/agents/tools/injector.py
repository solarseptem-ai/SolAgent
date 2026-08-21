"""工具注入器。对标 hermes-agent tool_search + pi deferred-tools 渐进式披露。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from solagent.agents.tools.registry import ToolEntry
from solagent.schema.tools import ToolListContext

if TYPE_CHECKING:
    from solagent.agents.tools.registry import ToolRegistry


@dataclass
class ToolDisclosureConfig:
    mode: str = "threshold"
    threshold_percent: float = 10.0
    core_toolsets: list[str] = field(default_factory=lambda: ["core"])
    max_deferred_tools: int = 50


@dataclass
class ToolInjection:
    immediate: list[ToolEntry] = field(default_factory=list)
    deferred: list[ToolEntry] = field(default_factory=list)


class ToolInjector:
    def __init__(self, registry: ToolRegistry, config: ToolDisclosureConfig | None = None):
        self._registry = registry
        self._config = config or ToolDisclosureConfig()

    def prepare(
        self, enabled_toolsets: list[str], ctx: ToolListContext
    ) -> ToolInjection:
        all_entries = self._registry.resolve(enabled_toolsets, ctx)

        core = [e for e in all_entries if e.toolset in self._config.core_toolsets]
        non_core = [e for e in all_entries if e.toolset not in self._config.core_toolsets]

        if self._config.mode == "immediate":
            return ToolInjection(immediate=all_entries, deferred=[])

        if self._config.mode == "threshold":
            core_tokens = self._estimate_tokens([e.tool for e in core])
            total_tokens = core_tokens + self._estimate_tokens([e.tool for e in non_core])
            ctx_window = ctx.token_budget

            if total_tokens / ctx_window < self._config.threshold_percent / 100:
                return ToolInjection(immediate=all_entries, deferred=[])

            return ToolInjection(
                immediate=core,
                deferred=non_core[:self._config.max_deferred_tools],
            )

        return ToolInjection(
            immediate=core,
            deferred=non_core[:self._config.max_deferred_tools],
        )

    def inject_to_request(
        self, injection: ToolInjection, request: dict
    ) -> dict:
        tools = []
        for entry in injection.immediate:
            tool = entry.tool
            tools.append({
                "type": "function",
                "function": {
                    "name": tool.id,
                    "description": tool.description,
                    "parameters": tool.json_schema,
                },
            })

        if injection.deferred:
            tools.append(self._make_tool_search_bridge(injection.deferred))

        if tools:
            request["tools"] = tools
        return request

    def _estimate_tokens(self, tools: list) -> int:
        total_chars = sum(
            len(json.dumps(t.json_schema)) + len(t.description)
            for t in tools
        )
        return total_chars // 4

    def _make_tool_search_bridge(self, deferred: list[ToolEntry]) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "tool_search",
                "description": (
                    "Search for available tools by keyword. "
                    "Use this to discover tools not listed above. "
                    "After finding a tool, call it directly by name."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Keyword to search for in tool names and descriptions",
                        }
                    },
                    "required": ["query"],
                },
            },
        }