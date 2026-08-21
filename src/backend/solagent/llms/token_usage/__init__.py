"""Token 用量管理模块，提供预算控制与用量追踪能力。

- TokenBudget: 设定输入/输出 token 上限，在超过阈值时发出警告或拒绝请求。
- TokenUsageTracker: 累计多次调用的 token 消耗，便于生成统计报告。
"""
from solagent.llms.token_usage.budget import TokenBudget
from solagent.llms.token_usage.tracker import TokenUsageTracker

__all__ = ["TokenBudget", "TokenUsageTracker"]
