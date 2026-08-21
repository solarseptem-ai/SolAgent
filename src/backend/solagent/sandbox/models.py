"""
沙箱数据模型模块。

定义代码块（CodeBlock）和执行结果（ExecutionResult）的数据结构，
用于沙箱与上层之间的数据交换。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CodeBlock:
    """待执行的代码块。

    Attributes:
        code: 代码文本内容。
        language: 编程语言，默认 "python"。
    """

    code: str
    language: str = "python"


@dataclass
class ExecutionResult:
    """代码执行结果。

    Attributes:
        stdout: 标准输出内容。
        stderr: 标准错误内容。
        exit_code: 进程退出码。
        timeout: 是否因超时而终止。
        duration: 执行耗时（秒）。
        output_files: 产生的输出文件路径列表。
    """

    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    timeout: bool = False
    duration: float = 0.0
    output_files: list[str] = field(default_factory=list)

    @property
    def is_timeout(self) -> bool:
        """是否因超时而终止。"""
        return self.timeout

    @property
    def success(self) -> bool:
        """是否成功执行（退出码为 0 且未超时）。"""
        return self.exit_code == 0 and not self.timeout