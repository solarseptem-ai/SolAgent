"""提示词模板注册表。

提供 PromptTemplate 的全局单例注册表，支持按名称检索、按分类过滤、批量注册等操作。
内置模板在注册表初始化时自动加载，运行时也可动态注册自定义模板。
"""

from __future__ import annotations

import logging

from solagent.prompts.models import PromptTemplate

_logger = logging.getLogger(__name__)

_registry: PromptRegistry | None = None


def get_prompt_registry() -> PromptRegistry:
    """获取全局 PromptRegistry 单例实例。"""
    global _registry
    if _registry is None:
        _registry = PromptRegistry()
    return _registry


class PromptRegistry:
    """提示词模板注册表，集中管理所有可用的 PromptTemplate。

    初始化时自动加载 builtins 中的内置模板，支持运行时动态增删。
    """
    def __init__(self):
        """初始化注册表并加载内置模板。"""
        self._templates: dict[str, PromptTemplate] = {}
        self._load_builtins()

    def _load_builtins(self) -> None:
        """从 builtins 模块加载所有预置模板到注册表。"""
        from solagent.prompts.builtins import BUILTIN_TEMPLATES
        for template in BUILTIN_TEMPLATES:
            self.register(template)

    def register(self, template: PromptTemplate) -> None:
        """注册一个提示词模板，以模板名作为唯一键。"""
        self._templates[template.name] = template

    def get(self, name: str) -> PromptTemplate | None:
        """按名称获取已注册的模板，不存在时返回 None。"""
        return self._templates.get(name)

    def list_names(self) -> list[str]:
        """返回所有已注册模板的名称列表。"""
        return list(self._templates.keys())

    def list_all(self) -> list[PromptTemplate]:
        """返回所有已注册的模板对象列表。"""
        return list(self._templates.values())

    def list_by_category(self, category: str) -> list[PromptTemplate]:
        """按分类过滤并返回对应的模板列表。"""
        return [t for t in self._templates.values() if t.category == category]

    def __len__(self) -> int:
        """返回当前注册表中模板的总数。"""
        return len(self._templates)