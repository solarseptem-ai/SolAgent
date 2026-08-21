"""LLM 调用成本追踪模块。

根据各模型的定价策略和实际消耗的 token 数量，计算并累计每次 LLM 调用的费用，
支持按模型维度汇总成本，便于监控和预算管理。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from solagent.schema.llm import TokenUsage

# 各模型每百万 token 的定价（输入价格, 输出价格），用于成本计算
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.00, 30.00),
    "gpt-3.5-turbo": (0.50, 1.50),
    "o1": (15.00, 60.00),
    "o3-mini": (1.10, 4.40),
    "claude-3-5-sonnet-20241022": (3.00, 15.00),
    "claude-3-5-haiku-20241022": (0.80, 4.00),
    "claude-3-opus-20240229": (15.00, 75.00),
    "deepseek-chat": (0.14, 0.28),
    "deepseek-reasoner": (0.55, 2.19),
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "mixtral-8x7b-32768": (0.24, 0.24),
    "qwen3-8b": (0.0, 0.0),
    "qwen3-32b": (0.0, 0.0),
    "qwen3-235b": (0.0, 0.0),
}


@dataclass
class CostRecord:
    """单次 LLM 调用的成本记录。

    属性:
        model: 使用的模型名称。
        input_tokens: 输入 token 数量。
        output_tokens: 输出 token 数量。
        cost_usd: 估算的成本（美元）。
    """
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class CostTracker:
    """成本追踪器，累计多次 LLM 调用的成本并支持按模型汇总。

    属性:
        records: 所有 CostRecord 的列表。
        _pricing: 内部定价表，可按模型自定义单价。
    """
    records: list[CostRecord] = field(default_factory=list)
    _pricing: dict[str, tuple[float, float]] = field(default_factory=lambda: dict(_MODEL_PRICING))

    def set_pricing(self, model: str, input_price_per_m: float, output_price_per_m: float) -> None:
        """为指定模型设置自定义定价（每百万 token 价格）。"""
        self._pricing[model] = (input_price_per_m, output_price_per_m)

    def _get_pricing(self, model: str) -> tuple[float, float]:
        """获取模型的定价，支持前缀匹配以适配不同版本模型。"""
        # 按键长度降序排列，优先匹配最长前缀，确保更具体的模型名称先被命中
        for key in sorted(self._pricing.keys(), key=len, reverse=True):
            if model.startswith(key):
                return self._pricing[key]
        return (0.0, 0.0)

    def record(self, model: str, usage: TokenUsage) -> CostRecord:
        """根据 token 消耗记录本次请求的成本，并返回 CostRecord。"""
        input_price, output_price = self._get_pricing(model)
        cost = (usage.input_tokens / 1_000_000) * input_price + (usage.output_tokens / 1_000_000) * output_price
        record = CostRecord(model=model, input_tokens=usage.input_tokens, output_tokens=usage.output_tokens, cost_usd=cost)
        self.records.append(record)
        return record

    @property
    def total_cost(self) -> float:
        """累计总成本（美元）。"""
        return sum(r.cost_usd for r in self.records)

    @property
    def total_input_tokens(self) -> int:
        """累计输入 token 总数。"""
        return sum(r.input_tokens for r in self.records)

    @property
    def total_output_tokens(self) -> int:
        """累计输出 token 总数。"""
        return sum(r.output_tokens for r in self.records)

    def cost_by_model(self) -> dict[str, float]:
        """按模型名称汇总各自的总成本。"""
        result: dict[str, float] = {}
        for r in self.records:
            result[r.model] = result.get(r.model, 0.0) + r.cost_usd
        return result

    def reset(self) -> None:
        """清空所有成本记录。"""
        self.records.clear()