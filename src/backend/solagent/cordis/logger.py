"""日志服务，提供结构化日志记录、多导出器支持和 ANSI 彩色输出。

LoggerService 是 Cordis 框架的中央日志服务，支持通过 `ctx.logger(name)` 获取命名空间日志器，
也支持 `ctx.logger.info(...)` 的快捷调用方式。日志系统采用导出器模式，允许同时向多个目标
（控制台、文件、网络等）输出日志，并支持 printf 风格的格式化字符串和 ANSI 彩色输出。
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from solagent.cordis.service import Service

# 日志级别常量
LOG_ERROR = 0
LOG_WARN = 1
LOG_INFO = 2
LOG_DEBUG = 3

# 级别编号到名称的映射
_LEVEL_NAMES = {0: "error", 1: "warn", 2: "info", 3: "debug"}

# ANSI 颜色调色板（16 色和 256 色）
c16 = [6, 2, 3, 4, 5, 1]
c256 = [
    20, 21, 26, 27, 32, 33, 38, 39, 40, 41, 42, 43, 44, 45, 56, 57, 62,
    63, 68, 69, 74, 75, 76, 77, 78, 79, 80, 81, 92, 93, 98, 99, 112, 113,
    129, 134, 135, 148, 149, 160, 161, 162, 163, 164, 165, 166, 167, 168,
    169, 170, 171, 172, 173, 178, 179, 184, 185, 196, 197, 198, 199, 200,
    201, 202, 203, 204, 205, 206, 207, 208, 209, 214, 215, 220, 221,
]


class LogMessage:
    """单条日志消息的数据结构，包含序列号、时间戳、日志级别和参数。

    属性说明：
        sn: 全局递增序列号。
        ts: 时间戳（Unix 时间）。
        name: 日志器名称/命名空间。
        type: 日志级别名称。
        level: 日志级别数值。
        args: 日志参数元组。
    """
    __slots__ = ("sn", "ts", "name", "type", "level", "args")

    def __init__(self, sn: int, name: str, level: int, args: tuple[Any, ...]) -> None:
        self.sn = sn
        self.ts = time.time()
        self.name = name
        self.type = _LEVEL_NAMES.get(level, "info")
        self.level = level
        self.args = args


class Exporter:
    """日志导出器基类，定义导出器的配置属性和 export 接口。

    属性说明：
        colors: 颜色模式，False 禁用，整数表示 ANSI 颜色深度。
        maxLength: 单行日志最大长度，超出则截断。
        levels: 按命名空间设置的级别过滤映射。
        formatters: 自定义格式化函数字典。
    """
    colors: int | bool = False
    maxLength: int = 10240
    levels: dict[str, int] | None = None
    formatters: dict[str, Any] | None = None

    def export(self, message: LogMessage) -> None:
        """导出单条日志消息，子类必须实现此方法。"""
        raise NotImplementedError


class Logger:
    """命名空间日志器，支持级别过滤、printf 风格格式化和 ANSI 彩色输出。

    每个 Logger 实例绑定到一个特定的命名空间（如插件名称），
    根据配置的级别决定哪些日志会被实际输出。
    """

    @staticmethod
    def color(exporter: Exporter, code: int, value: Any, decoration: str = "") -> str:
        """为值添加 ANSI 颜色转义序列。

        Args:
            exporter: 导出器配置，用于判断是否启用颜色。
            code: ANSI 颜色代码。
            value: 要着色的值。
            decoration: 额外的装饰样式（如粗体）。

        Returns:
            带 ANSI 转义序列的字符串，若颜色禁用则返回原值的字符串表示。
        """
        if not exporter.colors:
            return str(value)
        if code < 8:
            return f"\033[3{code}{decoration}m{value}\033[0m"
        return f"\033[38;5;{code}{decoration}m{value}\033[0m"

    @staticmethod
    def code(name: str, level: int | bool | None = None) -> int:
        """根据名称和级别计算稳定的颜色代码。

        使用哈希算法将名称映射到调色板中的固定颜色，
        确保同一命名空间的日志始终使用相同颜色。
        """
        h = 0
        for ch in name:
            h = ((h << 3) - h) + ord(ch) + 13
            h = h & 0xFFFFFFFF
            if h > 0x7FFFFFFF:
                h -= 0x100000000
        if not level:
            return 0
        palette = c256 if (isinstance(level, int) and level >= 2) else c16
        return palette[abs(h) % len(palette)]

    @staticmethod
    def format(exporter: Exporter, message: LogMessage) -> str:
        """格式化日志消息为字符串，支持 printf 风格占位符和长度截断。

        处理逻辑：
            1. 首个参数若为异常，提取 traceback 信息。
            2. 首个参数若不是字符串，自动插入 "%o" 占位符。
            3. 解析并替换 %s、%d、%f、%o 等格式说明符。
            4. 超出 maxLength 的行进行截断。
        """
        args = list(message.args)
        if args and isinstance(args[0], Exception):
            args[0] = getattr(args[0], "__traceback__", None) or str(args[0])
            args.insert(0, "%s")
        elif args and not isinstance(args[0], str):
            args.insert(0, "%o")

        fmt: str = args.pop(0) if args else ""
        fmt = _format_str(fmt, args, exporter.formatters or {}, message)

        for arg in args:
            if isinstance(arg, dict):
                arg = json.dumps(arg)
            fmt += " " + str(arg)

        max_len = getattr(exporter, "maxLength", 10240) or 10240
        lines = []
        for line in fmt.split("\n"):
            if len(line) > max_len:
                line = line[:max_len] + "..."
            lines.append(line)
        return "\n".join(lines)

    def __init__(self, name: str, level: int, service: "LoggerService") -> None:
        self.name = name
        self.level = level
        self._service = service

    def _log(self, level: int, *args: Any) -> None:
        """内部日志输出方法，处理异常展开并委托给 LoggerService 发射。"""
        if len(args) == 1 and isinstance(args[0], Exception):
            exc = args[0]
            # 若异常有原因链，递归记录根本原因
            if exc.__cause__:
                self._log(level, exc.__cause__)
                return
            # 若异常包含多个子错误，逐一记录
            if hasattr(exc, "errors") and isinstance(exc.errors, list):
                for e in exc.errors:
                    self._log(level, e)
                return
        self._service._emit(self.name, level, args)

    def error(self, *args: Any) -> None:
        """输出 ERROR 级别日志。"""
        self._log(LOG_ERROR, *args)

    def warn(self, *args: Any) -> None:
        """输出 WARN 级别日志。"""
        self._log(LOG_WARN, *args)

    def info(self, *args: Any) -> None:
        """输出 INFO 级别日志。"""
        self._log(LOG_INFO, *args)

    def debug(self, *args: Any) -> None:
        """输出 DEBUG 级别日志。"""
        self._log(LOG_DEBUG, *args)


def _format_str(fmt: str, args: list[Any], formatters: dict[str, Any], message: LogMessage) -> str:
    """解析 printf 风格格式化字符串，替换 %s、%d、%f、%o 等占位符。"""
    def _replace(m: re.Match[str]) -> str:
        ch = m.group(1)
        if ch == "%":
            return "%"
        if ch == "c":
            return ""
        if ch == "C":
            val = args.pop(0) if args else ""
            code = Logger.code(message.name, 3)
            return Logger.color(_dummy_exporter, code, val) if args else str(val)
        if args:
            val = args.pop(0)
            if ch == "s":
                return str(val)
            if ch in ("d", "i"):
                return str(int(val))
            if ch == "f":
                return str(float(val))
            if ch in ("o", "O"):
                return json.dumps(val)
        return m.group(0)

    return re.sub(r"%([a-zA-Z%])", _replace, fmt)


# 用于颜色计算的默认导出器（启用 256 色）
_dummy_exporter = Exporter()
_dummy_exporter.colors = 3


class LoggerService(Service):
    """中央日志服务，支持多导出器、日志缓冲和上下文拦截配置。

    通过 `ctx.logger(name)` 获取命名空间日志器，
    也支持 `ctx.logger.info(...)` 的快捷调用方式。

    属性说明：
        tracker: 追踪器配置，property 指向 "ctx"，noShadow 为 True（保留原始 fiber 上下文）。
        bufferSize: 日志缓冲区大小，默认 1000 条。
    """

    tracker = {"property": "ctx", "noShadow": True}
    bufferSize = 1000

    def __init__(self, ctx: Any) -> None:
        super().__init__(ctx, "logger")
        self._sn = 0
        self._exporters: dict[int, Exporter] = {}
        self._exporter_sn = 0
        self.buffer: list[LogMessage] = []

        # 默认导出器：以 256 色模式缓冲日志消息
        default = Exporter()
        default.colors = 3
        default.export = self._buffer_export
        self.exporter(default)

    def __call__(self, name: str | None = None) -> Logger:
        """使服务可调用，返回指定名称的 Logger 实例。"""
        return self.invoke(None, name)

    def invoke(self, proxy: Any, name: str | None = None) -> Logger:
        """由 TraceableProxy.__call__ 调用，从调用者上下文中解析拦截配置。

        根据调用者的 Cordis 上下文解析 logger 配置，确定日志器名称和级别。
        若未指定名称，则使用当前 fiber 的名称作为默认命名空间。
        """
        ctx = proxy._ctx if proxy is not None and hasattr(proxy, "_ctx") else self.ctx
        config = self._resolveConfig(ctx)
        name = name or config.get("name")
        if not name:
            fiber = getattr(ctx, "fiber", None)
            name = getattr(fiber, "name", "cordis") if fiber else "cordis"
        level = config.get("level", LOG_INFO)
        return Logger(name, level, self)

    def _resolveConfig(self, ctx: Any) -> dict[str, Any]:
        """沿拦截器链解析 logger 配置，从祖先到当前逐层合并。

        Args:
            ctx: Cordis 上下文。

        Returns:
            合并后的配置字典。
        """
        intercept = getattr(ctx, "_intercept", {})
        configs: list[dict[str, Any]] = []
        while hasattr(intercept, "own"):
            if intercept.own("logger"):
                configs.insert(0, intercept["logger"])
            intercept = intercept.parent
        result: dict[str, Any] = {}
        for c in configs:
            if isinstance(c, dict):
                result.update(c)
        return result

    def exporter(self, exporter: Exporter) -> Any:
        """注册一个新的日志导出器，返回用于移除该导出器的 dispose 函数。

        Args:
            exporter: 要注册的导出器实例。

        Returns:
            调用后可注销该导出器的函数。
        """
        self._exporter_sn += 1
        sn = self._exporter_sn
        self._exporters[sn] = exporter

        def _dispose() -> None:
            self._exporters.pop(sn, None)

        if hasattr(self.ctx, "effect"):
            self.ctx.effect(_dispose)
        return _dispose

    def _buffer_export(self, message: LogMessage) -> None:
        """默认导出器实现：将日志消息追加到缓冲区，超出容量时保留最近的消息。"""
        self.buffer.append(message)
        if len(self.buffer) > self.bufferSize:
            self.buffer = self.buffer[-self.bufferSize:]

    def _emit(self, name: str, level: int, args: tuple[Any, ...]) -> None:
        """发射日志消息到所有已注册的导出器，单个导出器异常不影响其他导出器。"""
        self._sn += 1
        msg = LogMessage(self._sn, name, level, args)
        for exporter in list(self._exporters.values()):
            try:
                exporter.export(msg)
            except Exception:
                pass

    def error(self, *args: Any) -> Any:
        """快捷方法：创建默认日志器并输出 ERROR 级别日志。"""
        return self().error(*args)

    def warn(self, *args: Any) -> Any:
        """快捷方法：创建默认日志器并输出 WARN 级别日志。"""
        return self().warn(*args)

    def info(self, *args: Any) -> Any:
        """快捷方法：创建默认日志器并输出 INFO 级别日志。"""
        return self().info(*args)

    def debug(self, *args: Any) -> Any:
        """快捷方法：创建默认日志器并输出 DEBUG 级别日志。"""
        return self().debug(*args)