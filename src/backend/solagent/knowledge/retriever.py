"""
知识检索器模块。

封装对知识库的检索逻辑，支持事件上报（开始、错误、结束）。
当未配置知识库或检索失败时，优雅降级返回空列表。
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from solagent.events.types import AgentEventType

if TYPE_CHECKING:
    from solagent.events.bus import EventBus

_logger = logging.getLogger(__name__)


class KnowledgeRetriever:
    """知识检索器，代理 KnowledgeBase 的 search 操作并上报生命周期事件。

    Attributes:
        _kb: 关联的知识库实例，可为 None。
        _event_bus: 可选的事件总线，用于上报检索状态。
    """

    def __init__(self, knowledge_base=None, event_bus: EventBus | None = None):
        self._kb = knowledge_base
        self._event_bus = event_bus

    async def retrieve(self, query: str, top_k: int = 5) -> list:
        """从知识库检索与查询最相关的文档。

        Args:
            query: 查询文本。
            top_k: 返回的最大结果数，默认 5。

        Returns:
            相关文档列表；若知识库未配置或检索失败，返回空列表。
        """
        # 未配置知识库时直接返回空结果
        if self._kb is None:
            return []
        # 上报检索开始事件
        if self._event_bus:
            from solagent.events.types import AgentEvent as _AgentEvent
            self._event_bus.emit(_AgentEvent(
                event_type=AgentEventType.KNOWLEDGE_QUERY_START,
                data={"query": query, "top_k": top_k},
            ))
        try:
            results = await self._kb.search(query, top_k)
        except Exception as e:
            # 检索失败时上报错误事件并记录日志
            if self._event_bus:
                from solagent.events.types import AgentEvent as _AgentEvent
                self._event_bus.emit(_AgentEvent(
                    event_type=AgentEventType.KNOWLEDGE_QUERY_ERROR,
                    data={"query": query, "error": str(e)},
                ))
            _logger.warning("Knowledge retrieval failed: %s", e, exc_info=True)
            return []
        # 上报检索完成事件
        if self._event_bus:
            from solagent.events.types import AgentEvent as _AgentEvent
            self._event_bus.emit(_AgentEvent(
                event_type=AgentEventType.KNOWLEDGE_QUERY_END,
                data={"query": query, "result_count": len(results)},
            ))
        return results