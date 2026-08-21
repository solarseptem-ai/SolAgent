"""结构化输出管道模块。

将 LLM 的文本响应解析为符合 Pydantic 模型的结构化数据，
并在解析失败时通过 review-revise（审查-修正）循环自动纠错，
提高复杂结构化任务的输出可靠性。
"""
from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from solagent.schema.llm import LLMRequest
from solagent.schema.messages import Message

T = TypeVar("T", bound=BaseModel)


class StructuredOutputError(Exception):
    """当结构化输出在所有重试次数后仍解析失败时抛出此异常。"""


# --- 向后兼容的 API（已弃用，保留给现有调用方使用） ---

def parse_structured_output(content: str, model: type[T]) -> T:
    """将 LLM 响应字符串解析为指定的 Pydantic 模型实例。

    这是简化版的直接解析函数，不经过 review-revise 纠错流程。
    """
    pipe = StructuredOutputPipeline.__new__(StructuredOutputPipeline)
    try:
        text = pipe._extract_json(content)
        return model.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValidationError, ValueError):
        raise StructuredOutputError(f"Failed to parse structured output for {model.__name__}")


def build_response_format(model: type[BaseModel]) -> dict:
    """根据 Pydantic 模型构建 OpenAI 所需的 response_format 参数。"""
    schema = model.model_json_schema()
    return {"type": "json_schema", "json_schema": {"name": model.__name__, "schema": schema}}


async def chat_with_structured_output(provider, request, model: type[T], max_retries: int = 3) -> T:
    """带自动重试的结构化输出对话接口（旧版包装器）。"""
    pipe = StructuredOutputPipeline(provider, max_retries=max_retries)
    return await pipe.generate(request, model)


class StructuredOutputPipeline:
    """结构化输出管道，支持 review-revise 自动纠错。

    执行流程：调用 LLM 生成响应 → 提取 JSON → 用 Pydantic 校验。
    若校验失败，则进入审查-修正循环：让 LLM 分析错误原因，
    然后基于反馈重新生成，直到通过校验或达到最大重试次数。
    """

    _JSON_RE = re.compile(r'```(?:json)?\s*\n?(.*?)\n?```', re.DOTALL)
    _CONTENT_RE = re.compile(r'\[CONTENT\]\s*(.*?)\s*\[/CONTENT\]', re.DOTALL)

    _REVIEW_TEMPLATE = """\
The JSON output below failed validation against the {model_name} schema.

## Validation Errors
{errors}

## Your Output
```
{raw_output}
```

## Schema
```json
{schema}
```

Analyze each error. For each field that failed, explain what is wrong and what the correct value should be.
Output as JSON: {{"field_name": "what is wrong and how to fix it"}}
Only include fields that have errors."""

    _REVISE_TEMPLATE = """\
Your previous output was invalid. Here is the review:

{review}

## Expected Schema
```json
{schema}
```

## Original Request
{original_prompt}

Please regenerate the JSON output with the corrections. Output ONLY valid JSON, no explanation."""

    def __init__(self, provider, max_retries: int = 2) -> None:
        """初始化结构化输出管道。

        参数:
            provider: LLM 提供商实例，用于生成和审查响应。
            max_retries: 解析失败后的最大重试次数（不含首次尝试）。
        """
        self._provider = provider
        self._max_retries = max_retries
        self.last_usage = None

    async def generate(
        self,
        request_or_prompt: LLMRequest | str,
        output_model: type[T],
        *,
        system_prompt: str = "",
        messages: list[Message] | None = None,
        temperature: float = 0.0,
    ) -> T:
        """生成符合指定 Pydantic 模型的结构化输出，支持自动纠错。

        参数:
            request_or_prompt: 已构造好的 LLMRequest 或纯文本提示词。
            output_model: 用于校验的 Pydantic 模型类。
            system_prompt: 系统提示词（仅在传入字符串提示词时使用）。
            messages: 可选的消息列表（仅在传入字符串提示词时使用）。
            temperature: LLM 采样温度。
        """
        schema_json = json.dumps(output_model.model_json_schema(), indent=2)

        if isinstance(request_or_prompt, LLMRequest):
            request = request_or_prompt
            request.temperature = temperature
            original_prompt = str(request.messages[-1].content if request.messages else "")
        else:
            msgs = list(messages) if messages else []
            if system_prompt:
                msgs.append(Message.system(system_prompt))
            msgs.append(Message.user(request_or_prompt))
            request = LLMRequest(
                messages=msgs,
                model=getattr(self._provider, 'get_default_model', lambda: 'gpt-4o')(),
                temperature=temperature,
                max_tokens=4096,
            )
            original_prompt = request_or_prompt

        last_error = None
        raw_output = ""

        for attempt in range(self._max_retries + 1):
            response = await self._provider.chat(request)
            self.last_usage = response.usage
            raw_output = response.content

            try:
                text = self._extract_json(raw_output)
                return output_model.model_validate(json.loads(text))
            except (json.JSONDecodeError, ValidationError) as e:
                last_error = e
                if attempt < self._max_retries:
                    # 进入审查-修正循环：先让 LLM 分析错误，再将审查结果追加到对话中重新生成
                    review = await self._review(raw_output, e, output_model, schema_json)
                    revise_prompt = self._REVISE_TEMPLATE.format(
                        review=review, schema=schema_json, original_prompt=original_prompt,
                    )
                    request.messages.append(Message.assistant(raw_output))
                    request.messages.append(Message.user(revise_prompt))
            except ValueError:
                raise StructuredOutputError(
                    f"No JSON content found in response for {output_model.__name__}"
                )

        raise StructuredOutputError(
            f"Failed to parse structured output for {output_model.__name__} "
            f"after {self._max_retries + 1} attempts: {last_error}"
        )

    def _extract_json(self, text: str) -> str:
        """从文本中提取 JSON 内容，支持代码块、CONTENT 标签和裸 JSON 格式。"""
        text = text.strip()

        match = self._CONTENT_RE.search(text)
        if match:
            return match.group(1).strip()

        match = self._JSON_RE.search(text)
        if match:
            return match.group(1).strip()

        if text.startswith("[") or text.startswith("{"):
            return text

        raise ValueError("No JSON content found in output")

    async def _review(
        self, raw_output: str, error: Exception, output_model: type[BaseModel], schema_json: str
    ) -> str:
        """让 LLM 审查上一次输出的错误并返回审查意见，用于后续修正。"""
        if isinstance(error, ValidationError):
            error_details = json.dumps(
                [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in error.errors()],
                indent=2,
            )
        else:
            error_details = str(error)

        review_prompt = self._REVIEW_TEMPLATE.format(
            model_name=output_model.__name__,
            errors=error_details,
            raw_output=raw_output[:4000],
            schema=schema_json,
        )

        review_request = LLMRequest(
            messages=[Message.user(review_prompt)],
            model=getattr(self._provider, 'get_default_model', lambda: 'gpt-4o')(),
            temperature=0.0,
            max_tokens=1024,
        )
        review_response = await self._provider.chat(review_request)
        return review_response.content