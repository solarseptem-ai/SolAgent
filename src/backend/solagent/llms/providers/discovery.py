"""LLM 提供商自动发现模块。

根据系统环境变量（如 API 密钥、基础地址）自动检测和识别可用的 LLM 提供商，
支持通过密钥前缀进行二次校验，减少手动配置成本。
"""
from __future__ import annotations

import os

from solagent.llms.providers.profile import ProviderProfile

# 提供商自动检测规则：每个规则定义了环境变量名、基础地址变量、默认值及模型列表等
_DETECTION_RULES: list[dict] = [
    {"env_key": "OPENAI_API_KEY", "base_url_env": "OPENAI_BASE_URL", "default_base_url": "https://api.openai.com/v1",
     "name": "openai", "display_name": "OpenAI", "api_mode": "chat_completions",
     "default_model": "gpt-4o", "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo", "o1", "o3-mini"],
     "supports_vision": True, "supports_thinking": True},
    {"env_key": "ANTHROPIC_API_KEY", "base_url_env": "ANTHROPIC_BASE_URL", "default_base_url": "https://api.anthropic.com",
     "name": "anthropic", "display_name": "Anthropic", "api_mode": "anthropic_messages",
     "default_model": "claude-3-5-sonnet-20241022",
     "models": ["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022", "claude-3-opus-20240229"],
     "supports_vision": True, "supports_thinking": True},
    {"env_key": "DEEPSEEK_API_KEY", "base_url_env": "DEEPSEEK_BASE_URL", "default_base_url": "https://api.deepseek.com/v1",
     "name": "deepseek", "display_name": "DeepSeek", "api_mode": "chat_completions",
     "default_model": "deepseek-chat", "models": ["deepseek-chat", "deepseek-reasoner"],
     "supports_vision": False, "supports_thinking": True},
    {"env_key": "GROQ_API_KEY", "base_url_env": "GROQ_BASE_URL", "default_base_url": "https://api.groq.com/openai/v1",
     "name": "groq", "display_name": "Groq", "api_mode": "chat_completions",
     "default_model": "llama-3.3-70b-versatile", "models": ["llama-3.3-70b-versatile", "mixtral-8x7b-32768"],
     "supports_vision": False, "supports_thinking": False},
    {"env_key": "TOGETHER_API_KEY", "base_url_env": "TOGETHER_BASE_URL", "default_base_url": "https://api.together.xyz/v1",
     "name": "together", "display_name": "Together AI", "api_mode": "chat_completions",
     "default_model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
     "models": ["meta-llama/Llama-3.3-70B-Instruct-Turbo", "mistralai/Mixtral-8x7B-Instruct-v0.1"],
     "supports_vision": False, "supports_thinking": False},
    {"env_key": "OPENROUTER_API_KEY", "base_url_env": "OPENROUTER_BASE_URL", "default_base_url": "https://openrouter.ai/api/v1",
     "name": "openrouter", "display_name": "OpenRouter", "api_mode": "chat_completions",
     "default_model": "openai/gpt-4o", "models": ["openai/gpt-4o", "anthropic/claude-3.5-sonnet"],
     "supports_vision": True, "supports_thinking": True},
    {"env_key": "OLLAMA_HOST", "base_url_env": "OLLAMA_HOST", "default_base_url": "http://localhost:11434/v1",
     "name": "ollama", "display_name": "Ollama", "api_mode": "chat_completions",
     "default_model": "llama3", "models": ["llama3", "llama3:70b", "mistral", "codellama"],
     "supports_vision": False, "supports_thinking": False},
    {"env_key": "GEMINI_API_KEY", "base_url_env": "GEMINI_BASE_URL", "default_base_url": "https://generativelanguage.googleapis.com/v1beta",
     "name": "gemini", "display_name": "Google Gemini", "api_mode": "chat_completions",
     "default_model": "gemini-2.0-flash", "models": ["gemini-2.0-flash", "gemini-2.0-pro"],
     "supports_vision": True, "supports_thinking": False},
{"env_key": "AZURE_OPENAI_API_KEY", "base_url_env": "AZURE_OPENAI_ENDPOINT", "default_base_url": "",
      "name": "azure", "display_name": "Azure OpenAI", "api_mode": "chat_completions",
      "default_model": "gpt-4o", "models": ["gpt-4o", "gpt-4o-mini"],
      "supports_vision": True, "supports_thinking": False},
     {"env_key": "FINNA_API_KEY", "base_url_env": "FINNA_BASE_URL", "default_base_url": "https://www.finna.com.cn/v1",
      "name": "finna", "display_name": "Finna", "api_mode": "chat_completions",
      "default_model": "qwen3-8b", "models": ["qwen3-8b", "qwen3-32b", "qwen3-235b", "deepseek-v3", "deepseek-r1"],
      "supports_vision": False, "supports_thinking": True},
]

# 网关类提供商的 API 密钥前缀到提供商名称的映射，用于前缀二次校验
_KEY_PREFIX_MAP: dict[str, str] = {
    "sk-or-": "openrouter",
    "sk-ant-": "anthropic",
    "app-": "finna",
}


def _detect_by_key_prefix() -> list[ProviderProfile]:
    """通过 API 密钥前缀检测特定网关提供商，避免误识别。"""
    results = []
    for env_key, prefix in [
        ("OPENROUTER_API_KEY", "sk-or-"),
        ("ANTHROPIC_API_KEY", "sk-ant-"),
        ("FINNA_API_KEY", "app-"),
    ]:
        val = os.getenv(env_key, "")
        if val.startswith(prefix):
            for rule in _DETECTION_RULES:
                if rule["name"] == _KEY_PREFIX_MAP.get(prefix, ""):
                    results.append(_build_profile(rule, val))
    return results


def _build_profile(rule: dict, api_key: str = "") -> ProviderProfile:
    """根据检测规则和密钥值构建 ProviderProfile 实例。"""
    base_url = os.getenv(rule["base_url_env"], rule["default_base_url"])
    return ProviderProfile(
        name=rule["name"], display_name=rule["display_name"], api_mode=rule["api_mode"],
        base_url=base_url, env_key=rule["env_key"], api_key=api_key or None,
        default_model=rule["default_model"], models=list(rule["models"]),
        supports_vision=rule["supports_vision"], supports_tools=True, supports_streaming=True,
        supports_thinking=rule["supports_thinking"],
    )


def discover_providers() -> list[ProviderProfile]:
    """扫描环境变量，自动发现并返回所有可用提供商的配置画像列表。"""
    discovered = []
    for rule in _DETECTION_RULES:
        if os.getenv(rule["env_key"]):
            discovered.append(_build_profile(rule, os.getenv(rule["env_key"], "")))
    prefix_detected = _detect_by_key_prefix()
    for p in prefix_detected:
        if p.name not in [d.name for d in discovered]:
            discovered.append(p)
    return discovered


def discover_provider_names() -> list[str]:
    """返回自动发现的提供商名称列表。"""
    return [p.name for p in discover_providers()]