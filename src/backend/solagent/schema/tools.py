"""工具系统相关的数据模型定义。

本模块提供了 Agent 工具注册、调用和结果返回所需的全部 Schema，
包括工具参数类型、工具定义、工具调用请求和结果等。这些模型支持
生成 OpenAI 和 Anthropic 等主流 LLM 所需的工具 Schema 格式，
实现工具描述的标准化和跨平台兼容。
"""
from __future__ import annotations

import json
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolParameterType(str, Enum):
    """工具参数的数据类型枚举，对应 JSON Schema 的基本类型。"""
    STRING = "string"    # 字符串类型
    NUMBER = "number"    # 数值类型（整数或浮点数）
    BOOLEAN = "boolean"  # 布尔类型
    OBJECT = "object"    # 对象/字典类型
    ARRAY = "array"      # 数组类型


class ToolParameter(BaseModel):
    """工具参数模型，描述单个参数的名称、类型和约束。

    属性说明：
        name: 参数名称。
        type: 参数的数据类型。
        description: 参数功能描述，供模型理解参数用途。
        required: 是否必填参数。
        enum: 枚举值列表，限制参数取值范围。
        properties: 当 type 为 OBJECT 时，定义对象的子属性。
        items: 当 type 为 ARRAY 时，定义数组元素的类型。
    """
    name: str
    type: ToolParameterType
    description: str | None = None
    required: bool = False
    enum: list[str] | None = None
    properties: dict[str, ToolParameter] | None = None
    items: ToolParameter | None = None

    def _to_schema_dict(self) -> dict[str, Any]:
        """将参数模型递归转换为符合 JSON Schema 规范的字典。

        该方法处理嵌套对象和数组类型，并自动收集 required 字段列表。
        """
        schema: dict[str, Any] = {"type": self.type.value}
        if self.description:
            schema["description"] = self.description
        if self.enum:
            schema["enum"] = self.enum
        if self.type == ToolParameterType.OBJECT and self.properties:
            # 递归转换子属性为 JSON Schema 格式
            schema["properties"] = {
                k: v._to_schema_dict() for k, v in self.properties.items()
            }
            # 自动收集所有标记为 required 的子属性名称
            required = [k for k, v in self.properties.items() if v.required]
            if required:
                schema["required"] = required
        if self.type == ToolParameterType.ARRAY and self.items:
            schema["items"] = self.items._to_schema_dict()
        return schema


class ToolSchema(BaseModel):
    """工具参数的整体 Schema 模型，用于描述工具输入的结构。

    属性说明：
        type: 根类型，固定为 "object"，表示工具参数是一个对象。
        properties: 对象属性的参数定义字典。
        required: 必填属性名称列表。
    """
    type: str = "object"
    properties: dict[str, ToolParameter] = Field(default_factory=dict)
    required: list[str] = Field(default_factory=list)


class ToolDefinition(BaseModel):
    """工具定义模型，完整描述一个可调用工具的元数据和参数结构。

    属性说明：
        name: 工具的唯一名称标识。
        description: 工具功能描述，模型据此判断何时调用该工具。
        parameters: 工具的参数列表。
    """
    model_config = {"frozen": True}

    name: str
    description: str
    parameters: list[ToolParameter] = Field(default_factory=list)

    def _build_schema(self) -> ToolSchema:
        """从参数列表构建内部 ToolSchema 表示，收集 properties 和 required 字段。"""
        properties: dict[str, ToolParameter] = {}
        required: list[str] = []
        for param in self.parameters:
            properties[param.name] = param
            if param.required:
                required.append(param.name)
        return ToolSchema(properties=properties, required=required)

    def to_openai_schema(self) -> dict[str, Any]:
        """转换为 OpenAI Function Calling 格式的工具 Schema 字典。"""
        schema = self._build_schema()
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": schema.type,
                    "properties": {
                        k: v._to_schema_dict() for k, v in schema.properties.items()
                    },
                    "required": schema.required,
                },
            },
        }

    def to_anthropic_schema(self) -> dict[str, Any]:
        """转换为 Anthropic Tool Use 格式的工具 Schema 字典。"""
        schema = self._build_schema()
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": schema.type,
                "properties": {
                    k: v._to_schema_dict() for k, v in schema.properties.items()
                },
                "required": schema.required,
            },
        }


class ToolCall(BaseModel):
    """工具调用请求模型，表示模型发起的一次工具调用。

    属性说明：
        id: 工具调用的唯一标识，用于关联后续结果。
        name: 被调用工具的名称。
        arguments: 工具调用的参数字典。
    """
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)

    @property
    def arguments_json(self) -> str:
        """将参数字典序列化为 JSON 字符串，保留非 ASCII 字符。"""
        return json.dumps(self.arguments, ensure_ascii=False)

    @classmethod
    def from_openai(cls, tool_call: Any) -> ToolCall:
        """从 OpenAI 的工具调用对象解析为内部 ToolCall 模型。

        Args:
            tool_call: OpenAI API 返回的工具调用对象。

        Returns:
            解析后的 ToolCall 实例。
        """
        raw_args = tool_call.function.arguments
        # 兼容字符串和字典两种参数格式
        arguments: dict[str, Any] = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args if isinstance(raw_args, dict) else {})
        return cls(
            id=tool_call.id,
            name=tool_call.function.name,
            arguments=arguments,
        )


class ToolResult(BaseModel):
    """工具执行结果模型，封装工具调用完成后的输出信息。

    属性说明：
        call_id: 关联的工具调用标识，与 ToolCall.id 对应。
        name: 执行的工具名称。
        output: 工具的文本输出内容。
        is_error: 标记是否为错误结果。
        metadata: 扩展元数据字典。
    """
    call_id: str
    name: str
    output: str
    is_error: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolExecutionMode(str, Enum):
    """工具执行模式枚举，控制多个工具调用的执行策略。"""
    SEQUENTIAL = "sequential"  # 顺序执行，逐个等待结果
    PARALLEL = "parallel"      # 并行执行，同时发起多个调用


class ToolStreamItem(BaseModel):
    """流式工具输出项，用于实时传输工具执行的中间进度或最终结果。

    属性说明：
        type: 输出项类型，"progress" 表示中间进度，"terminal" 表示最终结束。
        data: 进度数据或中间结果，终端项可能为 None。
        result: 当 type 为 "terminal" 时的最终工具结果。
    """
    type: Literal["progress", "terminal"]
    data: Any | None = None
    result: ToolResult | None = None


class ToolCallContext(BaseModel):
    """工具执行上下文模型，为单次工具调用提供运行时环境信息。

    属性说明：
        tool_call_id: 当前工具调用的唯一标识。
        session_id: 所属会话标识，用于追踪和日志关联。
        cwd: 工具执行时的工作目录。
    """
    tool_call_id: str
    session_id: str = ""
    cwd: str = ""


class ToolListContext(BaseModel):
    """工具列表上下文模型，在获取可用工具列表时传递约束条件。

    属性说明：
        token_budget: 当前上下文的 Token 预算，用于决定返回多少工具描述。
        active_skills: 当前激活的技能名称列表，用于筛选相关工具。
        session_id: 所属会话标识。
    """
    token_budget: int = 128000
    active_skills: list[str] = []
    session_id: str = ""