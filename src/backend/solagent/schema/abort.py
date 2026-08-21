"""AbortSignal — 统一取消信号。

对标 dsh AbortSignal / AbortController：
- AbortSignal: 只读信号，可检查是否已取消
- AbortController: 控制端，可触发取消
- AbortError: 取消异常，区分 pre-dispatch 和 post-body 取消

用法：
    controller = AbortController()
    signal = controller.signal

    # 在调度循环中检查
    signal.throw_if_aborted()

    # 外部取消
    controller.abort()
"""


class AbortError(Exception):
    """操作被取消。"""

    def __init__(self, message: str = "operation aborted"):
        super().__init__(message)


class AbortSignal:
    """可取消信号 — 只读端。

    由 AbortController 创建，传递给执行链路。
    各执行阶段在每次 await 前检查 signal.aborted。
    """

    def __init__(self):
        self._aborted = False

    @property
    def aborted(self) -> bool:
        return self._aborted

    def throw_if_aborted(self) -> None:
        if self._aborted:
            raise AbortError()

    def _set_aborted(self) -> None:
        self._aborted = True


class AbortController:
    """取消信号控制器 — 写入端。

    创建 AbortSignal 并提供 abort() 方法触发取消。
    触发后不可逆。
    """

    def __init__(self):
        self._signal = AbortSignal()

    @property
    def signal(self) -> AbortSignal:
        return self._signal

    def abort(self) -> None:
        self._signal._set_aborted()

    @property
    def aborted(self) -> bool:
        return self._signal.aborted