"""预设挂载模块。

将 AgentPreset 中的配置（人格、工具列表、提示词等）注入到 Cordis 上下文中，
使 Agent 在执行时能够读取这些预设值。支持多个预设的层级组合（scope chain）。
"""

from __future__ import annotations

from collections.abc import Callable

from solagent.cordis import Context
from solagent.presets.types import AgentPreset


def mount_preset(ctx: Context, preset: AgentPreset) -> Callable[[], None]:
    """将单个预设挂载到目标 Cordis 上下文中，返回一个清理函数用于卸载。

    参数:
        ctx: 目标 Cordis 上下文。
        preset: 需要挂载的预设对象。

    返回:
        调用后可移除该预设所注入的所有值的清理函数（disposer）。
    """
    """Mount a preset into a target context scope. Returns a disposer."""
    disposers: list[Callable[[], None]] = []

    if preset.persona:
        disposers.append(ctx.provide("preset_persona", preset.persona))

    if preset.tools:
        disposers.append(ctx.provide("preset_tools", preset.tools))

    if preset.prompts:
        disposers.append(ctx.provide("preset_prompts", preset.prompts))

    disposers.append(ctx.provide("preset_id", preset.id))
    disposers.append(ctx.provide("preset_name", preset.name))

    def _dispose() -> None:
        for d in reversed(disposers):
            try:
                d()
            except Exception:
                pass

    return _dispose


def compose_presets(base_ctx: Context, presets: list[AgentPreset]) -> Context:
    """将多个预设组合为 Cordis 作用域链，后挂载的预设优先级更高。

    参数:
        base_ctx: 基础 Cordis 上下文。
        presets: 需要依次挂载的预设列表。

    返回:
        最内层（最后挂载）的 Cordis 上下文作用域。
    """
    scope = base_ctx
    for preset in presets:
        scope = scope.extend()
        mount_preset(scope, preset)
    return scope