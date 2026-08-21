"""
本地沙箱后端模块。

在当前机器的子进程中执行代码，通过资源限制（rlimit）和环境过滤提供基础隔离。
适用于没有 Docker 或需要轻量级隔离的场景。
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import tempfile
import time as _time
from pathlib import Path

try:
    import resource
except ModuleNotFoundError:
    resource = None  # type: ignore[assignment]  # ponytail: Windows 无 resource 模块

_logger = logging.getLogger(__name__)

from solagent.sandbox.health import SandboxHealth
from solagent.sandbox.models import CodeBlock, ExecutionResult

# 允许传入子进程的环境变量白名单，减少信息泄露风险
_SAFE_ENV_KEYS = {"PATH", "HOME", "USER", "USERNAME", "TMP", "TMPDIR", "TEMP", "LANG", "LC_ALL", "PYTHONIOENCODING", "SYSTEMROOT", "WINDIR", "PYTHONPATH", "VIRTUAL_ENV", "CONDA_PREFIX"}


def _set_limits(memory_mb: int, cpu_time: float) -> None:
    if resource is None:
        return
    if hasattr(resource, "RLIMIT_AS"):
        limit = memory_mb * 1024 * 1024
        try:
            resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
        except (ValueError, OSError):
            pass
    if hasattr(resource, "RLIMIT_CPU"):
        try:
            resource.setrlimit(resource.RLIMIT_CPU, (int(cpu_time), int(cpu_time)))
        except (ValueError, OSError):
            pass


def _safe_env() -> dict[str, str]:
    """过滤当前环境变量，仅保留安全键和 PYTHON 相关变量。"""
    return {k: v for k, v in os.environ.items()
            if k in _SAFE_ENV_KEYS or k.startswith("PYTHON")}


class LocalSandboxProvider:
    """本地沙箱后端，在子进程中执行代码。

    Attributes:
        memory_limit_mb: 内存限制（MB）。
        cpu_timeout: CPU 超时时间（秒）。
        network_disabled: 是否禁用网络（当前为信息属性）。
        allow_write: 是否允许文件写入。
        _started: 沙箱是否已启动。
        _health: 沙箱健康状态追踪。
    """

    def __init__(self, memory_limit_mb: int = 256, cpu_timeout: float = 30.0,
                 network_disabled: bool = True, allow_write: bool = True):
        self.memory_limit_mb = memory_limit_mb
        self.cpu_timeout = cpu_timeout
        self.network_disabled = network_disabled
        self.allow_write = allow_write
        self._started = False
        self._health = SandboxHealth()

    async def start(self) -> None:
        """标记沙箱为已启动状态。"""
        self._started = True
        self._health.mark_started()

    async def stop(self) -> None:
        """标记沙箱为已停止状态。"""
        self._started = False

    async def execute(self, code: CodeBlock | str, language: str = "python",
                      timeout: float = 30.0) -> ExecutionResult:
        """在本地子进程中执行代码。

        Args:
            code: 代码字符串或 CodeBlock 对象。
            language: 编程语言，默认 "python"。
            timeout: 执行超时时间（秒）。

        Returns:
            执行结果，包含标准输出、标准错误、退出码等。

        Raises:
            RuntimeError: 沙箱未启动时。
        """
        if not self._started:
            raise RuntimeError("Sandbox not started. Call start() first.")
        if isinstance(code, str):
            code = CodeBlock(code=code, language=language)

        start = _time.monotonic()
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            ext = ".py" if code.language == "python" else ".sh"
            script = tmp / f"script{ext}"
            script.write_text(code.code, encoding="utf-8")

            # 根据语言和平台构建执行命令
            if code.language == "python":
                cmd = [sys.executable, str(script)]
            else:
                cmd = ["bash", str(script)] if sys.platform != "win32" else ["cmd", "/c", str(script)]

            env = _safe_env()

            # 非 Windows 平台设置子进程资源限制
            preexec_fn = None
            if sys.platform != "win32":
                def _set_child_limits():
                    _set_limits(self.memory_limit_mb, min(self.cpu_timeout, timeout))
                preexec_fn = _set_child_limits

            try:
                proc = await asyncio.to_thread(
                    subprocess.run,
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=str(tmp),
                    env=env,
                    preexec_fn=preexec_fn,
                )
                exit_code = proc.returncode
                stdout = proc.stdout
                stderr = proc.stderr
                is_timeout = False
            except subprocess.TimeoutExpired:
                exit_code = -1
                stdout = ""
                stderr = ""
                is_timeout = True
            except FileNotFoundError:
                exit_code = -2
                stdout = ""
                stderr = f"Interpreter not found: {cmd[0]}"
                is_timeout = False
            except Exception as e:
                _logger.warning("Local sandbox execution failed", exc_info=True)
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