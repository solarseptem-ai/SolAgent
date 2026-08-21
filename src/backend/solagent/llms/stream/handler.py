"""流式响应处理器，用于收集 LLM 流式 chunk 并转换为统一的 StreamEvent。

将底层 LLMStreamChunk 抽象为前端友好的 StreamEvent（文本增量、思考增量、数据块等），
同时提供 collect 方法将完整流内容拼接为字符串，方便非流式消费场景。
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from solagent.schema.llm import LLMFinishReason, LLMStreamChunk
from solagent.schema.stream import DeltaEvent, StreamEvent, StreamEventType


class StreamHandler:
    """处理 LLM 流式输出的工具类。

    支持将异步 chunk 流收集为完整文本，或将每个 chunk 转译为结构化事件流。
    """

    async def collect(self, stream: AsyncIterator[LLMStreamChunk]) -> tuple[str, list[LLMStreamChunk]]:
        """收集流中的所有 chunk，拼接为完整文本并保留原始 chunk 列表。

        参数:
            stream: LLMStreamChunk 异步迭代器。

        返回:
            (完整文本内容, 原始 chunk 列表) 的元组。
        """
        chunks: list[LLMStreamChunk] = []
        content_parts: list[str] = []
        async for chunk in stream:
            chunks.append(chunk)
            if chunk.content:
                content_parts.append(chunk.content)
        return "".join(content_parts), chunks

    async def to_events(self, stream: AsyncIterator[LLMStreamChunk]) -> AsyncIterator[StreamEvent]:
        """将 LLMStreamChunk 流转换为 StreamEvent 流。

        根据 chunk 类型分别生成 TEXT_DELTA、THINKING_DELTA、DATA_BLOCK_* 和 DONE 事件，
        方便上层或前端统一消费。

        参数:
            stream: LLMStreamChunk 异步迭代器。
        """
        async for chunk in stream:
            if chunk.data_block:
                # 数据块（如文件、图片）拆分为 START / DELTA / END 事件序列
                for event in self._emit_data_block_events(chunk.data_block):
                    yield event
            elif chunk.is_thinking:
                yield StreamEvent(event_type=StreamEventType.THINKING_DELTA, data={"content": chunk.content or ""})
            else:
                yield StreamEvent(event_type=StreamEventType.TEXT_DELTA, data={"content": chunk.content or ""})
            if chunk.finish_reason:
                yield StreamEvent(event_type=StreamEventType.DONE, data={"finish_reason": chunk.finish_reason.value})

    def _emit_data_block_events(self, data_block: dict):
        """将单个数据块拆分为 DATA_BLOCK_START、DATA_BLOCK_DELTA、DATA_BLOCK_END 事件序列。

        参数:
            data_block: 包含 id、media_type、name、data 等字段的数据块字典。
        """
        from uuid import uuid4

        block_id = data_block.get("id", str(uuid4()))
        media_type = data_block.get("media_type", "application/octet-stream")
        name = data_block.get("name", "data")

        yield StreamEvent(
            event_type=StreamEventType.DATA_BLOCK_START,
            data={"name": name, "media_type": media_type, "block_id": block_id,
                  "estimated_size": data_block.get("estimated_size")},
            timestamp=0.0,
        )

        data = data_block.get("data", "")
        chunk_size = 4096
        # 将大数据分片，每片生成一个 DELTA 事件
        for i in range(0, len(data), chunk_size):
            split = data[i:i + chunk_size]
            yield StreamEvent(
                event_type=StreamEventType.DATA_BLOCK_DELTA,
                data={"block_id": block_id, "index": i // chunk_size,
                      "delta": split, "is_last": i + chunk_size >= len(data)},
                timestamp=0.0,
            )

        yield StreamEvent(
            event_type=StreamEventType.DATA_BLOCK_END,
            data={"block_id": block_id, "name": name, "total_size": len(data), "media_type": media_type},
            timestamp=0.0,
        )
