"""LLM 提供商配置画像模块。

定义 ProviderProfile 数据类，以声明式方式描述一个 LLM 提供商的各项配置参数，
包括 API 模式、基础地址、支持模型、功能开关及可选的消息预处理钩子。
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class ProviderProfile:
    """提供商配置画像，描述一个 LLM 提供商的完整配置信息。

    属性:
        name: 提供商内部标识名。
        display_name: 对外展示的名称。
        api_mode: API 调用模式，支持 OpenAI 兼容或 Anthropic Messages 格式。
        base_url: API 基础地址。
        env_key: 对应环境变量名（用于自动读取 API 密钥）。
        api_key: 显式指定的 API 密钥。
        default_model: 默认使用的模型名称。
        models: 该提供商支持的所有模型列表。
        supports_vision: 是否支持视觉/多模态。
        supports_tools: 是否支持工具调用。
        supports_streaming: 是否支持流式输出。
        supports_thinking: 是否支持 reasoning/thinking 内容。
        extra_headers: 需要附加到 API 请求中的额外请求头。
        extra_body: 需要附加到 API 请求体中的额外字段。
        prepare_messages: 可选的消息预处理钩子，签名: (messages: list[Message]) -> list[dict]。
    """

    name: str
    display_name: str
    api_mode: Literal["chat_completions", "anthropic_messages"] = "chat_completions"
    base_url: str = ""
    env_key: str = ""
    api_key: str | None = None
    default_model: str = ""
    models: list[str] = field(default_factory=list)
    supports_vision: bool = False
    supports_tools: bool = True
    supports_streaming: bool = True
    supports_thinking: bool = False
    extra_headers: dict[str, str] = field(default_factory=dict)
    extra_body: dict[str, Any] = field(default_factory=dict)
    prepare_messages: Callable[..., Any] | None = None  # 签名: (messages: list[Message]) -> list[dict]

    def add_model(self, model_name: str) -> None:
        """向该提供商的模型列表中添加一个模型（去重）。"""
        if model_name not in self.models:
            self.models.append(model_name)

    def remove_model(self, model_name: str) -> None:
        """从该提供商的模型列表中移除指定模型。"""
        if model_name in self.models:
            self.models.remove(model_name)

    def has_model(self, model_name: str) -> bool:
        """检查指定模型是否已注册到该提供商。"""
        return model_name in self.models