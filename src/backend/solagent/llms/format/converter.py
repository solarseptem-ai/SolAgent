"""消息格式转换器模块。

将 SolAgent 内部统一的 Message 对象及其内容块（TextBlock、ImageBlock、ToolResultBlock 等）
转换为 OpenAI 兼容的 API 消息格式，是多模态和工具调用功能的数据适配层。
"""
from __future__ import annotations

import json

from solagent.schema.messages import ImageBlock, Message, MessageRole, TextBlock, ToolResultBlock
from solagent.schema.tools import ToolDefinition


class FormatConverter:
    """统一的消息格式转换器，负责将内部消息模型转为 OpenAI 格式的 API 消息。"""

    @staticmethod
    def to_openai_messages(messages: list[Message]) -> list[dict]:
        """将内部 Message 列表转换为 OpenAI 消息格式的字典列表。

        对 system、user、assistant、tool 四种角色分别处理：
        - tool 角色提取 tool_call_id 和结果文本；
        - assistant 角色提取文本并序列化 tool_calls；
        - user/system 角色支持文本和多模态图片混排。
        """
        result: list[dict] = []
        for msg in messages:
            # 内部角色枚举到 OpenAI 角色字符串的映射
            role_map = {
                MessageRole.SYSTEM: "system",
                MessageRole.USER: "user",
                MessageRole.ASSISTANT: "assistant",
                MessageRole.TOOL: "tool",
            }
            role = role_map.get(msg.role, "user")
            entry: dict = {"role": role}

            if role == "tool":
                # tool 消息需要提取结果内容和对应的 tool_call_id
                content_text = ""
                tool_call_id = ""
                for block in msg.content:
                    if isinstance(block, ToolResultBlock):
                        content_text = block.content
                        tool_call_id = block.tool_call_id
                    elif isinstance(block, TextBlock):
                        content_text = block.text
                entry["content"] = content_text
                entry["tool_call_id"] = tool_call_id
            elif role == "assistant":
                # assistant 消息合并所有文本块，并附带 tool_calls 列表
                text_parts = [b.text for b in msg.content if isinstance(b, TextBlock)]
                entry["content"] = "\n".join(text_parts) if text_parts else None
                if msg.tool_calls:
                    entry["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                            },
                        }
                        for tc in msg.tool_calls
                    ]
            else:
                # user/system 消息支持文本与图片混排，构造 content 数组或单字符串
                content_parts: list[dict] = []
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        content_parts.append({"type": "text", "text": block.text})
                    elif isinstance(block, ImageBlock):
                        content_parts.append({
                            "type": "image_url",
                            "image_url": {"url": block.source.url or f"data:{block.source.media_type};base64,{block.source.data}"},
                        })
                if content_parts:
                    # 多段内容或包含图片时使用数组格式，否则简化为单字符串以减少 payload
                    if len(content_parts) > 1 or content_parts[0].get("type") == "image_url":
                        entry["content"] = content_parts
                    else:
                        entry["content"] = content_parts[0]["text"]
                else:
                    entry["content"] = ""
            result.append(entry)
        return result

    @staticmethod
    def tools_to_openai(tools: list[ToolDefinition]) -> list[dict]:
        """将内部 ToolDefinition 列表转换为 OpenAI 工具声明格式。"""
        return [t.to_openai_schema() for t in tools]