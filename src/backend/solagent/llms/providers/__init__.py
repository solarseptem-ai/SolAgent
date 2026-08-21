"""LLM 提供商子包的统一入口模块。

导出所有与 LLM 提供商相关的核心类和函数，包括抽象基类、能力声明、
自动发现、配置画像和注册表管理，方便上层统一引用。
"""
from solagent.llms.providers.base import LLMProvider
from solagent.llms.providers.capabilities import ModelCapabilities, get_model_capabilities
from solagent.llms.providers.discovery import discover_providers
from solagent.llms.providers.profile import ProviderProfile
from solagent.llms.providers.registry import ProviderRegistry, get_registry, reset_registry

__all__ = [
    "LLMProvider",
    "ModelCapabilities",
    "ProviderProfile",
    "ProviderRegistry",
    "discover_providers",
    "get_model_capabilities",
    "get_registry",
    "reset_registry",
]