"""基于 contextvars 的事件作用域栈，兼容 CloudEvents 规范。"""

import contextvars


class EventScope:
    """基于上下文变量的作用域栈实现。

    用于在异步上下文中跟踪事件嵌套层级（如 agent.start → llm.call.start → tool.call.start），
    支持 push/pop 操作和当前作用域查询。利用 contextvars 保证并发安全。
    """

    def __init__(self):
        """初始化作用域栈，每个实例拥有独立的 ContextVar。"""
        self._stack_var: contextvars.ContextVar[list[str]] = contextvars.ContextVar(
            f"event_scope_{id(self)}"
        )

    def _get_stack(self) -> list[str]:
        """获取当前上下文中的作用域栈，若不存在则创建空栈。"""
        try:
            return self._stack_var.get()
        except LookupError:
            stack: list[str] = []
            self._stack_var.set(stack)
            return stack

    def push(self, scope: str) -> None:
        """将作用域压入栈顶。"""
        stack = self._get_stack()
        stack.append(scope)

    def pop(self, expected: str | None = None) -> None:
        """弹出栈顶作用域。

        Args:
            expected: 若指定，则验证栈顶是否匹配，不匹配时抛出 RuntimeError。

        Raises:
            RuntimeError: 栈为空或 expected 不匹配时抛出。
        """
        stack = self._get_stack()
        if not stack:
            raise RuntimeError("Scope pop called on empty stack")
        current = stack[-1]
        if expected is not None and current != expected:
            raise RuntimeError(
                f"Scope pop mismatch: expected {expected!r}, got {current!r}"
            )
        stack.pop()

    @property
    def current(self) -> str:
        """返回栈顶作用域，空栈时返回空字符串。"""
        try:
            stack = self._stack_var.get()
            return stack[-1] if stack else ""
        except LookupError:
            return ""