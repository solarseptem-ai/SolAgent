"""LLM 工厂模块。

根据模型名称自动查找并创建对应的 LLMProvider 实例，
同时负责凭证解析器的初始化与注册，是上层业务创建 LLM 服务的主要入口。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from solagent.llms.providers.base import LLMProvider
from solagent.llms.providers.registry import get_registry

if TYPE_CHECKING:
    from solagent.llms.credentials import CredentialResolver


class LLMFactory:
    """LLM 工厂类，封装了提供商注册表的自动发现与凭证解析逻辑。

    属性:
        _registry: 提供商注册表实例，维护所有可用提供商的配置信息。
        _resolver: 凭证解析器，用于从环境变量等来源获取 API 密钥。
    """

    def __init__(self, resolver: "CredentialResolver | None" = None):
        # 初始化注册表并触发自动发现，加载所有已配置的提供商
        self._registry = get_registry()
        self._registry.auto_register_discovered()
        if resolver is None:
            from solagent.llms.credentials import CredentialResolver, EnvCredentialStore

            # 默认使用环境变量作为凭证来源
            self._resolver = CredentialResolver(EnvCredentialStore())
        else:
            self._resolver = resolver

    def create(self, model: str) -> LLMProvider:
        """根据模型名称创建并返回对应的 LLMProvider 实例。

        参数:
            model: 目标模型名称，如 "gpt-4o"。

        异常:
            KeyError: 找不到支持该模型的提供商时抛出。
        """
        profile = self._registry.find_by_model(model)
        if profile is None:
            available = [p.name for p in self._registry.list_profiles()]
            raise KeyError(f"No provider found for model: {model}. Available providers: {available}")
        return self._registry.get_provider(profile.name)

    def list_providers(self) -> list:
        """返回当前注册表中所有已注册的提供商配置列表。"""
        return self._registry.list_profiles()

    def get_api_key(self, provider_name: str) -> str | None:
        """获取指定提供商的 API 密钥明文，若未配置则返回 None。"""
        key = self._resolver.resolve_api_key(provider_name)
        return key.get_secret_value() if key else None

    @property
    def resolver(self) -> "CredentialResolver":
        """返回当前工厂使用的凭证解析器。"""
        return self._resolver