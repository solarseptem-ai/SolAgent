"""
沙箱后端聚合导出。

目前仅提供 Docker 沙箱后端，后续可扩展更多隔离执行后端。
"""
from solagent.sandbox.backends.docker import DockerSandboxProvider
from solagent.sandbox.backends.local import LocalSandboxProvider

__all__ = ["DockerSandboxProvider", "LocalSandboxProvider"]