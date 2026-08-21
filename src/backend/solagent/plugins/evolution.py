"""Evolution Plugin — 自进化引擎：静默学习、PluginBank 注册、UCB 选择、自动遗忘。"""
"""Agent 进化（自学）插件模块。

通过监听事件总线收集 Agent 执行轨迹，自动提炼成功路径为可复用的 Pattern，
并以动态插件形式注册到 PluginManager。同时提供 UCB 算法选择最佳技能，
以及遗忘低置信度/长期未使用的旧技能。
"""
import asyncio
import hashlib
import math
import time
from dataclasses import dataclass, field
from typing import Any, ClassVar

from solagent.events.types import AgentEvent, AgentEventType
from solagent.plugins import Plugin, PluginManager


@dataclass
class Pattern:
    """工具调用序列模式，代表 Agent 自学到的成功路径。

    Attributes:
        name: 模式名称。
        tool_sequence: 有序的工具名元组。
        confidence: 成功置信度（成功次数 / 使用次数）。
        times_used: 被使用的总次数。
        times_succeeded: 成功次数。
        last_success_at: 上次成功的时间戳。
        source_trace_id: 来源会话 trace ID。
    """
    name: str
    tool_sequence: tuple[str, ...]
    confidence: float = 0.5
    times_used: int = 0
    times_succeeded: int = 0
    last_success_at: float = 0.0
    source_trace_id: str = ""

    @property
    def sequence_hash(self) -> str:
        """基于工具序列生成短哈希，用于唯一标识。"""
        return hashlib.sha256("|".join(self.tool_sequence).encode()).hexdigest()[:12]


class EvolvedPlugin(Plugin):
    """进化技能插件 — 注册到 PluginManager，可被 UCB 选择，可被手动删除。"""

    name: ClassVar[str] = ""
    pattern: Pattern
    inject: ClassVar[dict[str, Any]] = {}

    async def start(self):
        """从配置中读取 pattern，并向上下文暴露 evolved.{name} 服务。"""
        self.pattern = getattr(self, "_config", {}).get("pattern", Pattern(name="", tool_sequence=()))
        self.ctx.provide(f"evolved.{self.name}", self.pattern)

    async def stop(self):
        pass


class EvolutionPlugin(Plugin):
    """静默学习引擎 — 订阅 EventBus 收集反馈，分析轨迹，注册/遗忘技能。

    三定律：
    1. 学会好的 — 成功轨迹提炼为 Pattern，注册为 EvolvedPlugin
    2. 忘记不好的 — 置信度跌破阈值自动 unregister
    3. 自学技能 — 用户可手动 list/get/unregister 进化插件
    """

    name = "evolution"
    inject = {"event_bus": None}

    CONFIDENCE_THRESHOLD = 0.3       # 低于此置信度即遗忘
    MIN_SEQUENCE_LENGTH = 2          # 最少工具调用序列长度才提炼为 Pattern
    GUIDED_ROUNDS = 5                # 引导轮数，未满引导轮优先返回
    GUIDED_FAIL_THRESHOLD = 0.5      # 引导期失败率上限
    FORGET_DECAY_DAYS = 7            # 遗忘时间窗口（天）

    def __init__(self, ctx):
        super().__init__(ctx)
        self._traces: dict[str, list[tuple[str, bool]]] = {}
        self._patterns: dict[str, Pattern] = {}
        self._evolved_plugins: dict[str, type[EvolvedPlugin]] = {}
        self._total_rounds = 0

    async def start(self):
        """注入 evolution 服务并订阅工具调用与 Agent 结束事件。"""
        self.ctx.provide("evolution", self)
        bus = self.ctx.event_bus
        if bus is not None:
            bus.subscribe("tool.call.*", self._on_tool_event)
            bus.subscribe("agent.end", self._on_agent_end)
            bus.subscribe("agent.error", self._on_agent_error)

    async def stop(self):
        pass

    def _pattern_key(self, steps: list[str]) -> str:
        """将工具名列表用 | 连接，生成 Pattern 字典键。"""
        return "|".join(steps)

    async def _on_tool_event(self, event: AgentEvent) -> None:
        """记录每个会话的工具调用轨迹，遇到错误时回置对应步骤状态。"""
        session_id = event.session_id or event.event_id
        et = event.event_type
        if et in (AgentEventType.TOOL_CALL_START, AgentEventType.TOOL_CALL_END, AgentEventType.TOOL_CALL_ERROR):
            tool_name = event.data.get("tool_name", "")
            if et == AgentEventType.TOOL_CALL_START and tool_name:
                # 开始调用时记录步骤，默认标记为成功
                if session_id not in self._traces:
                    self._traces[session_id] = []
                self._traces[session_id].append((tool_name, True))
            elif et == AgentEventType.TOOL_CALL_ERROR and tool_name:
                # 调用出错时回查最近同名步骤并标记为失败
                if session_id in self._traces:
                    for i, (name, ok) in reversed(list(enumerate(self._traces[session_id]))):
                        if name == tool_name:
                            self._traces[session_id][i] = (name, False)
                            break

    async def _on_agent_end(self, event: AgentEvent) -> None:
        """Agent 正常结束时，提炼成功轨迹为 Pattern 并注册进化插件。"""
        session_id = event.session_id or event.event_id
        steps = self._traces.pop(session_id, None)
        if steps is None:
            return
        tool_names = [name for name, _ in steps]
        if len(tool_names) < self.MIN_SEQUENCE_LENGTH:
            return
        all_ok = all(ok for _, ok in steps)
        if not all_ok:
            return

        key = self._pattern_key(tool_names)
        if key in self._patterns:
            # 已有模式：更新使用计数与置信度
            self._patterns[key].times_used += 1
            self._patterns[key].times_succeeded += 1
            self._patterns[key].confidence = self._patterns[key].times_succeeded / max(self._patterns[key].times_used, 1)
            self._patterns[key].last_success_at = time.time()
            return

        # 新建 Pattern 并注册为动态插件
        pattern = Pattern(
            name=key.replace("|", "_"),
            tool_sequence=tuple(tool_names),
            times_used=1,
            times_succeeded=1,
            confidence=0.5,
            last_success_at=time.time(),
            source_trace_id=session_id,
        )
        self._patterns[key] = pattern

        plugin_cls = type(
            f"Evolved_{pattern.name}",
            (EvolvedPlugin,),
            {"name": pattern.name, "inject": {}},
        )
        self._evolved_plugins[pattern.name] = plugin_cls
        pm = self._get_plugin_manager()
        if pm is not None:
            pm.register(plugin_cls, {"pattern": pattern})
            self._total_rounds += 1

    async def _on_agent_error(self, event: AgentEvent) -> None:
        """Agent 异常结束时丢弃当前会话轨迹，不提炼 Pattern。"""
        session_id = event.session_id or event.event_id
        self._traces.pop(session_id, None)

    def select_best(self, available: list[str]) -> str | None:
        """使用 UCB1 算法从可用进化技能中选择最佳候选。

        引导期（使用次数 < GUIDED_ROUNDS）的技能会被优先返回，
        超过引导期后按 avg_success + exploration_bonus 排序。
        """
        if not self._evolved_plugins:
            return None
        best = None
        best_score = -1.0
        self._total_rounds = max(self._total_rounds, 1)
        for name, plugin_cls in self._evolved_plugins.items():
            key = name.replace("_", "|")
            pattern = self._patterns.get(key)
            if pattern is None:
                continue
            if name not in available:
                continue
            # 引导轮内直接返回，保证新技能有足够曝光
            if pattern.times_used < self.GUIDED_ROUNDS:
                return name
            if pattern.times_used == 0:
                continue
            avg = pattern.times_succeeded / pattern.times_used
            exploration = math.sqrt(2 * math.log(self._total_rounds) / pattern.times_used)
            score = avg + exploration
            if score > best_score:
                best_score = score
                best = name
        return best

    async def forget_stale(self) -> list[str]:
        """遗忘低质量或长期未使用的进化技能。

        遗忘条件：
        1. 置信度低于阈值；
        2. 引导期后失败率过高；
        3. 超过 FORGET_DECAY_DAYS 天未成功。
        """
        forgotten = []
        now = time.time()
        decay_seconds = self.FORGET_DECAY_DAYS * 86400
        pm = self._get_plugin_manager()

        for key, pattern in list(self._patterns.items()):
            should_forget = False
            if pattern.confidence < self.CONFIDENCE_THRESHOLD:
                should_forget = True
            elif pattern.times_used >= self.GUIDED_ROUNDS:
                guided_fail_rate = 1 - pattern.confidence
                if guided_fail_rate > self.GUIDED_FAIL_THRESHOLD:
                    should_forget = True
            if pattern.last_success_at > 0 and (now - pattern.last_success_at) > decay_seconds:
                should_forget = True

            if should_forget:
                name = pattern.name
                if pm is not None and pm.has(name):
                    await pm.unregister(name)
                self._patterns.pop(key, None)
                self._evolved_plugins.pop(name, None)
                forgotten.append(name)

        return forgotten

    def _get_plugin_manager(self) -> PluginManager | None:
        """尝试从上下文中获取插件管理器，失败返回 None。"""
        try:
            return self.ctx.registry
        except AttributeError:
            return None

    def list_evolved(self) -> list[Pattern]:
        """返回当前所有已学得的 Pattern 列表。"""
        return list(self._patterns.values())