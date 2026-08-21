"""基于 NATS KV Store 的 Agent 注册中心：实现 DiscoveryPort 的分布式版本。

利用 NATS 的键值存储实现 Agent 能力的注册、发现和注销，
支持按工具、模式、模型等条件过滤查询，适用于动态扩缩容的分布式 Agent 集群。
"""
from __future__ import annotations

import json
import logging

from solagent.schema.agent import AgentCapability

_logger = logging.getLogger(__name__)


class NatsRegistry:
    """基于 NATS KV 的 Agent 注册与发现组件。

    属性:
        _nats: NatsEventAdapter 实例，复用其 NATS 连接。
        _kv: NATS KeyValue 存储句柄，延迟初始化。
    """

    def __init__(self, nats_adapter):
        self._nats = nats_adapter
        self._kv = None

    async def connect(self):
        """通过复用的 NATS 连接初始化 KV 存储（bucket 名为 "agents"）。"""
        if self._nats._nc:
            self._kv = await self._nats._nc.jetstream().create_key_value(bucket="agents")

    async def register(self, capability: AgentCapability) -> None:
        """将 Agent 的能力信息注册到 NATS KV 中。

        参数:
            capability: 该 Agent 的能力描述对象。

        异常:
            RuntimeError: 当尚未调用 connect() 时抛出。
        """
        if not self._kv:
            raise RuntimeError("NatsRegistry not connected")
        key = f"agent.{capability.agent_id}"
        await self._kv.put(key, capability.model_dump_json().encode())

    async def find(self, criteria: dict) -> list[AgentCapability]:
        """根据条件在 NATS KV 中查找匹配的 Agent 能力。

        支持的条件键包括 "tool"、"mode"、"model"，分别匹配 capabilities 中的对应列表。

        参数:
            criteria: 查询条件字典，例如 {"tool": "search", "mode": "react"}。

        返回:
            符合条件的 AgentCapability 列表。

        异常:
            RuntimeError: 当尚未调用 connect() 时抛出。
        """
        if not self._kv:
            raise RuntimeError("NatsRegistry not connected")
        results = []
        try:
            keys = await self._kv.keys()
            for key in keys:
                try:
                    entry = await self._kv.get(key)
                    cap = AgentCapability.model_validate(json.loads(entry.value))
                    match = True
                    # 逐条校验查询条件是否全部满足
                    for k, v in criteria.items():
                        if k == "tool" and v not in cap.tools or k == "mode" and v not in cap.modes or k == "model" and v not in cap.models:
                            match = False
                    if match:
                        results.append(cap)
                except Exception:
                    _logger.warning("Remote adapter registry lookup failed", exc_info=True)
        except Exception:
            _logger.warning("Remote adapter registry lookup failed", exc_info=True)
        return results

    async def deregister(self, agent_id: str) -> None:
        """从 NATS KV 中注销指定 Agent。

        参数:
            agent_id: 要注销的 Agent ID。

        异常:
            RuntimeError: 当尚未调用 connect() 时抛出。
        """
        if not self._kv:
            raise RuntimeError("NatsRegistry not connected")
        await self._kv.delete(f"agent.{agent_id}")