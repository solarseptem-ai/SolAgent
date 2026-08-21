"""结构化输出相关的 Pydantic 模型定义。

本模块提供了 Agent 在计划执行、DAG 编排、自我反思和会话压缩等场景中
所需的结构化输出 Schema。这些模型使 LLM 能够生成符合预定义结构的数据，
便于下游组件进行解析、验证和自动化处理。
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class PlanStep(BaseModel):
    """计划中的单个步骤模型，描述 Agent 要执行的具体动作。

    属性说明：
        step: 步骤序号，用于确定执行顺序。
        action: 步骤的动作描述或指令文本。
        tool: 该步骤需要调用的工具名称，空字符串表示不调用工具。
        args: 传递给工具的参数字典。
    """
    step: int
    action: str
    tool: str = ""
    args: dict[str, Any] = Field(default_factory=dict)


class PlanModel(BaseModel):
    """计划模型，封装 Agent 完成任务的完整步骤序列。

    支持从裸数组自动包装为对象形式，方便 LLM 直接输出步骤列表。
    """
    steps: list[PlanStep]

    @model_validator(mode='before')
    @classmethod
    def _accept_bare_array(cls, data: Any) -> Any:
        """若输入为纯数组，自动包装为 {'steps': data} 格式以兼容模型验证。"""
        if isinstance(data, list):
            return {"steps": data}
        return data


class RetryPolicy(BaseModel):
    """单步重试策略模型，定义步骤执行失败时的重试行为。

    属性说明：
        max_attempts: 最大重试次数，含首次执行。
        initial_interval: 首次重试前的等待间隔（秒）。
        backoff_factor: 退避乘数，每次重试后等待时间乘以该因子。
        max_interval: 最大等待间隔（秒），防止退避时间无限增长。
        retry_on: 触发重试的错误类型列表，空列表表示对所有可重试错误生效。
    """
    max_attempts: int = 3
    initial_interval: float = 1.0
    backoff_factor: float = 2.0
    max_interval: float = 30.0
    retry_on: list[str] = Field(default_factory=list)


class DAGStep(BaseModel):
    """DAG（有向无环图）中的单个步骤模型，支持数据流映射、条件执行和错误处理。

    属性说明：
        id: 步骤的唯一标识符。
        tool: 步骤调用的工具名称。
        args: 工具参数字典。
        depends_on: 依赖步骤的 ID 列表，这些步骤必须先执行完成。
        description: 步骤的描述文本。
        input_mapping: 数据流映射，使用 Jinja2 模板引用上游步骤的输出，
            例如 {"file_path": "{{ step_read_dir.output.files[0].path }}"}。
        condition: 条件执行表达式，基于步骤输出评估是否执行，
            例如 "step_validate.output.status == 'ok'"。
        retry_policy: 该步骤的重试策略配置。
        error_handler: 错误处理策略标识。
        on_error: 错误时的行为，可选 "fail"（失败）、"skip"（跳过）、"continue"（继续）。
        run_timeout: 步骤运行超时时间（秒）。
        idle_timeout: 步骤空闲超时时间（秒）。
        cache_policy: 缓存策略，"none" 不缓存，"inputs" 按输入缓存，"always" 总是缓存。
        fan_out: 动态扇出表达式，评估结果可展开为多个并行实例。
        fan_out_as: 扇出迭代变量的名称。
        sub_dag: 嵌套子 DAG，用于复杂步骤的进一步分解。
    """
    id: str
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    description: str = ""

    # 数据流映射：使用 Jinja2 模板引用上游步骤输出
    input_mapping: dict[str, str] = Field(default_factory=dict)

    # 条件执行：基于步骤输出评估的 Python 表达式
    condition: str | None = None

    # 错误处理配置
    retry_policy: RetryPolicy | None = None
    error_handler: str | None = None
    on_error: Literal["fail", "skip", "continue"] = "fail"

    # 步骤超时配置
    run_timeout: float = 300.0
    idle_timeout: float = 60.0

    # 缓存策略
    cache_policy: Literal["none", "inputs", "always"] = "none"

    # 动态扇出：表达式结果可展开为 N 个并行实例
    fan_out: str | None = None
    fan_out_as: str = "item"

    # 嵌套子 DAG，支持复杂任务的层次化分解
    sub_dag: DAGModel | None = None


class DAGModel(BaseModel):
    """DAG 编排模型，定义一组带依赖关系的步骤及其执行策略。

    支持拓扑排序确定并行执行层级、环检测防止死锁，以及编译期验证确保配置正确性。
    """
    steps: list[DAGStep]

    @model_validator(mode='before')
    @classmethod
    def _accept_bare_array(cls, data: Any) -> Any:
        """若输入为纯数组，自动包装为 {'steps': data} 格式以兼容模型验证。"""
        if isinstance(data, list):
            return {"steps": data}
        return data

    def topological_sort(self) -> list[list[DAGStep]]:
        """使用 Kahn 算法进行拓扑排序，返回可按层级并行执行的步骤分组。

        每一层内的步骤没有相互依赖，可以并发执行；层与层之间按顺序执行。
        """
        # 构建入度表和依赖关系图
        in_degree: dict[str, int] = {s.id: len(s.depends_on) for s in self.steps}
        dependents: dict[str, list[str]] = {s.id: [] for s in self.steps}
        for s in self.steps:
            for dep in s.depends_on:
                dependents.setdefault(dep, []).append(s.id)

        # 初始化队列：入度为 0 的步骤可以先执行
        queue = [sid for sid, deg in in_degree.items() if deg == 0]
        levels: list[list[str]] = []
        while queue:
            levels.append(list(queue))
            next_queue: list[str] = []
            for sid in queue:
                for dep in dependents.get(sid, []):
                    in_degree[dep] -= 1
                    if in_degree[dep] == 0:
                        next_queue.append(dep)
            queue = next_queue

        step_map = {s.id: s for s in self.steps}
        return [[step_map[sid] for sid in level if sid in step_map] for level in levels]

    def detect_cycles(self) -> list[list[str]]:
        """使用 DFS 三色标记法检测 DAG 中存在的所有环。

        Returns:
            检测到的所有环，每个环以步骤 ID 列表形式返回。
        """
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {s.id: WHITE for s in self.steps}
        parent: dict[str, str | None] = {s.id: None for s in self.steps}
        cycles: list[list[str]] = []
        adj: dict[str, list[str]] = {s.id: [] for s in self.steps}
        for s in self.steps:
            for dep in s.depends_on:
                adj.setdefault(dep, []).append(s.id)

        def dfs(u: str) -> None:
            color[u] = GRAY
            for v in adj.get(u, []):
                if color.get(v) == GRAY:
                    # 发现回边，构成环，回溯收集环上的所有节点
                    cycle = [v, u]
                    cur = parent.get(u)
                    while cur and cur != v:
                        cycle.append(cur)
                        cur = parent.get(cur)
                    cycle.append(v)
                    cycles.append(cycle[::-1])
                elif color.get(v) == WHITE:
                    parent[v] = u
                    dfs(v)
            color[u] = BLACK

        for sid in color:
            if color[sid] == WHITE:
                dfs(sid)
        return cycles

    def validate(self) -> list[str]:
        """编译期验证 DAG 配置的合法性，返回所有错误信息列表。

        检查项包括：步骤 ID 唯一性、tool/sub_dag 互斥性、依赖项存在性以及环检测。
        """
        errors: list[str] = []
        step_ids = {s.id for s in self.steps}
        if len(step_ids) != len(self.steps):
            errors.append("Duplicate step IDs found")
        for s in self.steps:
            if s.tool and s.sub_dag:
                errors.append(f"Step '{s.id}': cannot specify both tool and sub_dag")
            if not s.tool and not s.sub_dag:
                errors.append(f"Step '{s.id}': must specify either tool or sub_dag")
            for dep in s.depends_on:
                if dep not in step_ids:
                    errors.append(f"Step '{s.id}': depends on unknown step '{dep}'")
        cycles = self.detect_cycles()
        if cycles:
            for cycle in cycles:
                errors.append(f"Cycle detected: {' -> '.join(cycle)}")
        return errors


class ReflexionModel(BaseModel):
    """自我反思模型，用于 Agent 在执行失败后分析原因并调整策略。

    属性说明：
        analysis: 对失败原因或当前状况的分析总结。
        new_approach: 基于分析得出的新执行方案或改进策略。
    """
    analysis: str
    new_approach: str


class ConversationSummary(BaseModel):
    """结构化会话摘要模型，用于上下文压缩和长会话管理。

    当会话历史过长时，Agent 可生成该摘要替代原始消息，既保留关键信息又减少 Token 消耗。

    属性说明：
        task_overview: 当前任务的总体描述。
        current_state: 当前执行到的步骤或阶段。
        key_facts: 会话中发现的关键事实列表。
        decisions: 已做出的决策列表。
        action_items: 待执行的后续行动项列表。
        context_to_preserve: 必须保留的原始上下文内容，防止关键信息丢失。
    """
    task_overview: str = Field(default="", description="What is the current task")
    current_state: str = Field(default="", description="What step are we on")
    key_facts: list[str] = Field(default_factory=list, description="Important facts discovered")
    decisions: list[str] = Field(default_factory=list, description="Decisions made")
    action_items: list[str] = Field(default_factory=list, description="Pending action items")
    context_to_preserve: str = Field(default="", description="Context that must not be lost")
