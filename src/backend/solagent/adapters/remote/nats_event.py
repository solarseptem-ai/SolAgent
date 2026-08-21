"""NATS 事件适配器：通过 NATS JetStream 实现 EventPort，支持分布式事件发布与订阅。

利用 NATS 的持久化消息流实现跨进程/跨节点的事件通信，
publish 将事件推送到 JetStream，subscribe 以拉模式消费指定主题的消息。
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

from solagent.events.types import AgentEvent

_logger = logging.getLogger(__name__)


class NatsEventAdapter:
    """基于 NATS JetStream 的事件适配器。

    属性:
        _url: NATS 服务器地址。
        _nc: NATS 连接对象，延迟初始化。
        _js: JetStream 上下文，延迟初始化。
    """

    def __init__(self, nats_url: str = "nats://localhost:4222"):
        self._url = nats_url
        self._nc = None
        self._js = None

    async def connect(self):
        """建立与 NATS 服务器的连接并获取 JetStream 上下文。"""
        import nats
        self._nc = await nats.connect(self._url)
        self._js = self._nc.jetstream()

    async def publish(self, event: AgentEvent) -> None:
        """将事件发布到 NATS JetStream。

        参数:
            event: 要发布的 AgentEvent。

        异常:
            RuntimeError: 当尚未调用 connect() 时抛出。
        """
        if not self._js:
            raise RuntimeError("NatsEventAdapter not connected")
        subject = f"events.{event.topic}"
        data = event.model_dump_json().encode()
        await self._js.publish(subject, data)

    async def subscribe(self, pattern: str, handler: Callable[[AgentEvent], Awaitable[None]]) -> None:
        """订阅指定模式的主题，在后台循环中拉取并处理消息。

        参数:
            pattern: 订阅的主题模式（支持 JetStream 通配符）。
            handler: 异步事件处理回调。

        异常:
            RuntimeError: 当尚未调用 connect() 时抛出。
        """
        if not self._js:
            raise RuntimeError("NatsEventAdapter not connected")
        from nats.js.api import AckPolicy, ConsumerConfig
        sub = await self._js.pull_subscribe(pattern, "solagent", config=ConsumerConfig(ack_policy=AckPolicy.EXPLICIT))

        async def _loop():
            """后台消息拉取循环：不断 fetch 消息并调用 handler 处理。"""
            while True:
                try:
                    msgs = await sub.fetch(1, timeout=1)
                    for msg in msgs:
                        data = json.loads(msg.data)
                        event = AgentEvent.model_validate(data)
                        await handler(event)
                        await msg.ack()
                except Exception:
                    _logger.warning("NATS event forwarding failed", exc_info=True)
                    await asyncio.sleep(0.1)

        asyncio.create_task(_loop())

    async def close(self):
        """关闭 NATS 连接。"""
        if self._nc:
            await self._nc.close()