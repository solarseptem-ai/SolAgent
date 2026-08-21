"""LLM 可观测性子包的入口模块。

导出 LLMTracer，用于追踪 LLM 调用记录、延迟和 token 消耗，并支持接入外部可观测平台。
"""
from solagent.llms.observability.tracer import LLMTracer

__all__ = ["LLMTracer"]