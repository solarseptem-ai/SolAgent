"""Agent 核心模块的入口。

聚合了 SolAgent 中所有与 Agent 生命周期相关的核心组件，包括：
- 基础抽象（BaseAgent、AgentContext、AgentStep）
- 构建器（AgentBuilder）
- 执行模式（ReAct、DAG、Plan-Execute、Reflexion 等）
- 工具链（ToolRegistry、ToolExecutor、ToolGuard）
- 人机协同（HITLManager）
- 记忆与中间件（MemoryManager、MiddlewareChain）
- 人机回环与权限（HITL、PermissionEngine）
- 检查点（Checkpoint）

使用者通常通过 AgentBuilder 链式组装这些组件，然后调用 run() 或 run_stream() 执行。
"""

from solagent.agents.base import AgentContext, AgentStep, BaseAgent
from solagent.agents.builder import AgentBuilder
from solagent.agents.checkpoint import Checkpoint
from solagent.agents.dag.executor import DAGExecutor, DAGResult, StepResult
from solagent.agents.dag.plan import ExecutionPlan
from solagent.agents.hitl import HITLDecision, HITLManager, HITLRequest, HITLResponse
from solagent.agents.hooks import AgentHooks
from solagent.agents.memory.manager import MemoryManager
from solagent.agents.middleware.chain import MiddlewareChain
from solagent.agents.modes.chat import ChatMode
from solagent.agents.modes.code_as_action import CodeAsActionMode
from solagent.agents.modes.compiler import CompilerMode
from solagent.agents.modes.dag import DAGAgent
from solagent.agents.modes.function_call import FunctionCallMode
from solagent.agents.modes.plan_execute import PlanExecuteMode
from solagent.agents.modes.react import ReActMode
from solagent.agents.modes.reflexion import ReflexionMode
from solagent.agents.modes.registry import ModeRegistry
from solagent.agents.multi_agent.team import TeamAgent, TeamRunner
from solagent.agents.runner import AgentRunner
from solagent.agents.tools.base import BaseTool
from solagent.agents.tools.executor import ToolExecutor
from solagent.agents.tools.guard import GuardLevel, ToolGuard
from solagent.agents.tools.permission import (
    PermissionDecision,
    PermissionEngine,
    PermissionMode,
    PermissionResult,
    PermissionRule,
)
from solagent.agents.tools.registry import ToolRegistry

__all__ = [
    "AgentBuilder",
    "AgentContext",
    "AgentHooks",
    "AgentRunner",
    "AgentStep",
    "BaseAgent",
    "BaseTool",
    "ChatMode",
    "Checkpoint",
    "CodeAsActionMode",
    "CompilerMode",
    "DAGAgent",
    "DAGExecutor",
    "DAGResult",
    "ExecutionPlan",
    "FunctionCallMode",
    "GuardLevel",
    "HITLDecision",
    "HITLManager",
    "HITLRequest",
    "HITLResponse",
    "MemoryManager",
    "MiddlewareChain",
    "ModeRegistry",
    "PermissionDecision",
    "PermissionEngine",
    "PermissionMode",
    "PermissionResult",
    "PermissionRule",
    "PlanExecuteMode",
    "ReActMode",
    "ReflexionMode",
    "StepResult",
    "TeamAgent",
    "TeamRunner",
    "ToolExecutor",
    "ToolGuard",
    "ToolRegistry",
]