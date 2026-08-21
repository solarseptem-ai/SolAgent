"""多提供商负载均衡器，在多个 LLM 提供商之间按策略分发请求。

支持轮询、随机、最少使用和加权四种策略，用于提升吞吐量与可用性。
"""
from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import AsyncIterator
from enum import Enum

from solagent.llms.providers.base import LLMProvider
from solagent.schema.llm import LLMRequest, LLMResponse, LLMStreamChunk


class BalanceStrategy(str, Enum):
    """负载均衡策略枚举。

    - ROUND_ROBIN: 轮询，按顺序循环分配请求。
    - RANDOM: 随机选择提供商。
    - LEAST_USED: 选择累计调用次数最少的提供商。
    - WEIGHTED: 按权重概率随机选择提供商。
    """
    ROUND_ROBIN = "round_robin"
    RANDOM = "random"
    LEAST_USED = "least_used"
    WEIGHTED = "weighted"


class LoadBalancer:
    """LLM 请求负载均衡器。

    维护一组 LLMProvider，根据指定策略为每次请求选择其中一个执行。
    同时统计各节点的调用次数，供最少使用策略和监控使用。

    属性:
        _providers: 已注册的 LLMProvider 列表。
        _weights: 与 _providers 对应的权重列表。
        _call_counts: 记录每个 provider 索引的累计调用次数。
        _strategy: 当前使用的负载均衡策略。
        _rr_index: 轮询策略的当前游标。
    """

    def __init__(self, strategy: BalanceStrategy = BalanceStrategy.ROUND_ROBIN):
        self._providers: list[LLMProvider] = []
        self._weights: list[float] = []
        self._call_counts: dict[int, int] = defaultdict(int)
        self._strategy = strategy
        self._rr_index = 0

    def add_provider(self, provider: LLMProvider, weight: float = 1.0) -> None:
        """注册一个新的 LLM 提供商及其权重。

        参数:
            provider: 要注册的 LLMProvider 实例。
            weight: 该提供商的权重，仅在 WEIGHTED 策略下生效。
        """
        self._providers.append(provider)
        self._weights.append(weight)

    def remove_provider(self, index: int) -> None:
        """移除指定索引的提供商。

        参数:
            index: 提供商在内部列表中的索引。
        """
        if 0 <= index < len(self._providers):
            self._providers.pop(index)
            self._weights.pop(index)

    def _select_provider(self) -> LLMProvider:
        """根据当前策略选择一个 LLMProvider。

        返回:
            被选中的 LLMProvider 实例。

        异常:
            ValueError: 当未注册任何提供商时抛出。
        """
        if not self._providers:
            raise ValueError("No providers registered")

        if self._strategy == BalanceStrategy.ROUND_ROBIN:
            idx = self._rr_index % len(self._providers)
            self._rr_index += 1
            return self._providers[idx]

        elif self._strategy == BalanceStrategy.RANDOM:
            return random.choice(self._providers)

        elif self._strategy == BalanceStrategy.LEAST_USED:
            # 选择调用次数最少的 provider 索引
            min_idx = min(range(len(self._providers)), key=lambda i: self._call_counts[i])
            return self._providers[min_idx]

        elif self._strategy == BalanceStrategy.WEIGHTED:
            # 基于权重的轮盘赌选择
            total = sum(self._weights)
            if total == 0:
                return self._providers[0]
            r = random.random() * total
            cumulative = 0.0
            for i, w in enumerate(self._weights):
                cumulative += w
                if r <= cumulative:
                    return self._providers[i]
            return self._providers[-1]

        return self._providers[0]

    async def chat(self, request: LLMRequest) -> LLMResponse:
        """使用选中的提供商执行普通对话请求，并增加对应计数。

        参数:
            request: LLM 请求对象。

        返回:
            选中提供商返回的 LLMResponse。
        """
        provider = self._select_provider()
        idx = self._providers.index(provider)
        self._call_counts[idx] += 1
        return await provider.chat(request)

    async def chat_stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        """使用选中的提供商执行流式对话请求，并增加对应计数。

        参数:
            request: LLM 流式请求对象。
        """
        provider = self._select_provider()
        idx = self._providers.index(provider)
        self._call_counts[idx] += 1
        async for chunk in provider.chat_stream(request):
            yield chunk

    @property
    def provider_count(self) -> int:
        """返回当前已注册的提供商数量。"""
        return len(self._providers)

    def reset_stats(self) -> None:
        """重置调用计数和轮询游标。"""
        self._call_counts.clear()
        self._rr_index = 0