"""LLM 子系统的统一入口模块。

集中导出缓存、凭证、成本追踪、工厂、健康检查、流处理、结构化输出、
提供商注册与路由、重试策略等所有与 LLM 交互相关的公共类和函数，
方便上层业务通过单一导入点访问所需组件。
"""
from solagent.llms.cache import LLMCache
from solagent.llms.credentials import (
    ChainCredentialStore,
    CredentialResolver,
    EnvCredentialStore,
    FileCredentialStore,
    CREDENTIAL_REGISTRY,
    OpenAICredential,
    AnthropicCredential,
    DeepSeekCredential,
    AzureCredential,
    OllamaCredential,
    GeminiCredential,
    GroqCredential,
    OpenRouterCredential,
    TogetherCredential,
    FinnaCredential,
)
from solagent.llms.cost import CostRecord, CostTracker
from solagent.llms.factory import LLMFactory
from solagent.llms.format.converter import FormatConverter
from solagent.llms.health import HealthReport, HealthResult, check_all_health, check_provider_health
from solagent.llms.hotswap import ProviderWatcher
from solagent.llms.media.handler import MediaHandler
from solagent.llms.observability.tracer import LLMTracer
from solagent.llms.pipeline import (
    RequestPipeline,
    empty_content_sanitizer,
    get_default_pipeline,
    reasoning_content_injector,
)
from solagent.llms.presets import PRESETS, ModelPreset, get_preset
from solagent.llms.providers.anthropic import AnthropicProvider
from solagent.llms.providers.base import LLMProvider
from solagent.llms.providers.capabilities import ModelCapabilities, ModelFamily, get_model_capabilities
from solagent.llms.providers.custom import CustomProvider
from solagent.llms.providers.discovery import discover_provider_names, discover_providers
from solagent.llms.providers.hooks import ProviderHooks, anthropic_hooks, deepseek_thinking_hooks
from solagent.llms.providers.profile import ProviderProfile
from solagent.llms.providers.registry import ProviderRegistry, get_registry, reset_registry
from solagent.llms.retry.circuit_breaker import CircuitBreaker
from solagent.llms.retry.global_limiter import get_global_limiter
from solagent.llms.retry.policy import RetryPolicy, set_exception_budget
from solagent.llms.retry.rate_limiter import RateLimiter
from solagent.llms.routing.fallback import FallbackChain
from solagent.llms.routing.load_balancer import BalanceStrategy, LoadBalancer
from solagent.llms.routing.router import ModelRouter
from solagent.llms.stream.handler import StreamHandler
from solagent.llms.stream.thinking import ThinkingParser, ThinkingState
from solagent.llms.stream.timeout import StreamIdleTimeoutError, wrap_stream_idle_timeout
from solagent.llms.structured import (
    StructuredOutputError,
    StructuredOutputPipeline,
    build_response_format,
    chat_with_structured_output,
    parse_structured_output,
)
from solagent.llms.token_usage.budget import TokenBudget
from solagent.llms.token_usage.tracker import TokenUsageTracker

__all__ = [
    "PRESETS",
    "AnthropicCredential",
    "AnthropicProvider",
    "AzureCredential",
    "BalanceStrategy",
    "CREDENTIAL_REGISTRY",
    "ChainCredentialStore",
    "CircuitBreaker",
    "CostRecord",
    "CostTracker",
    "CredentialResolver",
    "CustomProvider",
    "DeepSeekCredential",
    "EnvCredentialStore",
    "FallbackChain",
    "FileCredentialStore",
    "FinnaCredential",
    "FormatConverter",
    "GeminiCredential",
    "GroqCredential",
    "HealthReport",
    "HealthResult",
    "LLMCache",
    "LLMFactory",
    "LLMProvider",
    "LLMTracer",
    "LoadBalancer",
    "MediaHandler",
    "ModelCapabilities",
    "ModelFamily",
    "ModelPreset",
    "ModelRouter",
    "OllamaCredential",
    "OpenAICredential",
    "OpenRouterCredential",
    "ProviderHooks",
    "ProviderProfile",
    "ProviderRegistry",
    "ProviderWatcher",
    "RateLimiter",
    "RequestPipeline",
    "RetryPolicy",
    "StreamHandler",
    "StreamIdleTimeoutError",
    "StructuredOutputError",
    "StructuredOutputPipeline",
    "ThinkingParser",
    "ThinkingState",
    "TogetherCredential",
    "TokenBudget",
    "TokenUsageTracker",
    "anthropic_hooks",
    "build_response_format",
    "chat_with_structured_output",
    "check_all_health",
    "check_provider_health",
    "deepseek_thinking_hooks",
    "discover_provider_names",
    "discover_providers",
    "empty_content_sanitizer",
    "get_default_pipeline",
    "get_global_limiter",
    "get_model_capabilities",
    "get_preset",
    "get_registry",
    "parse_structured_output",
    "reasoning_content_injector",
    "reset_registry",
    "set_exception_budget",
    "wrap_stream_idle_timeout",
]