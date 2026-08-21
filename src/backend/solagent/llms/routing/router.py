"""模型路由器：根据模型名称解析对应的 LLMProvider 实例。

内部通过 ProviderRegistry 查找模型所属的提供商配置，再延迟初始化并返回实际的 provider 对象。
常用于在运行时根据用户指定的模型名称动态切换后端服务。
"""
from solagent.llms.providers.base import LLMProvider
from solagent.llms.providers.registry import get_registry


class ModelRouter:
    """模型路由器，将模型名称映射到已注册的 LLMProvider。

    属性:
        _registry: 全局 ProviderRegistry 实例，用于查询模型与 provider 的映射关系。
    """

    def __init__(self):
        self._registry = get_registry()

    def resolve(self, model: str) -> LLMProvider:
        """根据模型名称解析对应的 LLMProvider。

        参数:
            model: 模型名称，例如 "gpt-4o"、"claude-3-opus" 等。

        返回:
            该模型对应的 LLMProvider 实例。

        异常:
            KeyError: 当未找到支持该模型的提供商时抛出。
        """
        profile = self._registry.find_by_model(model)
        if profile is None:
            raise KeyError(f"No provider found for model: {model}")
        return self._registry.get_provider(profile.name)
