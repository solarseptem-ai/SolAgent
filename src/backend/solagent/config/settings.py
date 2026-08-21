"""Agent 环境变量设置。

基于 pydantic-settings 实现，支持从 .env 文件和环境变量读取配置。
所有配置项均带有 solagent_ 前缀，例如环境变量 SOLAGENT_DEFAULT_MODEL 会映射到 default_model。
"""

from pydantic_settings import BaseSettings


class AgentSettings(BaseSettings):
    """Agent 运行时设置，优先从环境变量和 .env 文件加载。

    Attributes:
        default_model: 默认使用的 LLM 模型名称。
        default_mode: 默认 Agent 运行模式。
        max_iterations: 最大迭代次数。
        max_tokens: 单次调用最大 Token 数。
        temperature: 默认采样温度。
        log_level: 日志级别。
        openai_api_key: OpenAI API 密钥。
        openai_base_url: OpenAI API 基础地址。
        anthropic_api_key: Anthropic API 密钥。
        deepseek_api_key: DeepSeek API 密钥。
    """

    model_config = {"env_prefix": "solagent_", "env_file": ".env", "extra": "ignore"}

    default_model: str = "gpt-4o"
    default_mode: str = "react"
    max_iterations: int = 10
    max_tokens: int = 4096
    temperature: float = 0.0
    log_level: str = "INFO"
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    anthropic_api_key: str | None = None
    deepseek_api_key: str | None = None