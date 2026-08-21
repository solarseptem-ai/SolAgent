"""OpenTelemetry 分布式追踪集成模块。

本模块为 SolAgent 框架提供轻量级的追踪能力，围绕 Agent 执行、LLM 调用和
工具调用等关键环节创建 span 包装器。通过与现有 trace_id 上下文集成，
实现跨请求的链路关联和性能监控。

可选依赖：安装 `opentelemetry-api` 和 `opentelemetry-sdk` 后自动启用；
若未安装，所有追踪操作将静默回退为无操作模式，不影响业务逻辑。
"""

import contextlib
import logging
import time
from typing import Any

from solagent.core.logging import get_trace_id, set_span_id

_logger = logging.getLogger(__name__)

# 检测 OpenTelemetry 是否可用，若不可用则所有追踪功能静默降级
_otel_available = False
try:
    from opentelemetry import trace
    from opentelemetry.trace import SpanKind, Status, StatusCode
    _otel_available = True
except ImportError:
    pass


def tracer_available() -> bool:
    """检查当前环境是否支持 OpenTelemetry 追踪。"""
    return _otel_available


def _get_tracer() -> Any:
    """获取 SolAgent 的 tracer 实例，若 OTel 不可用则返回 None。"""
    if not _otel_available:
        return None
    return trace.get_tracer("solagent", "0.1.0")


@contextlib.asynccontextmanager
async def agent_span(agent_name: str, mode: str, **attrs):
    """Agent 执行的异步上下文管理器，自动创建和结束追踪 span。

    追踪属性包括 Agent 名称、运行模式和当前 trace_id。
    异常发生时自动记录错误状态和异常详情。

    Args:
        agent_name: Agent 名称。
        mode: Agent 运行模式。
        **attrs: 额外的追踪属性。

    Yields:
        创建的 span 对象，或 None（当 OTel 不可用时）。
    """
    tracer = _get_tracer()
    if tracer is None:
        yield None
        return

    span_id = set_span_id()
    with tracer.start_as_current_span(
        "agent.run",
        kind=SpanKind.SERVER,
        attributes={
            "agent.name": agent_name,
            "agent.mode": mode,
            "trace.id": get_trace_id(),
            **attrs,
        },
    ) as span:
        set_span_id(span_id)
        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise


@contextlib.asynccontextmanager
async def llm_span(model: str, message_count: int, **attrs):
    """LLM 调用的异步上下文管理器，追踪请求耗时和消息规模。

    Args:
        model: 调用的模型名称。
        message_count: 请求中的消息数量。
        **attrs: 额外的追踪属性。

    Yields:
        创建的 span 对象，或 None（当 OTel 不可用时）。
    """
    tracer = _get_tracer()
    if tracer is None:
        yield None
        return

    span_id = set_span_id()
    with tracer.start_as_current_span(
        "llm.call",
        kind=SpanKind.CLIENT,
        attributes={
            "llm.model": model,
            "llm.message_count": message_count,
            "trace.id": get_trace_id(),
            **attrs,
        },
    ) as span:
        set_span_id(span_id)
        start = time.monotonic()
        try:
            yield span
            span.set_attribute("llm.duration_ms", int((time.monotonic() - start) * 1000))
            span.set_status(Status(StatusCode.OK))
        except Exception as e:
            span.set_attribute("llm.duration_ms", int((time.monotonic() - start) * 1000))
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise


@contextlib.asynccontextmanager
async def tool_span(tool_name: str, **attrs):
    """工具调用的异步上下文管理器，追踪工具执行耗时。

    Args:
        tool_name: 调用的工具名称。
        **attrs: 额外的追踪属性。

    Yields:
        创建的 span 对象，或 None（当 OTel 不可用时）。
    """
    tracer = _get_tracer()
    if tracer is None:
        yield None
        return

    span_id = set_span_id()
    with tracer.start_as_current_span(
        "tool.call",
        kind=SpanKind.CLIENT,
        attributes={
            "tool.name": tool_name,
            "trace.id": get_trace_id(),
            **attrs,
        },
    ) as span:
        set_span_id(span_id)
        start = time.monotonic()
        try:
            yield span
            span.set_attribute("tool.duration_ms", int((time.monotonic() - start) * 1000))
            span.set_status(Status(StatusCode.OK))
        except Exception as e:
            span.set_attribute("tool.duration_ms", int((time.monotonic() - start) * 1000))
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise


def setup_otel(service_name: str = "solagent", exporter: str = "console",
               otlp_endpoint: str = "http://localhost:4317") -> None:
    """初始化 OpenTelemetry 追踪系统，配置 tracer provider 和导出器。

    支持的导出器类型：
        - "console": 控制台输出，适用于本地调试。
        - "otlp": OTLP/gRPC 导出，适用于生产环境的 Collector 接收。
        - "otlp-http": OTLP/HTTP 导出，适用于通过 HTTP 代理的场景。

    Args:
        service_name: 服务名称，显示在追踪系统中。
        exporter: 导出器类型，默认为 "console"。
        otlp_endpoint: OTLP 导出器的目标地址。
    """
    if not _otel_available:
        _logger.warning("OpenTelemetry not available. Install with: pip install opentelemetry-api opentelemetry-sdk")
        return

    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider

    resource = Resource.create({"service.name": service_name})

    if exporter == "otlp":
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(
            OTLPSpanExporter(endpoint=otlp_endpoint)
        ))
        _logger.info("OTLP tracing enabled (endpoint=%s)", otlp_endpoint)
    elif exporter == "otlp-http":
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as HTTPExporter
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(
            HTTPExporter(endpoint=otlp_endpoint)
        ))
        _logger.info("OTLP HTTP tracing enabled (endpoint=%s)", otlp_endpoint)
    else:
        # 默认使用控制台导出器，便于本地开发和调试
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    _logger.info("OpenTelemetry tracing initialized (exporter=%s)", exporter)