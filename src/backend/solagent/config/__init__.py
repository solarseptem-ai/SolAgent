"""SolAgent 配置系统模块。

提供应用级配置的数据模型、多层 YAML 配置加载、环境变量解析，
以及 ProviderConfig 到 ProviderRegistry 的桥接注册功能。
支持从默认值、用户目录和项目目录三层合并加载配置。
"""

from solagent.config.config_model import (
    AgentConfigBlock,
    AppConfig,
    GenerationConfig,
    LoggingConfig,
    MCPServerConfigBlock,
    ProviderConfig,
    SkillConfigBlock,
    ToolConfigBlock,
)
from solagent.config.loader import ConfigLoader
from solagent.config.provider_bridge import register_providers_from_config
from solagent.config.settings import AgentSettings

__all__ = [
    "AgentConfigBlock",
    "AgentSettings",
    "AppConfig",
    "ConfigLoader",
    "GenerationConfig",
    "LoggingConfig",
    "MCPServerConfigBlock",
    "ProviderConfig",
    "SkillConfigBlock",
    "ToolConfigBlock",
    "register_providers_from_config",
]
