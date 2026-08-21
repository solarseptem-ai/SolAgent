"""配置桥接模块，将 AppConfig 中的 ProviderConfig 块注册到 ProviderRegistry。

负责把 YAML 配置中的提供商定义转换为 ProviderProfile 对象，
并注册到全局 ProviderRegistry 中供 LLM 调用时使用。
支持自定义提供商类路径（use 字段）的动态导入。
"""
from __future__ import annotations

import importlib
import logging

_logger = logging.getLogger(__name__)

from solagent.config.config_model import AppConfig, ProviderConfig
from solagent.llms.providers.profile import ProviderProfile
from solagent.llms.providers.registry import ProviderRegistry


def _resolve_class(class_path: str) -> type:
    """根据类路径字符串动态导入并返回类对象。

    支持两种格式：
        - module.submodule:ClassName（冒号分隔）
        - module.submodule.ClassName（点分隔，取最后一个点）

    Args:
        class_path: 类路径字符串。

    Returns:
        导入的类对象。
    """
    if ":" in class_path:
        module_path, class_name = class_path.rsplit(":", 1)
    else:
        module_path, class_name = class_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def _provider_config_to_profile(pc: ProviderConfig) -> ProviderProfile:
    """将 ProviderConfig 转换为 ProviderProfile。

    ProviderProfile 是 LLM 层内部使用的标准化提供商描述对象。
    """
    return ProviderProfile(
        name=pc.name,
        display_name=pc.display_name,
        api_mode=pc.api_mode,  # type: ignore[arg-type]
        base_url=pc.base_url,
        env_key=pc.api_key_env,
        api_key=pc.api_key or None,
        default_model=pc.default_model,
        models=list(pc.models),
        extra_headers=dict(pc.extra_headers),
        extra_body=dict(pc.extra_body),
    )


def register_providers_from_config(
    app_config: AppConfig,
    registry: ProviderRegistry | None = None,
) -> int:
    """将 AppConfig 中定义的所有提供商注册到 ProviderRegistry。

    Args:
        app_config: 应用配置对象。
        registry: 目标注册表，None 则使用全局默认注册表。

    Returns:
        实际新注册的提供商数量（已存在的会跳过）。
    """
    if registry is None:
        from solagent.llms.providers.registry import get_registry
        registry = get_registry()

    count = 0
    for pc in app_config.providers:
        if registry.has_provider(pc.name):
            continue

        profile = _provider_config_to_profile(pc)

        if pc.use:
            # 尝试动态导入自定义提供商类
            try:
                provider_cls = _resolve_class(pc.use)
                provider = provider_cls(profile=profile, api_key=pc.api_key or None)
                registry.register(profile, lambda p=provider: p)
            except Exception:
                _logger.warning("Provider bridge config load failed", exc_info=True)
                registry.register_custom(profile, api_key=pc.api_key or None)
        else:
            registry.register_custom(profile, api_key=pc.api_key or None)

        count += 1

    return count