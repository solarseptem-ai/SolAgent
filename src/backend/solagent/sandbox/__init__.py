"""
沙箱（Sandbox）模块聚合导出。

提供代码执行的安全隔离环境，包含 Docker 和本地两种后端、
沙箱管理器、数据模型和抽象协议。
"""
from solagent.sandbox.backends import DockerSandboxProvider
from solagent.sandbox.manager import SandboxManager
from solagent.sandbox.models import CodeBlock, ExecutionResult
from solagent.sandbox.provider import SandboxProvider

__all__ = ["CodeBlock", "DockerSandboxProvider", "ExecutionResult", "SandboxManager", "SandboxProvider"]