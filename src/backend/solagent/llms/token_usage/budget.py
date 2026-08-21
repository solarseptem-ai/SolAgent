"""Token 预算管理器，用于控制单次会话或任务的输入/输出 token 消耗上限。

当累计用量超过设定阈值时发出警告，若完全耗尽则抛出 TokenLimitError，
防止因无限递归或超长上下文导致成本失控。
"""
from solagent.errors.llm import TokenLimitError
from solagent.schema.llm import TokenUsage


class TokenBudget:
    """Token 预算管理器。

    维护输入与输出 token 的已用量，并提供剩余量查询、警告判断和耗尽拦截。

    属性:
        max_input_tokens: 允许的最大输入 token 数。
        max_output_tokens: 允许的最大输出 token 数。
        warning_threshold: 输入用量占比达到多少时触发警告（0.0 ~ 1.0）。
        _used_input: 已累积的输入 token 数。
        _used_output: 已累积的输出 token 数。
    """

    def __init__(self, max_input_tokens: int = 128000, max_output_tokens: int = 4096, warning_threshold: float = 0.75):
        self.max_input_tokens = max_input_tokens
        self.max_output_tokens = max_output_tokens
        self.warning_threshold = warning_threshold
        self._used_input = 0
        self._used_output = 0

    @property
    def remaining_input(self) -> int:
        """返回剩余可用输入 token 数（最小为 0）。"""
        return max(0, self.max_input_tokens - self._used_input)

    @property
    def remaining_output(self) -> int:
        """返回剩余可用输出 token 数（最小为 0）。"""
        return max(0, self.max_output_tokens - self._used_output)

    @property
    def is_warning(self) -> bool:
        """判断当前输入用量是否已达到警告阈值。"""
        return self._used_input / max(1, self.max_input_tokens) >= self.warning_threshold

    @property
    def is_exhausted(self) -> bool:
        """判断输入 token 预算是否已耗尽。"""
        return self._used_input >= self.max_input_tokens

    def consume(self, usage: TokenUsage) -> None:
        """消费本次调用产生的 token 用量。

        参数:
            usage: 本次调用的 TokenUsage，包含 input_tokens 和 output_tokens。

        异常:
            TokenLimitError: 当累计输入 token 超过上限时抛出。
        """
        self._used_input += usage.input_tokens
        self._used_output += usage.output_tokens
        if self.is_exhausted:
            raise TokenLimitError(f"Input token budget exhausted: {self._used_input}/{self.max_input_tokens}")

    def reset(self) -> None:
        """重置所有已累积的输入/输出 token 计数。"""
        self._used_input = 0
        self._used_output = 0
