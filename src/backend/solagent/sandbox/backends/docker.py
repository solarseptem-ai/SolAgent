"""
Docker 沙箱后端模块。

基于 Docker 容器提供隔离的代码执行环境，支持资源限制（内存、CPU、网络）。
代码通过临时 tar 归档传入容器执行，结果通过容器 exec_run 获取。
"""
from __future__ import annotations

import asyncio
import io
import logging
import tarfile
import tempfile
import time as _time
from pathlib import Path

from solagent.sandbox.health import SandboxHealth
from solagent.sandbox.models import CodeBlock, ExecutionResult

_logger = logging.getLogger(__name__)


class DockerSandboxProvider:
    """Docker 沙箱后端，在隔离容器中执行代码。

    Attributes:
        image: Docker 镜像名称。
        memory_limit: 内存限制，如 "256m"。
        cpu_shares: CPU 份额权重。
        network_disabled: 是否禁用网络。
        _container: 运行的容器对象。
        _client: Docker 客户端。
        _health: 沙箱健康状态追踪。
    """

    def __init__(self, image: str = "python:3.12-slim", memory_limit: str = "256m",
                 cpu_shares: int = 512, network_disabled: bool = True):
        self.image = image
        self.memory_limit = memory_limit
        self.cpu_shares = cpu_shares
        self.network_disabled = network_disabled
        self._container = None
        self._client = None
        self._health = SandboxHealth()

    async def start(self) -> None:
        """启动 Docker 沙箱，拉取镜像并创建运行中的容器。"""
        import docker
        self._client = docker.from_env()
        # 若本地无镜像则自动拉取
        try:
            self._client.images.get(self.image)
        except docker.errors.ImageNotFound:
            _logger.info("Pulling Docker image: %s", self.image)
            await asyncio.to_thread(self._client.images.pull, self.image)
        # 创建并启动容器，保持运行状态（tail -f /dev/null）
        self._container = await asyncio.to_thread(
            self._client.containers.run,
            self.image,
            command="tail -f /dev/null",
            detach=True,
            remove=True,
            mem_limit=self.memory_limit,
            cpu_shares=self.cpu_shares,
            network_mode="none" if self.network_disabled else "bridge",
            read_only=False,
            security_opt=["no-new-privileges:true"],
        )
        self._health.mark_started()

    async def stop(self) -> None:
        """停止并清理 Docker 沙箱容器。"""
        if self._container:
            try:
                await asyncio.to_thread(self._container.kill)
            except Exception:
                _logger.warning("Docker sandbox container cleanup failed", exc_info=True)
            self._container = None
        if self._client:
            self._client = None

    async def execute(self, code: CodeBlock | str, language: str = "python",
                      timeout: float = 30.0) -> ExecutionResult:
        """在 Docker 容器中执行代码。

        Args:
            code: 代码字符串或 CodeBlock 对象。
            language: 编程语言，默认 "python"。
            timeout: 执行超时时间（秒）。

        Returns:
            执行结果，包含标准输出、标准错误、退出码等。

        Raises:
            RuntimeError: 沙箱未启动时。
        """
        if not self._container:
            raise RuntimeError("Sandbox not started. Call start() first.")
        if isinstance(code, str):
            code = CodeBlock(code=code, language=language)
        start = _time.monotonic()
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            ext = ".py" if code.language == "python" else ".sh"
            script = tmp / f"script{ext}"
            script.write_text(code.code, encoding="utf-8")
            # 将脚本目录打包为 tar 并传入容器 /tmp
            try:
                await asyncio.to_thread(
                    self._container.put_archive,
                    "/tmp",
                    self._make_tar(tmpdir),
                )
            except Exception:
                _logger.warning("Docker sandbox execution failed", exc_info=True)
            # 使用容器内 timeout 命令执行脚本
            cmd = f"timeout {timeout:.0f} {code.language} /tmp/script{ext}"
            try:
                exec_result = await asyncio.to_thread(
                    self._container.exec_run,
                    cmd,
                    workdir="/tmp",
                )
                exit_code = exec_result.exit_code or 0
                stdout = exec_result.output.decode() if isinstance(exec_result.output, bytes) else str(exec_result.output)
                stderr = ""
                is_timeout = exit_code == 124
            except Exception as e:
                _logger.warning("Docker sandbox execution failed", exc_info=True)
                exit_code = -1
                stdout = ""
                stderr = str(e)
                is_timeout = False
            duration = _time.monotonic() - start
            return ExecutionResult(
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                timeout=is_timeout,
                duration=duration,
            )

    def _make_tar(self, directory: str) -> bytes:
        """将目录打包为 tar 字节流，用于传入 Docker 容器。"""
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            tar.add(directory, arcname=".")
        return buf.getvalue()