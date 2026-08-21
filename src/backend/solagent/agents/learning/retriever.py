"""经验检索器，按任务语义检索最相关的历史经验。

基于记忆系统的语义搜索能力，检索与当前任务相关的经验记录，
并结合相关性得分、时效性奖励和重要性进行综合排序，返回最匹配的经验供 Agent 参考。
"""

from __future__ import annotations

from datetime import UTC, datetime

from solagent.agents.learning.models import ExperienceRecord
from solagent.schema.memory import MemoryCategory, MemoryQuery


class ExperienceRetriever:
    """历史经验检索器。

    负责从记忆系统中检索与当前任务最相关的经验记录，
    采用多因子评分（语义相关性 + 时效性 + 重要性）进行综合排序。

    属性:
        memory_manager: 记忆管理器，提供语义搜索接口。
    """

    def __init__(self, memory_manager):
        self._memory_manager = memory_manager

    async def retrieve(self, task: str, limit: int = 5) -> list[ExperienceRecord]:
        """检索与任务最相关的历史经验记录。

        参数:
            task: 当前任务描述，用于语义匹配。
            limit: 最终返回的经验数量。

        返回:
            按综合得分降序排列的经验记录列表，最多 limit 条。
        """
        # 先检索 3 倍数量的候选结果，再精排取 Top-K
        query = MemoryQuery(
            query=task,
            categories=[MemoryCategory.EXPERIENCE],
            limit=limit * 3,
        )
        results = await self._memory_manager.search(query)

        scored: list[tuple[float, ExperienceRecord]] = []
        for r in results:
            record = ExperienceRecord.from_memory(r.record)
            composite = (
                r.score * 0.5
                + self._recency_bonus(record) * 0.3
                + r.record.importance * 0.2
            )
            scored.append((composite, record))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:limit]]

    def _recency_bonus(self, record: ExperienceRecord) -> float:
        """根据经验记录的创建时间计算时效性奖励。

        一周内 1.0、一个月内 0.5、超过一个月 0.1。
        """
        days = (datetime.now(UTC) - record.created_at).days
        if days <= 7:
            return 1.0
        if days <= 30:
            return 0.5
        return 0.1