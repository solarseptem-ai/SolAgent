"""子代理的核心类型定义。

定义子代理启动请求（SubagentStartRequest）、执行结果（SubagentResult）
以及子代理提供者协议（SubagentProvider），为子代理的调用方和实现方提供统一契约。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class SubagentStartRequest:
    """子代理启动请求。

    属性:
        task: 要分配给子代理执行的任务描述。
        persona: 子代理使用的人格/角色描述，覆盖默认人格。
        tools: 子代理可使用的工具名列表，None 表示继承父代理的工具。
        model: 指定子代理使用的模型名称。
        max_iterations: 子代理最大迭代轮数，防止无限循环。
        extra: 扩展参数字典，供具体提供者自定义使用。
    """
    task: str
    persona: str | None = None
    tools: list[str] | None = None
    model: str | None = None
    max_iterations: int = 10
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class SubagentResult:
    """子代理执行结果。

    属性:
        value: 子代理返回的原始结果值。
        error: 若执行失败，此处为错误信息；成功时为 None。
        iterations: 子代理实际执行的迭代轮数。
        extra: 扩展结果字典，供具体提供者附加额外信息。
    """
    value: Any = None
    error: str | None = None
    iterations: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        """判断子代理是否成功完成（无错误）。"""
        return self.error is None


class SubagentProvider(Protocol):
    """子代理提供者协议。

    任何实现了该协议的类都可以注册到 SubagentRuntime 中，
    供主 Agent 按名称调用以执行子任务。

    属性:
        name: 提供者的唯一标识名称。
    """

    name: str

    async def start(self, request: SubagentStartRequest) -> SubagentResult:
        """启动并执行一次子代理任务，返回执行结果。

        参数:
            request: 子代理启动请求。

        返回:
            子代理执行完毕后的结果对象。
        """
        ...


class SubagentDepthError(Exception):
    """子代理深度超限。"""

    def __init__(self, depth: int, max_depth: int):
        self.depth = depth
        self.max_depth = max_depth
        super().__init__(f"Subagent depth {depth} exceeds max {max_depth}")