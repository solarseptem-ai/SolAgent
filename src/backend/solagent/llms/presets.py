"""LLM 模型预设配置模块。

预定义了若干常用的模型分组（如快速响应、最强推理、最低成本、视觉能力等），
方便上层业务根据场景快速选用合适的模型集合，而无需逐个指定模型名称。
"""
from dataclasses import dataclass


@dataclass
class ModelPreset:
    """模型预设分组，描述一组在特定场景下推荐的模型。

    属性:
        name: 预设标识名，如 "fast"。
        description: 预设的用途说明。
        models: 该预设包含的模型名称列表，按推荐程度排序。
    """
    name: str
    description: str
    models: list[str]


# 预定义的模型分组，便于按场景快速选型
PRESETS = {
    "fast": ModelPreset(name="fast", description="Fastest response time", models=["gpt-4o-mini", "gpt-3.5-turbo", "claude-3-haiku"]),
    "strong": ModelPreset(name="strong", description="Best reasoning quality", models=["gpt-4o", "claude-3-5-sonnet", "deepseek-reasoner"]),
    "cheap": ModelPreset(name="cheap", description="Lowest cost per token", models=["gpt-4o-mini", "deepseek-chat", "gpt-3.5-turbo"]),
    "vision": ModelPreset(name="vision", description="Vision-capable models", models=["gpt-4o", "claude-3-5-sonnet"]),
}


def get_preset(name: str) -> ModelPreset:
    """根据预设名称获取对应的 ModelPreset 实例。

    参数:
        name: 预设名称，如 "fast"。

    异常:
        KeyError: 预设名称不存在时抛出，同时提示所有可用预设。
    """
    if name not in PRESETS:
        raise KeyError(f"Preset '{name}' not found. Available: {list(PRESETS.keys())}")
    return PRESETS[name]