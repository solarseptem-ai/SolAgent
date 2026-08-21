"""
安全防护基础定义模块。

定义 Guardrail 协议和审查结果数据结构，所有具体防护规则需实现 Guardrail 接口。
"""
from dataclasses import dataclass
from typing import Protocol


@dataclass
class GuardrailResult:
    """防护审查结果。

    Attributes:
        allowed: 是否通过审查，True 表示允许通过。
        reason: 未通过时的原因说明。
        modified_content: 经修改后的内容（如脱敏、截断等）。
    """
    allowed: bool = True
    reason: str = ""
    modified_content: str = ""


class Guardrail(Protocol):
    """防护规则协议，具体防护策略需实现此接口。

    对输入（用户提问）和输出（模型回复）分别进行审查。
    """

    async def check_input(self, text: str) -> GuardrailResult:
        """审查输入内容。

        Args:
            text: 用户输入的文本。

        Returns:
            审查结果，指示是否允许以及原因。
        """
        ...

    async def check_output(self, text: str) -> GuardrailResult:
        """审查输出内容。

        Args:
            text: 模型生成的文本。

        Returns:
            审查结果，指示是否允许以及原因。
        """
        ...