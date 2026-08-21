"""Token 用量追踪器，累计多次 LLM 调用的 token 消耗。

常用于生成调用统计报告、监控成本或评估不同模型的实际 token 开销。
"""
from solagent.schema.llm import TokenUsage


class TokenUsageTracker:
    """Token 用量累计追踪器。

    属性:
        _usage: 累计的 TokenUsage（输入 + 输出 token 数）。
        _call_count: 累计的调用次数。
    """

    def __init__(self):
        self._usage = TokenUsage()
        self._call_count = 0

    def record(self, usage: TokenUsage) -> None:
        """记录一次调用的 token 用量。

        参数:
            usage: 本次调用的 TokenUsage。
        """
        self._usage = self._usage + usage
        self._call_count += 1

    @property
    def total(self) -> TokenUsage:
        """返回累计的总 token 用量。"""
        return self._usage

    @property
    def call_count(self) -> int:
        """返回累计的调用次数。"""
        return self._call_count

    def reset(self) -> None:
        """清空累计的 token 用量和调用次数。"""
        self._usage = TokenUsage()
        self._call_count = 0
