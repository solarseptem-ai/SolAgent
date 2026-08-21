"""LLM 流式响应处理模块。

提供 StreamHandler 用于收集流式 chunk 并转换为统一的 StreamEvent，
便于前端或上层业务消费 LLM 的流式输出。
"""
from solagent.llms.stream.handler import StreamHandler

__all__ = ["StreamHandler"]