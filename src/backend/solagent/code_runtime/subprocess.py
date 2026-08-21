r"""
子进程代码运行时模块。

每次 run() 调用启动一个独立的 Python 子进程作为 Worker，通过 stdin/stdout 上的 JSON Lines 协议进行双向通信。
Worker 脚本在独立进程中执行用户代码，绑定调用通过同步阻塞方式桥接回宿主进程。

通信协议（每条消息为单行 JSON）：
  Host  → Worker: {"type":"init","program":"...","bindings":[...]}
  Worker → Host: {"type":"call","id":1,"global":"tools","name":"read","args":[...]}
  Host  → Worker: {"type":"reply","id":1,"ok":true,"value":...}
  Worker → Host: {"type":"log","level":"info","message":"..."}
  Worker → Host: {"type":"done","value":...,"error":...}
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any

from solagent.code_runtime.runtime import CodeRuntime
from solagent.code_runtime.types import CodeBindingNamespace, CodeRunFailure, CodeRunRequest, CodeRunResult

_logger = logging.getLogger(__name__)

# Worker 脚本字符串，作为 -c 参数在子进程中执行
_WORKER_SCRIPT = r'''
import asyncio
import json
import sys
import traceback

def _worker_main():
    init_line = sys.stdin.readline()
    if not init_line:
        sys.__stdout__.write(json.dumps({"type":"done","error":{"kind":"worker-exit","message":"no init"}})+"\n")
        sys.__stdout__.flush()
        return
    init = json.loads(init_line)
    program = init["program"]
    bindings_spec = init.get("bindings", [])

    _cid = 0

    def _make_callable(global_name, func_name):
        """为绑定函数创建可调用对象，通过 stdout 向宿主发起同步调用请求。"""
        def _call(*args, **kwargs):
            nonlocal _cid
            _cid += 1
            cid = _cid
            payload = {"type":"call","id":cid,"global":global_name,"name":func_name,"args":list(args)}
            sys.__stdout__.write(json.dumps(payload, default=str)+"\n")
            sys.__stdout__.flush()
            reply_line = sys.stdin.readline()
            if not reply_line:
                raise RuntimeError("worker stdin closed during binding call")
            reply = json.loads(reply_line)
            if reply.get("ok"):
                return reply.get("value")
            raise RuntimeError(reply.get("error", "binding error"))
        return _call

    # 根据 bindings_spec 构建命名空间对象并注入到执行环境
    bindings = {}
    for ns in bindings_spec:
        obj = type("BindingNs", (), {})()
        for fname in ns.get("functions", {}):
            setattr(obj, fname, _make_callable(ns["global"], fname))
        bindings[ns["global"]] = obj

    # 重定向 stdout，将 print 输出转为 JSON log 消息
    class _LogWriter:
        def write(self, text):
            if text and text.strip():
                for line in text.splitlines():
                    if line.strip():
                        sys.__stdout__.write(json.dumps({"type":"log","level":"info","message":line})+"\n")
        def flush(self):
            sys.__stdout__.flush()
    sys.stdout = _LogWriter()

    try:
        ns = {**bindings, "__builtins__": __builtins__}
        exec(program, ns)
        if "main" in ns:
            result = asyncio.run(ns["main"](**bindings))
        else:
            result = None
        try:
            payload = json.dumps({"type":"done","value":result})
        except (TypeError, ValueError):
            payload = json.dumps({"type":"done","error":{"kind":"invalid-output","message":"result not JSON-serializable"}})
        sys.__stdout__.write(payload+"\n")
        sys.__stdout__.flush()
    except Exception:
        exc = traceback.format_exc()
        sys.__stdout__.write(json.dumps({"type":"done","error":{"kind":"exception","message":exc}})+"\n")
        sys.__stdout__.flush()

if __name__ == "__main__":
    _worker_main()
'''


class SubprocessCodeRuntime(CodeRuntime):
    """基于子进程的代码运行时实现。

    每次执行创建一个全新的 Python 子进程，通过 JSON Lines 协议通信。

    Attributes:
        _timeout: 默认执行超时时间（秒）。
    """

    language = "python"
    isolation = "subprocess"

    def __init__(self, timeout: float = 30.0):
        self._timeout = timeout

    async def run(self, request: CodeRunRequest) -> CodeRunResult:
        """启动子进程 Worker 并执行代码。

        流程：
        1. 创建子进程。
        2. 发送 init 消息（程序代码 + 绑定描述）。
        3. 循环读取 Worker 输出，处理 call / log / done 消息。
        4. 超时或完成后清理子进程。
        5. 验证返回值是否可 JSON 序列化。

        Args:
            request: 代码运行请求。

        Returns:
            代码运行结果。
        """
        timeout = request.timeout or self._timeout

        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", _WORKER_SCRIPT,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert proc.stdin is not None and proc.stdout is not None

        init_msg = json.dumps({
            "type": "init",
            "program": request.program,
            "bindings": [
                {"global": ns.global_name, "functions": list(ns.functions.keys())}
                for ns in request.bindings
            ],
        })
        proc.stdin.write((init_msg + "\n").encode())
        await proc.stdin.drain()

        logs: list[str] = []
        result_value: Any = None
        result_error: CodeRunFailure | None = None

        async def _read_worker() -> None:
            """读取 Worker stdout，根据消息类型分发处理。"""
            nonlocal result_value, result_error
            while proc.stdout is not None and not proc.stdout.at_eof():
                try:
                    line = await asyncio.wait_for(
                        proc.stdout.readline(), timeout=timeout,
                    )
                except asyncio.TimeoutError:
                    result_error = CodeRunFailure(kind="timeout", message=f"timed out after {timeout}s")
                    proc.kill()
                    return
                if not line:
                    break
                msg = json.loads(line.decode())
                msg_type = msg.get("type")
                if msg_type == "call":
                    # Worker 请求调用宿主绑定的函数
                    await self._handle_call(proc, msg, request.bindings)
                elif msg_type == "log":
                    logs.append(msg.get("message", ""))
                elif msg_type == "done":
                    # Worker 执行完成
                    result_value = msg.get("value")
                    err = msg.get("error")
                    if err:
                        result_error = CodeRunFailure(kind=err["kind"], message=err.get("message", ""))
                    return

        try:
            await _read_worker()
        except Exception:
            _logger.warning("code runtime worker crashed", exc_info=True)
            result_error = CodeRunFailure(kind="worker-exit", message="worker process exited unexpectedly")

        # 若子进程仍在运行，强制终止
        if proc.returncode is None:
            proc.kill()
            await proc.wait()

        # 验证返回值是否可 JSON 序列化
        if result_error is None and result_value is not None:
            try:
                json.dumps(result_value)
            except (TypeError, ValueError):
                result_error = CodeRunFailure(kind="invalid-output", message="result not JSON-serializable")

        return CodeRunResult(
            value=result_value,
            logs=logs,
            error=result_error,
        )

    async def _handle_call(self, proc: asyncio.subprocess.Process, msg: dict,
                           bindings: list[CodeBindingNamespace]) -> None:
        """处理 Worker 发起的绑定函数调用请求。

        在宿主进程中执行对应的绑定函数，并将结果通过 stdin 写回 Worker。

        Args:
            proc: 子进程对象。
            msg: call 消息字典，包含 id、global、name、args。
            bindings: 绑定命名空间列表。
        """
        assert proc.stdin is not None
        call_id = msg["id"]
        global_name = msg["global"]
        func_name = msg["name"]
        args = msg.get("args", [])

        ns = next((b for b in bindings if b.global_name == global_name), None)
        if ns is None:
            reply = {"type": "reply", "id": call_id, "ok": False, "error": f"unknown namespace: {global_name}"}
        elif func_name not in ns.functions:
            reply = {"type": "reply", "id": call_id, "ok": False, "error": f"unknown function: {global_name}.{func_name}"}
        else:
            try:
                fn = ns.functions[func_name]
                result = fn(*args)
                # 支持异步绑定函数
                if asyncio.iscoroutine(result):
                    result = await result
                json.dumps(result)
                reply = {"type": "reply", "id": call_id, "ok": True, "value": result}
            except Exception as e:
                reply = {"type": "reply", "id": call_id, "ok": False, "error": str(e)}

        proc.stdin.write((json.dumps(reply, default=str) + "\n").encode())
        await proc.stdin.drain()