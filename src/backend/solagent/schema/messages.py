"""消息模型定义，提供 Agent 与 LLM 交互所需的结构化消息表示。

本模块定义了消息角色枚举、内容块类型（文本、图像、工具调用、工具结果、思考过程）
以及消息容器模型。这些结构支持多模态输入输出、工具调用链和流式传输场景，
是 SolAgent 消息总线和 LLM 适配层的基础数据契约。
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator


class MessageRole(str, Enum):
    """消息角色枚举，标识消息在对话中的参与方身份。"""
    SYSTEM = "system"       # 系统提示消息，设定 Agent 行为规则
    USER = "user"           # 用户输入消息
    ASSISTANT = "assistant" # Agent/模型生成的回复消息
    TOOL = "tool"           # 工具执行结果消息


class ToolCallState(str, Enum):
    """工具调用状态枚举，追踪单个工具调用在生命周期中的当前阶段。

    状态流转通常为：PENDING -> VALIDATING -> ALLOWED -> EXECUTING -> FINISHED，
    任一阶段都可能因权限或校验失败而转入 DENIED。
    """
    PENDING = "pending"         # 待处理，模型已请求但尚未开始校验
    VALIDATING = "validating"   # 正在校验参数和权限
    ALLOWED = "allowed"         # 校验通过，等待执行
    EXECUTING = "executing"     # 正在执行工具逻辑
    FINISHED = "finished"       # 执行完成
    DENIED = "denied"           # 被拒绝（权限不足或参数非法）


class ImageSourceType(str, Enum):
    """图像数据源类型枚举，指明图像内容的提供方式。"""
    URL = "url"       # 通过 HTTP URL 引用外部图像
    BASE64 = "base64" # 图像数据以 Base64 编码字符串内嵌


class ImageSource(BaseModel):
    """图像数据源模型，描述单张图像的来源和格式信息。

    属性说明：
        type: 图像提供方式，URL 或 BASE64。
        url: 当 type 为 URL 时的图像地址。
        data: 当 type 为 BASE64 时的编码数据。
        media_type: 图像的 MIME 类型，如 "image/png"。
    """
    type: ImageSourceType
    url: str | None = None
    data: str | None = None
    media_type: str | None = None

    @model_validator(mode="after")
    def _validate_source(self) -> ImageSource:
        """校验图像数据源的一致性：URL 类型必须有 url，BASE64 类型必须有 data。"""
        if self.type == ImageSourceType.URL and not self.url:
            raise ValueError("url is required when type is URL")
        if self.type == ImageSourceType.BASE64 and not self.data:
            raise ValueError("data is required when type is BASE64")
        return self


class TextBlock(BaseModel):
    """文本内容块，表示一段纯文本消息内容。

    属性说明：
        type: 内容类型标识，固定为 "text"。
        text: 文本内容字符串。
        cache_control: 缓存控制参数，部分 Provider 支持提示缓存（如 Anthropic）。
    """
    model_config = {"frozen": True}

    type: Literal["text"] = "text"
    text: str
    cache_control: dict[str, Any] | None = None


class ImageBlock(BaseModel):
    """图像内容块，表示消息中包含的图像数据。

    属性说明：
        type: 内容类型标识，固定为 "image"。
        source: 图像数据源，包含 URL 或 Base64 编码数据。
    """
    model_config = {"frozen": True}

    type: Literal["image"] = "image"
    source: ImageSource


class ToolCallBlock(BaseModel):
    """工具调用块，表示模型请求调用某个工具及其参数。

    属性说明：
        type: 内容类型标识，固定为 "tool_call"。
        id: 工具调用的唯一标识，用于关联后续的工具结果。
        name: 被调用工具的名称。
        arguments: 工具调用的参数字典。
        state: 当前工具调用的处理状态。
    """
    type: Literal["tool_call"] = "tool_call"
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    state: ToolCallState = ToolCallState.PENDING


class ToolResultBlock(BaseModel):
    """工具结果块，表示工具执行完成后返回的内容。

    属性说明：
        type: 内容类型标识，固定为 "tool_result"。
        tool_call_id: 关联的工具调用标识，与 ToolCallBlock.id 对应。
        content: 工具执行结果的文本内容。
        is_error: 标记该结果是否为错误输出。
    """
    model_config = {"frozen": True}

    type: Literal["tool_result"] = "tool_result"
    tool_call_id: str
    content: str
    is_error: bool = False


class ThinkingBlock(BaseModel):
    """思考过程块，用于捕获和展示模型的内部推理链（Chain-of-Thought）。

    属性说明：
        type: 内容类型标识，固定为 "thinking"。
        thinking: 模型的思考文本内容。
        signature: 思考内容的签名，部分 Provider 用于校验思考完整性。
    """
    model_config = {"frozen": True}

    type: Literal["thinking"] = "thinking"
    thinking: str
    signature: str | None = None


# 内容块的联合类型，使用 Pydantic 的 discriminated union 根据 type 字段自动反序列化具体类型
ContentBlock = Annotated[
    TextBlock | ImageBlock | ToolCallBlock | ToolResultBlock | ThinkingBlock,
    Field(discriminator="type"),
]


class Message(BaseModel):
    """消息容器模型，表示对话中的一条消息，支持多模态内容和工具调用。

    属性说明：
        id: 消息的唯一标识符，默认自动生成 UUID。
        role: 消息角色，标识发送方。
        content: 消息内容块列表，可包含文本、图像、工具调用等多种类型。
        tool_calls: 当角色为 assistant 时，记录模型发起的工具调用请求。
        metadata: 扩展元数据字典。
        created_at: 消息创建时间（UTC）。
    """
    model_config = {"frozen": True}

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    role: MessageRole
    content: list[ContentBlock] = Field(default_factory=list)
    tool_calls: list[ToolCallBlock] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def system(cls, content: str | list[ContentBlock]) -> Message:
        """便捷构造器：创建一条系统角色消息。"""
        if isinstance(content, str):
            content = [TextBlock(text=content)]
        return cls(role=MessageRole.SYSTEM, content=content)

    @classmethod
    def user(cls, content: str | list[ContentBlock]) -> Message:
        """便捷构造器：创建一条用户角色消息。"""
        if isinstance(content, str):
            content = [TextBlock(text=content)]
        return cls(role=MessageRole.USER, content=content)

    @classmethod
    def assistant(cls, content: str | list[ContentBlock]) -> Message:
        """便捷构造器：创建一条助手角色消息。"""
        if isinstance(content, str):
            content = [TextBlock(text=content)]
        return cls(role=MessageRole.ASSISTANT, content=content)

    @classmethod
    def assistant_with_tool_calls(
        cls, content: str | list[ContentBlock], tool_calls: list[ToolCallBlock]
    ) -> Message:
        """便捷构造器：创建一条包含工具调用请求的助手消息。"""
        if isinstance(content, str):
            content = [TextBlock(text=content)]
        return cls(role=MessageRole.ASSISTANT, content=content, tool_calls=tool_calls)

    @classmethod
    def tool_result(cls, content: str | list[ContentBlock]) -> Message:
        """便捷构造器：创建一条工具结果角色消息。"""
        if isinstance(content, str):
            content = [TextBlock(text=content)]
        return cls(role=MessageRole.TOOL, content=content)

    def add_content_block(self, block: ContentBlock) -> Message:
        """向当前消息追加一个内容块，返回新的 Message 实例（原实例不可变）。"""
        return self.model_copy(update={"content": [*self.content, block]})