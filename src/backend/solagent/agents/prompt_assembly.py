"""PromptAssembly — section-based 系统提示词组装。

对标 dsh systemPrompt.assemble()：
- 按 order 排序的 section 注册
- 支持 scope-filtered 的 section 注册（per-agent）
- 支持 lazy evaluation（callable content）
- assemble() 返回最终系统提示词
"""

from collections.abc import Callable


class PromptAssembly:
    """Section-based prompt 组装器。

    用法：
        assembly = PromptAssembly()
        assembly.register("identity", 0, "You are a helpful assistant.")
        assembly.register("date", 10, lambda: f"Current date: {datetime.now()}")
        assembly.register("tools", 20, lambda ctx: format_tools(ctx.tools))
        prompt = assembly.assemble()  # 按 order 排序拼接
    """

    def __init__(self):
        self._sections: list[tuple[str, int, Callable | str]] = []

    def register(self, name: str, order: int, content: str | Callable) -> Callable:
        """注册一个 section。返回 disposer 函数用于取消注册。

        content 可以是固定字符串或 callable（lazy evaluation）。
        callable 在 assemble() 时调用，可接收可选的 context 参数。
        """
        self._sections.append((name, order, content))
        self._sections.sort(key=lambda x: x[1])

        def dispose():
            self._sections = [(n, o, c) for n, o, c in self._sections if n != name]

        return dispose

    def remove(self, name: str) -> None:
        self._sections = [(n, o, c) for n, o, c in self._sections if n != name]

    def assemble(self, context: object | None = None) -> str:
        """按 order 排序拼接所有 section。

        args:
            context: 可选上下文，传递给 callable content。
        """
        parts = []
        for _name, _order, content in self._sections:
            if callable(content):
                try:
                    result = content(context)
                except TypeError:
                    result = content()
                if result:
                    parts.append(str(result))
            else:
                parts.append(str(content))
        return "\n\n".join(parts)

    def __len__(self) -> int:
        return len(self._sections)