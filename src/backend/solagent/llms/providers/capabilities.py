"""模型能力声明模块。

定义模型家族枚举和各模型的能力参数（如最大输入/输出 token、是否支持视觉、
工具调用、流式输出、推理模式等），用于在运行时判断模型特性并做相应适配。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ModelFamily(str, Enum):
    """主流 LLM 模型家族枚举。"""
    GPT = "gpt"
    CLAUDE = "claude"
    GEMINI = "gemini"
    DEEPSEEK = "deepseek"
    QWEN = "qwen"
    UNKNOWN = "unknown"


@dataclass
class ModelCapabilities:
    """模型能力声明，描述特定模型支持的功能和限制。

    属性:
        family: 模型所属家族。
        max_input_tokens: 最大输入 token 数。
        max_output_tokens: 最大输出 token 数。
        supports_vision: 是否支持图像输入（多模态）。
        supports_tools: 是否支持函数/工具调用。
        supports_json_output: 是否支持原生 JSON 模式输出。
        supports_streaming: 是否支持流式响应。
        supports_thinking: 是否支持 reasoning/thinking 内容输出。
    """

    family: ModelFamily = ModelFamily.UNKNOWN
    max_input_tokens: int = 128000
    max_output_tokens: int = 4096
    supports_vision: bool = False
    supports_tools: bool = True
    supports_json_output: bool = False
    supports_streaming: bool = True
    supports_thinking: bool = False


# 预置的常用模型能力表，键为模型名称前缀，用于模糊匹配
MODEL_CAPABILITIES: dict[str, ModelCapabilities] = {
    "gpt-4o": ModelCapabilities(
        family=ModelFamily.GPT, max_input_tokens=128000, max_output_tokens=16384, supports_vision=True, supports_json_output=True
    ),
    "gpt-4o-mini": ModelCapabilities(
        family=ModelFamily.GPT, max_input_tokens=128000, max_output_tokens=16384, supports_vision=True, supports_json_output=True
    ),
    "gpt-4-turbo": ModelCapabilities(
        family=ModelFamily.GPT, max_input_tokens=128000, max_output_tokens=4096, supports_vision=True
    ),
    "gpt-3.5-turbo": ModelCapabilities(
        family=ModelFamily.GPT, max_input_tokens=16385, max_output_tokens=4096
    ),
    "claude-3-5-sonnet": ModelCapabilities(
        family=ModelFamily.CLAUDE, max_input_tokens=200000, max_output_tokens=8192, supports_vision=True
    ),
    "claude-3-opus": ModelCapabilities(
        family=ModelFamily.CLAUDE, max_input_tokens=200000, max_output_tokens=4096, supports_vision=True
    ),
    "deepseek-v3": ModelCapabilities(
        family=ModelFamily.DEEPSEEK, max_input_tokens=128000, max_output_tokens=8192
    ),
    "deepseek-r1": ModelCapabilities(
        family=ModelFamily.DEEPSEEK, max_input_tokens=128000, max_output_tokens=8192, supports_thinking=True
    ),
    "qwen3": ModelCapabilities(
        family=ModelFamily.QWEN, max_input_tokens=128000, max_output_tokens=8192, supports_thinking=True
    ),
}


def get_model_capabilities(model: str) -> ModelCapabilities:
    """根据模型名称获取对应的能力声明，支持前缀模糊匹配。

    若未命中任何已知模型，则返回默认能力配置。
    """
    for key, caps in MODEL_CAPABILITIES.items():
        if key in model.lower():
            return caps
    return ModelCapabilities()