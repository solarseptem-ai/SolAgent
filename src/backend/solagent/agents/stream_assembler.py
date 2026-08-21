"""流式 chunk → 完整 assistant 消息组装器。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from solagent.schema.llm import LLMFinishReason, LLMStreamChunk
from solagent.schema.messages import ToolCallBlock


def _safe_json_parse(raw: str) -> dict:
    try:
        return json.loads(raw)
    except Exception:
        return {}


@dataclass
class StreamAssembler:
    """流式 LLMStreamChunk → (full_content, list[ToolCallBlock]) 组装器。

    按 tool_call_id 聚合流式工具调用分片，build() 返回解析后的 content 和 ToolCallBlock 列表。
    """

    _text: str = ""
    _reasoning: str = ""
    _has_content: bool = False
    _tool_calls: dict[str, dict] = field(default_factory=dict)
    _tool_call_order: list[str] = field(default_factory=list)
    _finish: LLMFinishReason | None = None

    def push(self, chunk: LLMStreamChunk) -> None:
        if chunk.content:
            self._text += chunk.content
            self._has_content = True
        elif chunk.reasoning_content:
            self._reasoning += chunk.reasoning_content
        if chunk.tool_call_id:
            tid = chunk.tool_call_id
            if tid not in self._tool_calls:
                self._tool_calls[tid] = {"id": tid, "name": "", "arguments": ""}
                self._tool_call_order.append(tid)
            if chunk.tool_call_name:
                self._tool_calls[tid]["name"] = chunk.tool_call_name
            if chunk.tool_call_arguments:
                self._tool_calls[tid]["arguments"] += chunk.tool_call_arguments
        if chunk.finish_reason:
            self._finish = chunk.finish_reason

    def build(self) -> tuple[str, list[ToolCallBlock]]:
        calls = []
        for tid in self._tool_call_order:
            tc = self._tool_calls[tid]
            calls.append(ToolCallBlock(
                type="tool_call",
                id=tc["id"],
                name=tc["name"],
                arguments=_safe_json_parse(tc["arguments"]),
            ))
        text = self._text if self._has_content else self._reasoning
        return text, calls

    @property
    def has_tool_calls(self) -> bool:
        return bool(self._tool_calls)

    @property
    def text(self) -> str:
        return self._text if self._has_content else self._reasoning

    @property
    def finish_reason(self) -> LLMFinishReason | None:
        return self._finish