"""
代码运行时类型定义模块。

定义代码执行过程中使用的数据类型：绑定命名空间、运行请求、运行结果及错误。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

# 代码执行返回的 JSON 可序列化值
CodeJsonValue = Any

# 绑定到代码命名空间的可调用函数（支持同步和异步）
CodeBindingFunction = Callable[..., Any | Awaitable[Any]]


@dataclass
class CodeBindingNamespace:
    """代码绑定命名空间，将一组函数注入到执行环境的指定全局变量下。

    Attributes:
        global_name: 在代码执行环境中的全局变量名。
        functions: 函数名称到可调用对象的映射。
    """

    global_name: str
    functions: dict[str, CodeBindingFunction] = field(default_factory=dict)


@dataclass
class CodeRunRequest:
    """代码运行请求。

    Attributes:
        program: 要执行的程序代码字符串。
        bindings: 注入到运行环境的绑定命名空间列表。
        timeout: 执行超时时间（秒），默认 30 秒。
    """

    program: str
    bindings: list[CodeBindingNamespace] = field(default_factory=list)
    timeout: float = 30.0


@dataclass
class CodeRunFailure:
    """代码运行失败信息。

    Attributes:
        kind: 错误类型，如 "timeout"、"exception"、"worker-exit"。
        message: 错误描述信息。
    """

    kind: str
    message: str = ""


@dataclass
class CodeRunResult:
    """代码运行结果。

    Attributes:
        value: 执行返回值，需为 JSON 可序列化。
        logs: 执行过程中收集的日志列表。
        error: 若执行失败，包含失败原因；成功时为 None。
    """

    value: CodeJsonValue = None
    logs: list[str] = field(default_factory=list)
    error: CodeRunFailure | None = None

    @property
    def success(self) -> bool:
        """是否成功执行（无错误）。"""
        return self.error is None
