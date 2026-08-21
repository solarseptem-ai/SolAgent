"""
沙箱提供者协议模块。

定义所有沙箱后端必须遵循的接口，支持运行时类型检查。
"""
from typing import Protocol, runtime_checkable

from solagent.sandbox.models import ExecutionResult


@runtime_checkable
class SandboxProvider(Protocol):
    """沙箱后端协议，所有具体沙箱实现需遵循此接口。

    标记为 @runtime_checkable，支持 isinstance 运行时检查。
    """

    async def execute(self, code: str, language: str = "python", timeout: float = 30.0) -> ExecutionResult:
        """在沙箱中执行代码。

        Args:
            code: 代码文本。
            language: 编程语言。
            timeout: 执行超时时间（秒）。

        Returns:
            执行结果。
        """
        ...

    async def start(self) -> None:
        """启动沙箱环境。"""
        ...

    async def stop(self) -> None:
        """停止沙箱环境并清理资源。"""
        ...