"""经验学习相关的数据模型。

定义经验记录（ExperienceRecord）、策略规则（StrategyRule）和经验评分（ExperienceScore）
等核心数据结构，支持将 Agent 执行结果转化为可持久化的记忆记录，以及基于经验生成策略规则。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

from solagent.schema.memory import MemoryCategory, MemoryRecord


class ExperienceTag(str, Enum):
    """经验持久化等级标签。

    - PERMANENT: 核心策略和规则，永不失效。
    - DURABLE: 长期有效的经验模式。
    - EPHEMERAL: 短期有效，可能随时间过时。
    - CORRECTION: 用户纠正过的错误经验。
    """
    PERMANENT = "permanent"
    DURABLE = "durable"
    EPHEMERAL = "ephemeral"
    CORRECTION = "correction"


@dataclass
class ExperienceRecord:
    """单次 Agent 执行的经验记录。

    属性:
        task_signature: 任务签名/摘要。
        tag: 经验持久化等级标签。
        tool_sequence: 本次执行调用的工具序列。
        tool_success_map: 各工具的成功/失败状态。
        outcome: 执行结果（success / failure / partial）。
        error_pattern: 失败时的错误特征摘要。
        input_tokens: 输入 token 数。
        output_tokens: 输出 token 数。
        duration_ms: 执行耗时（毫秒）。
        lesson: 总结出的经验教训文本。
        score: 综合得分（0~1）。
        created_at: 记录创建时间。
    """
    task_signature: str
    tag: ExperienceTag = ExperienceTag.DURABLE
    tool_sequence: list[str] = field(default_factory=list)
    tool_success_map: dict[str, bool] = field(default_factory=dict)
    outcome: str = "success"
    error_pattern: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 0
    lesson: str | None = None
    score: float = 0.0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_memory_record(self) -> MemoryRecord:
        return MemoryRecord(
            id=str(uuid.uuid4()),
            content=self.task_signature,
            category=MemoryCategory.EXPERIENCE,
            importance=self.score,
            metadata={
                "tag": self.tag.value,
                "tool_sequence": self.tool_sequence,
                "tool_success_map": self.tool_success_map,
                "outcome": self.outcome,
                "error_pattern": self.error_pattern or "",
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "duration_ms": self.duration_ms,
                "lesson": self.lesson or "",
                "score": self.score,
            },
            created_at=self.created_at,
        )

    @classmethod
    def from_memory(cls, record: MemoryRecord) -> ExperienceRecord:
        m = record.metadata
        return cls(
            task_signature=record.content,
            tag=ExperienceTag(m.get("tag", "durable")),
            tool_sequence=m.get("tool_sequence", []),
            tool_success_map=m.get("tool_success_map", {}),
            outcome=m.get("outcome", "success"),
            error_pattern=m.get("error_pattern") or None,
            input_tokens=m.get("input_tokens", 0),
            output_tokens=m.get("output_tokens", 0),
            duration_ms=m.get("duration_ms", 0),
            lesson=m.get("lesson") or None,
            score=m.get("score", 0.0),
            created_at=record.created_at,
        )


@dataclass
class StrategyRule:
    """策略规则，基于历史经验归纳出的行为指导。

    属性:
        rule_id: 规则唯一标识。
        description: 规则描述文本。
        status: 规则状态（active / inactive）。
        trigger_conditions: 触发该规则的条件字典。
        recommended_tools: 推荐使用的工具列表。
        deprecated_tools: 不推荐或废弃的工具列表。
        forbidden_patterns: 禁止出现的模式列表。
        successful_patterns: 已验证成功的模式列表。
        success_rate: 成功率（0~1）。
        use_count: 使用次数。
        last_used: 上次使用时间。
        created_at: 创建时间。
    """

    rule_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    description: str = ""
    status: str = "active"
    trigger_conditions: dict = field(default_factory=dict)
    recommended_tools: list[str] = field(default_factory=list)
    deprecated_tools: list[str] = field(default_factory=list)
    forbidden_patterns: list[str] = field(default_factory=list)
    successful_patterns: list[str] = field(default_factory=list)
    success_rate: float = 1.0
    use_count: int = 0
    last_used: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_memory_record(self) -> MemoryRecord:
        return MemoryRecord(
            id=self.rule_id,
            content=self.description,
            category=MemoryCategory.STRATEGY,
            importance=self.success_rate,
            metadata={
                "status": self.status,
                "trigger_conditions": self.trigger_conditions,
                "recommended_tools": self.recommended_tools,
                "deprecated_tools": self.deprecated_tools,
                "forbidden_patterns": self.forbidden_patterns,
                "successful_patterns": self.successful_patterns,
                "success_rate": self.success_rate,
                "use_count": self.use_count,
                "last_used": self.last_used.isoformat(),
                "created_at": self.created_at.isoformat(),
            },
            created_at=self.created_at,
        )

    @classmethod
    def from_memory(cls, record: MemoryRecord) -> StrategyRule:
        m = record.metadata
        return cls(
            rule_id=record.id,
            description=record.content,
            status=m.get("status", "active"),
            trigger_conditions=m.get("trigger_conditions", {}),
            recommended_tools=m.get("recommended_tools", []),
            deprecated_tools=m.get("deprecated_tools", []),
            forbidden_patterns=m.get("forbidden_patterns", []),
            successful_patterns=m.get("successful_patterns", []),
            success_rate=m.get("success_rate", 1.0),
            use_count=m.get("use_count", 0),
            last_used=datetime.fromisoformat(m["last_used"]) if "last_used" in m else datetime.now(UTC),
            created_at=datetime.fromisoformat(m["created_at"]) if "created_at" in m else datetime.now(UTC),
        )


@dataclass
class ExperienceScore:
    """经验评分模型，多维度衡量单次 Agent 执行的效率和质量。

    维度:
        task_success: 任务成功率（0~1）。
        tool_efficiency: 工具使用效率，调用越少得分越高（0~1）。
        token_efficiency: Token 使用效率，消耗越少得分越高（0~1）。
        user_feedback: 用户反馈得分（默认 0.5）。
        overall: 综合得分，由 compute() 计算得出。
    """

    task_success: float = 0.0
    tool_efficiency: float = 0.0
    token_efficiency: float = 0.0
    user_feedback: float = 0.5
    overall: float = 0.0

    def compute(self) -> float:
        """按加权公式计算综合得分并缓存到 overall。

        权重:
            任务成功 40%、工具效率 20%、token 效率 20%、用户反馈 20%。
        """
        self.overall = (
            self.task_success * 0.4
            + self.tool_efficiency * 0.2
            + self.token_efficiency * 0.2
            + self.user_feedback * 0.2
        )
        return self.overall