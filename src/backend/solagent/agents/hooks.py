"""Agent 生命周期钩子系统。

提供 Agent 执行各阶段（循环前/后、工具调用前/后、出错时）的钩子注册与触发机制。
支持严格模式（strict）下钩子异常会中断执行，以及内置的错误归一化和取消清理钩子。
适用于需要在 Agent 生命周期中插入自定义逻辑（如日志、监控、审计）的场景。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from solagent.errors.classifier import classify_error, extract_error_code, extract_status_code

# 钩子函数签名：接收一个上下文字典，执行异步操作
HookFn = Callable[[dict], Awaitable[None]]
_logger = logging.getLogger("solagent.hooks")


class AgentHooks:
    """Agent 生命周期钩子注册表。

    在 Agent 执行的关键节点触发已注册的钩子函数，支持错误隔离和严格模式。

    属性:
        before_loop: Agent 主循环开始前触发的钩子列表。
        after_loop: Agent 主循环结束后触发的钩子列表。
        before_tool_call: 每次工具调用前触发的钩子列表。
        after_tool_call: 每次工具调用后触发的钩子列表。
        on_error: 发生错误时触发的钩子列表。
    """

    def __init__(self):
        self.before_loop: list[HookFn] = []
        self.after_loop: list[HookFn] = []
        self.before_tool_call: list[HookFn] = []
        self.after_tool_call: list[HookFn] = []
        self.on_error: list[HookFn] = []
        self._strict: bool = False

    def set_strict(self, strict: bool = True) -> None:
        """设置严格模式。启用后，任一钩子抛出异常都会中断后续钩子及 Agent 执行。"""
        self._strict = strict

    async def trigger(self, hooks: list[HookFn], context: dict) -> None:
        """顺序触发指定钩子列表中的每个钩子函数。

        参数:
            hooks: 要触发的钩子函数列表。
            context: 传递给钩子的上下文字典，可包含配置、错误、工具调用等信息。
        """
        for hook in hooks:
            try:
                await hook(context)
            except Exception as e:
                _logger.error("Hook %s failed: %s", hook.__name__ if hasattr(hook, '__name__') else hook, e)
                if self._strict:
                    raise


async def _error_normalize(context: dict) -> None:
    """内置错误归一化钩子：将异常对象转换为结构化的错误信息并写回 context。

    会向 context 中注入 error_type、error_class、error_retriable、error_status_code、
    error_code 等字段，便于上层统一处理错误。
    """
    error = context.get("error")
    if error is None:
        return
    if not isinstance(error, Exception):
        context["error_type"] = "unknown"
        context["error_class"] = "unknown"
        return

    retriable, reason = classify_error(error)
    context["error_type"] = reason
    context["error_class"] = type(error).__name__
    context["error_retriable"] = retriable
    context["error_status_code"] = extract_status_code(error)
    context["error_code"] = extract_error_code(error)
    context["_normalized"] = True

    if reason != "generic":
        _logger.info("Error normalized: %s → %s (retriable=%s)", str(error)[:100], reason, retriable)


async def _cancel_cleanup(context: dict) -> None:
    """内置取消清理钩子：当 Agent 被取消时，自动拒绝所有待审批的 HITL 请求。"""
    hitl = context.get("hitl")
    if hitl and hasattr(hitl, "reject_all"):
        try:
            hitl.reject_all(reason="cancelled")
        except Exception:
            _logger.warning("Hook cancel_cleanup failed for hitl.reject_all", exc_info=True)


def register_error_hooks(hooks: AgentHooks) -> None:
    """向 AgentHooks 注册内置的错误归一化和取消清理钩子。"""
    hooks.on_error.append(_error_normalize)
    hooks.on_error.append(_cancel_cleanup)
