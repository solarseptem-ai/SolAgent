"""子代理（Subagent）模块的入口。

子代理允许主 Agent 将子任务委托给其他 Agent 执行，实现任务拆分与并行处理。
本模块提供子代理的运行时管理（SubagentRuntime）、启动句柄（SubagentRun）以及
子代理契约类型（SubagentProvider、SubagentResult、SubagentStartRequest）。
"""

from solagent.subagent.runtime import SubagentRun, SubagentRuntime
from solagent.subagent.types import SubagentProvider, SubagentResult, SubagentStartRequest

__all__ = [
    "SubagentProvider",
    "SubagentResult",
    "SubagentRun",
    "SubagentRuntime",
    "SubagentStartRequest",
]