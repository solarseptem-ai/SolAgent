"""流式空闲超时包装器：当两次 chunk 之间的间隔超过阈值时主动中断。

用于防止 LLM 流式响应因模型卡住、网络挂起或大型工具调用导致无限等待。
每次成功读到 chunk 后计时器重置；若超过 idle_timeout 仍未收到新 chunk，
则抛出 StreamIdleTimeoutError，提示调用方及时采取回退或重试策略。
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import TypeVar

T = TypeVar("T")


class StreamIdleTimeoutError(asyncio.TimeoutError):
    """当流在空闲超时时间内未产生任何 chunk 时抛出的异常。"""


async def wrap_stream_idle_timeout(
    stream: AsyncIterator[T],
    idle_timeout: float,
) -> AsyncIterator[T]:
    """为异步生成器包装空闲超时检测。

    每成功读取一个 chunk 都会重置计时器；若在 *idle_timeout* 秒内未收到新 chunk，
    则抛出 ``StreamIdleTimeoutError``。

    参数:
        stream: 原始的异步生成器（流）。
        idle_timeout: 两次 chunk 之间的最大允许间隔（秒）。
    """
    while True:
        try:
            chunk = await asyncio.wait_for(
                stream.__anext__(),
                timeout=idle_timeout,
            )
            yield chunk
        except TimeoutError:
            raise StreamIdleTimeoutError(
                f"Stream idle timeout: no chunk for {idle_timeout}s. "
                f"The model may be stalled on a large tool call or response."
            )
        except StopAsyncIteration:
            return