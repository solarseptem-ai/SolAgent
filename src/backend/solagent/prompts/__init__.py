"""提示词模板模块的入口。

提供 PromptTemplate（提示词模板）、PromptVariable（模板变量）以及 PromptRegistry（模板注册表）
等核心组件，用于集中管理和渲染 Agent 运行时所需的各类系统提示词（system prompt）。
"""

from solagent.prompts.models import PromptTemplate, PromptVariable
from solagent.prompts.registry import PromptRegistry, get_prompt_registry

__all__ = ["PromptRegistry", "PromptTemplate", "PromptVariable", "get_prompt_registry"]