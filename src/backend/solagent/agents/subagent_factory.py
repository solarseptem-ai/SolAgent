"""SubagentFactory — 子代理构造统一入口。纯函数式工厂，无状态，并发安全。

为 SubagentTool 和多 Agent 编排提供共享的子代理构造逻辑：
- 复用父 provider（同一家 LLM）
- 收窄 tools（按 tool_names 过滤，默认最小集）
- 独立 permission/hitl/guard（子代理默认更受限）
- 独立 EventBus / EventScope
"""
from __future__ import annotations

from solagent.agents.base import AgentContext

# 注意：AgentBuilder 在 create() 函数内延迟 import，避免与 builder.py 形成循环导入
from solagent.agents.hitl import HITLManager
from solagent.agents.hooks import AgentHooks
from solagent.agents.middleware.chain import MiddlewareChain
from solagent.agents.tools.guard import GuardLevel, ToolGuard
from solagent.agents.tools.permission import PermissionEngine, PermissionMode
from solagent.agents.tools.registry import ToolRegistry
from solagent.schema.agent import AgentMode

_DEFAULT_TOOLS = ["read_file", "list_dir", "grep", "glob"]


async def create(
    parent_ctx: AgentContext,
    task: str,
    tool_names: list[str] | None = None,
    permission_mode: PermissionMode | None = None,
    mode: AgentMode = AgentMode.REACT,
    max_iterations: int = 5,
) -> AgentBuilder:
    """构造子 AgentBuilder。父 ctx 不被修改。

    Args:
        parent_ctx: 父 AgentContext，子代理复用其 provider
        task: 子代理任务（仅用于日志，不注入 messages）
        tool_names: 子代理可用工具名列表；None 用默认最小集
        permission_mode: 子代理权限模式；None 默认 ACCEPT_EDITS
        mode: 子代理模式，默认 REACT
        max_iterations: 子代理最大迭代，默认 5（比父更保守）

    Returns:
        配置好的 AgentBuilder，调用方负责 run()
    """
    from solagent.agents.builder import AgentBuilder

    current_depth = parent_ctx.metadata.get("subagent_depth", 0)
    child_depth = current_depth + 1

    builder = AgentBuilder()

    child_config = parent_ctx.config.model_copy(update={
        "name": f"{parent_ctx.config.name}_subagent",
        "mode": mode,
        "max_iterations": max_iterations,
        "tools": [],
        "skills": [],
        "middleware": [],
        "guardrails": [],
    })
    builder.with_config(child_config)

    builder.with_provider(parent_ctx.provider)

    child_tools = _build_child_tools(parent_ctx, tool_names)
    builder.with_tools(child_tools)

    builder.with_hooks(AgentHooks())
    builder.with_middleware(MiddlewareChain())

    child_permission = PermissionEngine(mode=permission_mode or PermissionMode.ACCEPT_EDITS)
    builder.with_permission(child_permission)

    child_hitl = HITLManager()
    if parent_ctx.hitl is None:
        child_hitl.disable()
    else:
        child_hitl.enable()
    builder.with_hitl(child_hitl)

    child_guard = ToolGuard(level=GuardLevel.AUTO)
    builder.with_guard(child_guard)

    if parent_ctx.plugin_ctx is not None:
        try:
            child_plugin_ctx = parent_ctx.plugin_ctx.isolate()
            builder._cordis_ctx = child_plugin_ctx
        except Exception:
            pass

    builder._metadata = {"subagent_depth": child_depth, "parent_session_id": parent_ctx.metadata.get("session_id", "")}

    return builder


def _build_child_tools(parent_ctx: AgentContext, tool_names: list[str] | None) -> ToolRegistry:
    """从父 tools 收窄出子 tools。tool_names 为 None 时用默认最小集。"""
    names = tool_names if tool_names else _DEFAULT_TOOLS
    child = ToolRegistry()
    for name in names:
        if parent_ctx.tools.has(name):
            child.register(parent_ctx.tools.get(name))
    return child
