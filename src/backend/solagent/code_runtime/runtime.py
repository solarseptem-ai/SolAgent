"""
代码运行时抽象基类模块。

定义所有代码执行后端的通用接口，子类需实现 run 方法。
language 和 isolation 为信息性属性，供上层决策使用。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from solagent.code_runtime.types import CodeRunRequest, CodeRunResult


class CodeRuntime(ABC):
    """代码执行后端的抽象基类。

    language 和 isolation 为信息性属性 —— 上层可根据它们决定是否生成代码块。

    Attributes:
        language: 支持的语言，默认 "python"。
        isolation: 隔离级别描述，如 "subprocess"、"docker" 等。
    """

    language: str = "python"
    isolation: str = "unknown"

    @abstractmethod
    async def run(self, request: CodeRunRequest) -> CodeRunResult:
        """使用给定的绑定执行程序。

        执行错误通过返回结果的 error 字段传递，不直接抛出异常；
        仅实现层面的契约违反（如已释放、无效绑定名）才应抛出异常。

        Args:
            request: 代码运行请求，包含程序代码和绑定命名空间。

        Returns:
            代码运行结果，包含返回值、日志和错误信息。
        """
        ...