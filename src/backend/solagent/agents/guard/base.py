"""工具安全防护的基础协议与组合守卫。

定义 Guard 协议、GuardResult（检查结果）、GuardContext（检查上下文）以及
CompositeGuard（组合守卫，顺序执行多个守卫，任一阻止则立即返回）。
所有具体守卫（如 BashCommandScanner、FileSafetyGuard 等）均需实现 Guard 协议。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


@dataclass
class GuardResult:
    """工具安全检查的结果。

    属性:
        blocked: 是否被阻止执行。
        risk_level: 风险等级（safe / medium / high）。
        reason: 阻止原因或风险提示描述。
        code: 风险类型编码，便于上层分类处理。
    """
    blocked: bool = False
    risk_level: Literal["safe", "medium", "high"] = "safe"
    reason: str = ""
    code: str = ""


@dataclass
class ToolHistoryEntry:
    """单次工具调用的历史记录，用于循环检测等基于历史的守卫。

    属性:
        tool_name: 工具名称。
        tool_args_hash: 参数 SHA256 哈希。
        success: 调用是否成功。
        result_hash: 结果内容哈希，用于检测无进展重复调用。
    """
    tool_name: str
    tool_args_hash: str
    success: bool
    result_hash: str = ""


@dataclass
class GuardContext:
    """工具安全检查的上下文信息。

    属性:
        tool_history: 当前会话中的工具调用历史。
        tool_call_id: 当前工具调用的唯一标识。
        iteration: 当前 Agent 迭代轮次。
    """
    tool_history: list[ToolHistoryEntry] = field(default_factory=list)
    tool_call_id: str = ""
    iteration: int = 0


class Guard(Protocol):
    """工具安全守卫协议。

    所有具体守卫类必须实现此协议，通过 check 方法对工具调用进行安全审查。
    """
    async def check(self, tool_name: str, tool_args: dict[str, Any], context: GuardContext) -> GuardResult: ...


class CompositeGuard:
    """组合守卫，将多个守卫按顺序链式执行。

    任一守卫返回 blocked=True 时立即终止并返回该结果，实现快速失败策略。
    """

    def __init__(self, guards: list[Guard] | None = None):
        self._guards: list[Guard] = guards or []

    def add(self, guard: Guard) -> None:
        """向守卫链末尾追加一个守卫。"""
        self._guards.append(guard)

    async def check(self, tool_name: str, tool_args: dict[str, Any], context: GuardContext) -> GuardResult:
        """顺序执行所有守卫的检查，任一阻止则立即返回。"""
        for guard in self._guards:
            result = await guard.check(tool_name, tool_args, context)
            if result.blocked:
                return result
        return GuardResult()