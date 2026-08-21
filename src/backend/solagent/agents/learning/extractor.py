"""经验提取器，从 Agent 单次执行结果中提炼结构化经验记录。

分析 Agent 的任务描述、工具调用序列、执行结果（成功/失败/部分成功）、错误模式
以及资源消耗（token、耗时），生成 ExperienceRecord 供记忆系统持久化。
同时计算经验得分，低分经验会被标记为短期（EPHEMERAL），减少长期记忆噪音。
"""

from __future__ import annotations

from datetime import UTC, datetime

from solagent.agents.learning.models import (
    ExperienceRecord,
    ExperienceScore,
    ExperienceTag,
)
from solagent.schema.agent import AgentResult
from solagent.schema.messages import Message, TextBlock, ThinkingBlock


class ExperienceExtractor:
    """Agent 执行经验提取器。

    负责将一次 Agent 执行的完整上下文和结果转化为结构化的 ExperienceRecord，
    以便后续检索和策略优化使用。

    属性:
        memory_manager: 记忆管理器，用于持久化经验记录。
        provider: LLM 提供者，预留用于未来需要 LLM 辅助提取的场景。
    """

    def __init__(self, memory_manager, provider):
        self._memory_manager = memory_manager
        self._provider = provider

    async def extract(self, result: AgentResult, messages: list[Message]) -> ExperienceRecord:
        """从 Agent 执行结果和对话消息中提取经验记录。

        参数:
            result: Agent 执行结果，包含 finish_reason、tool_results、token_usage 等。
            messages: 本次执行的完整对话消息列表。

        返回:
            结构化的 ExperienceRecord，包含评分和标签。
        """
        task_signature = self._summarize_task(messages)
        tool_sequence = self._extract_tool_sequence(result)
        tool_success_map = self._extract_tool_success(result)
        outcome = self._determine_outcome(result)
        error_pattern = self._extract_error_pattern(result) if outcome == "failure" else None

        record = ExperienceRecord(
            task_signature=task_signature,
            tool_sequence=tool_sequence,
            tool_success_map=tool_success_map,
            outcome=outcome,
            error_pattern=error_pattern,
            input_tokens=result.token_usage.input_tokens,
            output_tokens=result.token_usage.output_tokens,
            duration_ms=result.duration_ms,
            created_at=datetime.now(UTC),
        )

        record.score = self._compute_score(record)
        # 得分过低时降级为短期记忆，减少长期噪音
        if record.score < 0.6:
            record.tag = ExperienceTag.EPHEMERAL

        return record

    async def persist(self, record: ExperienceRecord):
        """将经验记录持久化到记忆系统。

        参数:
            record: 要保存的经验记录。
        """
        await self._memory_manager.add(record.to_memory_record())

    def _summarize_task(self, messages: list[Message]) -> str:
        """从消息列表中提取用户任务的简短摘要（取第一条用户消息前 200 字符）。"""
        for msg in messages:
            if msg.role == "user":
                text = self._extract_text(msg)
                if text:
                    return text[:200]
        return "unknown task"

    def _extract_text(self, msg: Message) -> str:
        """从单条消息中提取所有文本和思维链内容。"""
        parts = []
        for block in msg.content:
            if isinstance(block, (TextBlock, ThinkingBlock)):
                text = block.text if isinstance(block, TextBlock) else block.thinking
                if text:
                    parts.append(text)
        return " ".join(parts)

    def _extract_tool_sequence(self, result: AgentResult) -> list[str]:
        """提取本次执行中调用的工具名称序列。"""
        return [r.name for r in result.tool_results]

    def _extract_tool_success(self, result: AgentResult) -> dict[str, bool]:
        """提取每个工具调用的成功/失败状态映射。"""
        return {r.name: not r.is_error for r in result.tool_results}

    def _determine_outcome(self, result: AgentResult) -> str:
        """根据 finish_reason 和内容判断执行结果类型。

        返回 "success"、"failure" 或 "partial" 之一。
        """
        if result.finish_reason == "stop":
            return "success"
        if result.finish_reason == "error":
            return "failure"
        if result.finish_reason == "max_iterations":
            return "partial"
        return "success" if result.content else "failure"

    def _extract_error_pattern(self, result: AgentResult) -> str:
        """提取失败场景下的错误特征（首个错误工具的输出或最终内容前 200 字符）。"""
        for r in result.tool_results:
            if r.is_error:
                return r.output[:200]
        return result.content[:200] if result.content else "unknown error"

    def _compute_score(self, record: ExperienceRecord) -> float:
        """综合计算经验得分，衡量任务成功率、工具效率、token 效率。

        得分范围 [0, 1]，用于决定该经验应被标记为长期还是短期记忆。
        """
        score = ExperienceScore(
            task_success=1.0 if record.outcome == "success" else (0.5 if record.outcome == "partial" else 0.0),
            tool_efficiency=min(1.0, 3.0 / max(1, len(record.tool_sequence))),
            token_efficiency=min(1.0, 2000.0 / max(1, record.input_tokens + record.output_tokens)),
            user_feedback=0.5,
        )
        return score.compute()