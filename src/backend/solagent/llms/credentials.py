"""LLM 提供商凭证管理模块。

定义各 LLM 提供商所需的凭证模型，提供从环境变量、YAML 文件等来源读取凭证的能力，
并支持链式存储与自动解析，方便在运行时安全地获取 API 密钥等敏感信息。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, ClassVar

import yaml
from pydantic import BaseModel, SecretStr

from solagent.schema.credentials import CredentialStore


class OpenAICredential(BaseModel):
    """OpenAI 提供商的凭证配置。"""
    api_key: SecretStr
    organization: str | None = None
    base_url: str = "https://api.openai.com/v1"


class AnthropicCredential(BaseModel):
    """Anthropic 提供商的凭证配置。"""
    api_key: SecretStr
    base_url: str = "https://api.anthropic.com"


class DeepSeekCredential(BaseModel):
    """DeepSeek 提供商的凭证配置。"""
    api_key: SecretStr
    base_url: str = "https://api.deepseek.com"


class AzureCredential(BaseModel):
    """Azure OpenAI 提供商的凭证配置。"""
    api_key: SecretStr
    endpoint: str
    api_version: str = "2024-02-15-preview"


class OllamaCredential(BaseModel):
    """Ollama 本地部署提供商的凭证配置（仅需主机地址）。"""
    host: str = "http://localhost:11434"


class GeminiCredential(BaseModel):
    """Google Gemini 提供商的凭证配置。"""
    api_key: SecretStr


class GroqCredential(BaseModel):
    """Groq 提供商的凭证配置。"""
    api_key: SecretStr


class OpenRouterCredential(BaseModel):
    """OpenRouter 提供商的凭证配置。"""
    api_key: SecretStr


class TogetherCredential(BaseModel):
    """Together AI 提供商的凭证配置。"""
    api_key: SecretStr


class FinnaCredential(BaseModel):
    """Finna 提供商的凭证配置。"""
    api_key: SecretStr


# 提供商名称到对应凭证模型的映射表，用于自动解析
CREDENTIAL_REGISTRY: dict[str, type[BaseModel]] = {
    "openai": OpenAICredential,
    "anthropic": AnthropicCredential,
    "deepseek": DeepSeekCredential,
    "azure": AzureCredential,
    "ollama": OllamaCredential,
    "gemini": GeminiCredential,
    "groq": GroqCredential,
    "openrouter": OpenRouterCredential,
    "together": TogetherCredential,
    "finna": FinnaCredential,
}


class EnvCredentialStore:
    """从系统环境变量中读取 LLM 提供商凭证的存储器。

    属性:
        _ENV_MAP: 提供商名称与环境变量名的映射表。
    """

    _ENV_MAP: ClassVar[dict[str, str]] = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "azure": "AZURE_OPENAI_API_KEY",
        "ollama": "OLLAMA_HOST",
        "gemini": "GEMINI_API_KEY",
        "groq": "GROQ_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "together": "TOGETHER_API_KEY",
        "finna": "FINNA_API_KEY",
    }

    def get(self, provider: str) -> dict[str, Any] | None:
        """获取指定提供商的环境变量凭证，若未设置则返回 None。"""
        env_var = self._ENV_MAP.get(provider)
        if not env_var:
            return None
        value = os.environ.get(env_var)
        if not value:
            return None
        return {"api_key": value}

    def list_providers(self) -> set[str]:
        """返回当前环境变量中已配置的所有提供商名称集合。"""
        return {p for p, env in self._ENV_MAP.items() if os.environ.get(env)}


class FileCredentialStore:
    """从 YAML 文件中读取 LLM 提供商凭证的存储器。

    属性:
        _path: 凭证文件路径。
        _data: 解析后的凭证字典。
    """

    def __init__(self, path: Path):
        self._path = path
        self._data: dict[str, Any] = {}
        if path.exists():
            self._data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def get(self, provider: str) -> dict[str, Any] | None:
        """从 YAML 文件中获取指定提供商的凭证配置。"""
        return self._data.get(provider)

    def list_providers(self) -> set[str]:
        """返回 YAML 文件中已配置的所有提供商名称集合。"""
        return set(self._data.keys())


class ChainCredentialStore:
    """链式凭证存储器，按优先级依次查询多个存储源，返回第一个命中结果。

    属性:
        _stores: 多个 CredentialStore 实例组成的元组。
    """

    def __init__(self, *stores: CredentialStore):
        self._stores = stores

    def get(self, provider: str) -> dict[str, Any] | None:
        """按顺序在多个存储器中查找指定提供商的凭证，直到命中为止。"""
        for store in self._stores:
            data = store.get(provider)
            if data:
                return data
        return None

    def list_providers(self) -> set[str]:
        """返回所有存储器中已配置提供商的并集。"""
        result: set[str] = set()
        for store in self._stores:
            result |= store.list_providers()
        return result


class CredentialResolver:
    """凭证解析器，将存储器中的原始数据转换为对应的 Pydantic 凭证模型。

    属性:
        _store: 底层凭证存储器。
    """

    def __init__(self, store: CredentialStore):
        self._store = store

    def resolve(self, provider: str) -> BaseModel | None:
        """根据提供商名称解析并返回对应的凭证模型实例。"""
        model_cls = CREDENTIAL_REGISTRY.get(provider)
        if not model_cls:
            return None
        data = self._store.get(provider)
        if not data:
            return None
        return model_cls.model_validate(data)

    def resolve_api_key(self, provider: str) -> SecretStr | None:
        """解析并返回指定提供商的 API 密钥（以 SecretStr 安全封装）。"""
        cred = self.resolve(provider)
        if cred is None:
            return None
        api_key = getattr(cred, "api_key", None)
        return api_key if isinstance(api_key, SecretStr) else None