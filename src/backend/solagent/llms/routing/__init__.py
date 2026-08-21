"""LLM 请求路由模块，提供模型解析、故障转移和负载均衡能力。

- ModelRouter: 根据模型名称解析对应的 LLMProvider。
- FallbackChain: 当主提供商失败时，按顺序尝试备用提供商。
- LoadBalancer: 在多个提供商之间按策略分发请求，支持轮询、随机、最少使用和加权策略。
"""
from solagent.llms.routing.fallback import FallbackChain
from solagent.llms.routing.load_balancer import BalanceStrategy, LoadBalancer
from solagent.llms.routing.router import ModelRouter

__all__ = ["BalanceStrategy", "FallbackChain", "LoadBalancer", "ModelRouter"]
