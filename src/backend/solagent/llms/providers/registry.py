"""LLM 提供商注册表模块。

以延迟加载方式管理所有可用的 LLM 提供商，支持手动注册、自定义注册和自动环境发现，
并提供按模型名称反向查找提供商的能力。
"""
from __future__ import annotations

from collections.abc import Callable

from solagent.llms.providers.base import LLMProvider
from solagent.llms.providers.profile import ProviderProfile


class ProviderRegistry:
    """提供商注册表，延迟维护提供商配置画像和工厂函数。

    属性:
        _profiles: 提供商名称到 ProviderProfile 的映射。
        _factories: 提供商名称到无参工厂函数的映射，调用时返回 LLMProvider 实例。
    """

    def __init__(self) -> None:
        self._profiles: dict[str, ProviderProfile] = {}
        self._factories: dict[str, Callable[[], LLMProvider]] = {}

    def register(self, profile: ProviderProfile, factory: Callable[[], LLMProvider]) -> None:
        """注册一个提供商及其对应的工厂函数。"""
        self._profiles[profile.name] = profile
        self._factories[profile.name] = factory

    def register_custom(self, profile: ProviderProfile, api_key: str | None = None) -> LLMProvider:
        """注册一个自定义提供商并直接实例化返回，便于立即可用。"""
        from solagent.llms.providers.custom import CustomProvider
        provider = CustomProvider(profile, api_key=api_key)
        self._profiles[profile.name] = profile
        self._factories[profile.name] = lambda: provider
        return provider

    def unregister(self, name: str) -> bool:
        """从注册表中移除指定提供商，返回是否成功移除。"""
        removed = name in self._profiles
        self._profiles.pop(name, None)
        self._factories.pop(name, None)
        return removed

    def has_provider(self, name: str) -> bool:
        """检查指定名称的提供商是否已注册。"""
        return name in self._profiles

    def get_profile(self, name: str) -> ProviderProfile:
        """获取指定提供商的配置画像，不存在时抛出 KeyError。"""
        if name not in self._profiles:
            raise KeyError(f"Provider '{name}' not found. Available: {list(self._profiles.keys())}")
        return self._profiles[name]

    def get_provider(self, name: str) -> LLMProvider:
        """通过工厂函数实例化并返回指定名称的提供商，不存在时抛出 KeyError。"""
        if name not in self._factories:
            raise KeyError(f"Provider '{name}' not found")
        return self._factories[name]()

    def list_profiles(self) -> list[ProviderProfile]:
        """返回所有已注册提供商的配置画像列表。"""
        return list(self._profiles.values())

    def list_models(self, name: str) -> list[str]:
        """获取指定提供商支持的所有模型名称列表。"""
        profile = self.get_profile(name)
        return list(profile.models)

    def add_model(self, provider_name: str, model_name: str) -> None:
        """向指定提供商的模型列表中添加一个模型。"""
        profile = self.get_profile(provider_name)
        profile.add_model(model_name)

    def remove_model(self, provider_name: str, model_name: str) -> None:
        """从指定提供商的模型列表中移除一个模型。"""
        profile = self.get_profile(provider_name)
        profile.remove_model(model_name)

    def find_by_model(self, model_name: str) -> ProviderProfile | None:
        """根据模型名称反向查找支持该模型的提供商，未找到返回 None。"""
        for profile in self._profiles.values():
            if model_name in profile.models:
                return profile
        return None

    def auto_register_discovered(self) -> int:
        """自动从环境变量发现可用提供商并注册到注册表，返回注册成功的数量。"""
        from solagent.llms.providers.anthropic import AnthropicProvider
        from solagent.llms.providers.discovery import discover_providers
        from solagent.llms.providers.openai import OpenAIProvider

        # 内置提供商的工厂映射，用于优先实例化原生支持的提供商
        _BUILTIN_FACTORIES = {
            "openai": lambda: OpenAIProvider(),
            "anthropic": lambda: AnthropicProvider(),
        }

        count = 0
        profiles = discover_providers()
        for profile in profiles:
            if profile.name in self._profiles:
                continue
            if profile.name in _BUILTIN_FACTORIES:
                self.register(profile, _BUILTIN_FACTORIES[profile.name])
            else:
                self.register_custom(profile)
            count += 1
        return count


# 模块级注册表单例
_registry: ProviderRegistry | None = None


def get_registry() -> ProviderRegistry:
    """获取全局注册表单例，首次调用时自动初始化。"""
    global _registry
    if _registry is None:
        _registry = ProviderRegistry()
    return _registry


def reset_registry() -> None:
    """重置全局注册表单例，常用于测试场景。"""
    global _registry
    _registry = None