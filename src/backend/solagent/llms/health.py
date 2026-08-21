"""LLM 提供商连接健康检查模块。

对各个已注册的 LLM 提供商执行连通性检测，收集响应延迟与错误信息，
生成聚合健康报告，用于运维监控和故障发现。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

_logger = logging.getLogger(__name__)


@dataclass
class HealthResult:
    """单个提供商的健康检查结果。

    属性:
        provider_name: 提供商名称。
        success: 检查是否通过。
        latency_ms: 连接延迟（毫秒）。
        error: 错误描述，成功时为空字符串。
        model_count: 可用模型数量。
    """
    provider_name: str
    success: bool
    latency_ms: int = 0
    error: str = ""
    model_count: int = 0


@dataclass
class HealthReport:
    """所有提供商的聚合健康报告。

    属性:
        results: 各提供商的 HealthResult 列表。
        timestamp: 报告生成时间（ISO 格式字符串）。
    """
    results: list[HealthResult] = field(default_factory=list)
    timestamp: str = ""

    @property
    def healthy_count(self) -> int:
        """健康检查通过的提供商数量。"""
        return sum(1 for r in self.results if r.success)

    @property
    def total_count(self) -> int:
        """参与检查的提供商总数。"""
        return len(self.results)

    @property
    def all_healthy(self) -> bool:
        """当所有提供商均通过检查且总数大于 0 时返回 True。"""
        return self.healthy_count == self.total_count and self.total_count > 0


async def check_provider_health(provider) -> HealthResult:
    """检查单个提供商的连接健康状态。

    若提供商实现了 test_connection 方法，则调用该方法获取详细结果；
    否则默认视为健康。
    """
    if hasattr(provider, 'test_connection'):
        result = await provider.test_connection()
        return HealthResult(
            provider_name=provider.profile.name,
            success=result["success"],
            latency_ms=result["latency_ms"],
            error=result["error"],
        )
    return HealthResult(provider_name=provider.profile.name, success=True, latency_ms=0)


async def check_all_health(registry) -> HealthReport:
    """对注册表中所有提供商执行健康检查并生成聚合报告。"""
    import datetime
    results = []
    for profile in registry.list_profiles():
        try:
            provider = registry.get_provider(profile.name)
            result = await check_provider_health(provider)
            results.append(result)
        except Exception as e:
            _logger.warning("LLM health check failed for provider '%s': %s", profile.name, e, exc_info=True)
            results.append(HealthResult(provider_name=profile.name, success=False, error=str(e)))
    return HealthReport(results=results, timestamp=datetime.datetime.now().isoformat())