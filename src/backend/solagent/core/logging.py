"""结构化 JSON 日志模块，支持 trace_id 和 span_id 的上下文传播。

本模块提供基于 Python 标准 logging 的结构化日志能力，通过 contextvars 实现
跨协程和线程的 trace_id/span_id 自动传播。所有日志条目以 JSON 格式输出，
便于日志收集系统（如 ELK、Loki）进行索引、检索和链路追踪分析。
"""

import contextvars
import json
import logging
import time
import uuid

# 使用 contextvars 存储 trace_id 和 span_id，确保在异步上下文中正确传播
_trace_id: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")
_span_id: contextvars.ContextVar[str] = contextvars.ContextVar("span_id", default="")


def set_trace_id(trace_id: str | None = None) -> str:
    """设置当前上下文的 trace_id，若未提供则自动生成 16 位十六进制标识。

    Args:
        trace_id: 可选的追踪标识字符串。

    Returns:
        设置后的 trace_id 值。
    """
    tid = trace_id or str(uuid.uuid4()).replace("-", "")[:16]
    _trace_id.set(tid)
    return tid


def get_trace_id() -> str:
    """获取当前上下文的 trace_id。"""
    return _trace_id.get()


def set_span_id(span_id: str | None = None) -> str:
    """设置当前上下文的 span_id，若未提供则自动生成 8 位十六进制标识。

    Args:
        span_id: 可选的跨度标识字符串。

    Returns:
        设置后的 span_id 值。
    """
    sid = span_id or str(uuid.uuid4()).replace("-", "")[:8]
    _span_id.set(sid)
    return sid


def get_span_id() -> str:
    """获取当前上下文的 span_id。"""
    return _span_id.get()


class JSONFormatter(logging.Formatter):
    """JSON 格式日志格式化器，将日志记录转换为结构化 JSON 字符串。

    输出字段包括时间戳、日志级别、logger 名称、消息内容、trace_id、span_id、
    模块名、行号以及异常信息和额外字段。
    """

    def format(self, record: logging.LogRecord) -> str:
        # 构建基础日志条目字典
        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.", time.gmtime(record.created))
            + f"{int((record.created % 1) * 1000):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": _trace_id.get(),
            "span_id": _span_id.get(),
            "module": record.module,
            "line": record.lineno,
        }
        # 若存在异常信息，追加到日志条目中
        if record.exc_info and record.exc_info[1]:
            entry["exception"] = str(record.exc_info[1])
        # 追加用户自定义的额外字段
        extra = getattr(record, "extra", {})
        if extra:
            entry["extra"] = extra
        return json.dumps(entry, ensure_ascii=False, default=str)


def configure_logging(level: int = logging.INFO, json_format: bool = True) -> None:
    """配置根日志记录器，设置输出处理器和格式。

    Args:
        level: 日志级别，默认为 INFO。
        json_format: 是否使用 JSON 格式输出，False 则使用传统文本格式。
    """
    handler = logging.StreamHandler()
    if json_format:
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        ))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


class AgentLoggerAdapter(logging.LoggerAdapter):
    """Agent 日志适配器，自动将当前上下文的 trace_id 和 span_id 注入日志记录。

    使用该适配器后，所有通过它输出的日志都会携带 trace_id 和 span_id，
    无需在每条日志调用中手动传递。
    """

    def __init__(self, logger: logging.Logger, extra: dict | None = None):
        super().__init__(logger, extra or {})

    def process(self, msg, kwargs):
        """在日志处理阶段自动注入 trace_id 和 span_id 到 extra 字段。"""
        extra = kwargs.get("extra", {})
        extra["trace_id"] = _trace_id.get()
        extra["span_id"] = _span_id.get()
        kwargs["extra"] = extra
        return msg, kwargs