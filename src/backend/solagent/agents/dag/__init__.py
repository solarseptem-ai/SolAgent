"""DAG（有向无环图）执行模块的入口。

提供 DAG 模型的编译（ExecutionPlan）和执行（DAGExecutor）能力，
支持按拓扑层级并行执行步骤、条件分支、Fan-out、缓存、重试和子 DAG 嵌套。
适用于需要将复杂任务拆分为多步骤流水线并按依赖关系调度的场景。
"""

from solagent.agents.dag.executor import DAGExecutor, DAGResult, StepResult
from solagent.agents.dag.plan import ExecutionPlan

__all__ = ["DAGExecutor", "DAGResult", "ExecutionPlan", "StepResult"]