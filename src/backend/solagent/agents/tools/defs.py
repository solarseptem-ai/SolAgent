"""Tool definition base class. 对标 grok-build Tool trait：类型安全 + 流式 + 动态描述。"""
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Generic, TypeVar

from pydantic import BaseModel

from solagent.schema.tools import (
    ToolCallContext,
    ToolExecutionMode,
    ToolListContext,
    ToolResult,
    ToolStreamItem,
)

TParams = TypeVar("TParams", bound=BaseModel)


class ToolDef(Generic[TParams], ABC):
    """工具定义基类。泛型参数 TParams 为 Pydantic 模型，自动生成 JSON Schema。"""

    # ── 子类必须覆盖 ──
    id: str
    description: str
    params_model: type[TParams]

    # ── 子类可选覆盖 ──
    execution_mode: ToolExecutionMode = ToolExecutionMode.SEQUENTIAL
    sandboxed: bool = False
    cache_ttl: float = 0  # 0=不缓存, -1=会话级, >0=TTL秒数
    streamable: bool = False
    return_directly: bool = False
    concurrency_safe: bool = True  # True=可并行, False=独占（如 shell 写文件）

    @abstractmethod
    async def execute(self, params: TParams, ctx: ToolCallContext) -> ToolResult:
        ...

    async def execute_stream(
        self, params: TParams, ctx: ToolCallContext
    ) -> AsyncGenerator[ToolStreamItem, None]:
        result = await self.execute(params, ctx)
        yield ToolStreamItem(type="terminal", result=result)

    def should_show(self, ctx: ToolListContext) -> bool:
        return True

    def dynamic_description(self, ctx: ToolListContext) -> str:
        return self.description

    @property
    def json_schema(self) -> dict:
        return self.params_model.model_json_schema()