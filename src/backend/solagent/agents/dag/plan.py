"""DAG 编译模块。

将 DAGModel 编译为可执行的 ExecutionPlan，执行拓扑排序生成层级结构，
验证 DAG 合法性并检测环。编译结果供 DAGExecutor 按层级并行调度执行。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from solagent.schema.structured import DAGModel, DAGStep


@dataclass
class ExecutionPlan:
    """DAG 编译后的执行计划。

    包含拓扑层级、循环检测结果和验证错误。DAGExecutor 按 levels 逐层调度执行。

    属性:
        dag: 原始 DAG 模型。
        levels: 拓扑层级列表，每个层级内的步骤可并行执行。
        cycles: 检测到的循环路径列表。
        errors: 验证错误信息列表。
    """

    dag: DAGModel
    levels: list[list[DAGStep]] = field(default_factory=list)
    cycles: list[list[str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """执行计划是否通过验证（无错误）。"""
        return len(self.errors) == 0

    @property
    def total_steps(self) -> int:
        """DAG 中的总步骤数。"""
        return len(self.dag.steps)

    @property
    def level_count(self) -> int:
        """拓扑层级的数量。"""
        return len(self.levels)

    @classmethod
    def compile(cls, dag: DAGModel) -> ExecutionPlan:
        """编译 DAG 模型为执行计划。

        参数:
            dag: 待编译的 DAG 模型。

        返回:
            包含拓扑层级、循环检测和验证错误的 ExecutionPlan。
        """
        errors = dag.validate()
        if errors:
            return cls(dag=dag, errors=errors)
        levels = dag.topological_sort()
        cycles = dag.detect_cycles()
        return cls(dag=dag, levels=levels, cycles=cycles)