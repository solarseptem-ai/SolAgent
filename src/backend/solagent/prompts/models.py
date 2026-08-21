"""提示词模板的数据模型。

定义 PromptVariable（模板变量）和 PromptTemplate（提示词模板）两个核心模型，
支持变量默认值、渲染替换等基础功能，为 Agent 构建动态系统提示词提供数据层支持。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PromptVariable(BaseModel):
    """提示词模板中的变量定义。

    属性:
        name: 变量名，在模板中以 {{name}} 形式引用。
        description: 变量的用途说明。
        default: 未提供值时的默认填充内容。
        required: 是否必须显式提供值。
    """
    name: str
    description: str = ""
    default: str = ""
    required: bool = False


class PromptTemplate(BaseModel):
    """提示词模板定义。

    将一段带有占位变量的系统提示词封装为可复用模板，支持按上下文渲染为最终文本。

    属性:
        name: 模板唯一标识名。
        description: 模板的用途简述。
        version: 语义化版本号，用于模板升级管理。
        template: 模板原文，使用 {{variable}} 语法嵌入变量。
        variables: 该模板所需变量的定义列表。
        category: 分类（如 general、development、creative），便于按场景检索。
        tags: 标签列表，用于进一步筛选和搜索。
    """

    name: str
    description: str = ""
    version: str = "1.0.0"
    template: str = ""
    variables: list[PromptVariable] = Field(default_factory=list)
    category: str = "general"
    tags: list[str] = Field(default_factory=list)

    def render(self, context: dict | None = None) -> str:
        """按上下文渲染模板，将变量占位符替换为实际值。

        参数:
            context: 变量名到值的映射字典。若某个变量未提供，则使用其默认值。

        返回:
            渲染后的完整提示词文本。
        """
        ctx = context or {}
        result = self.template
        for var in self.variables:
            value = ctx.get(var.name, var.default)
            placeholder = "{{" + var.name + "}}"
            result = result.replace(placeholder, str(value))
        return result