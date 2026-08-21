"""Mode registry with thread-safe access."""
import asyncio
from typing import ClassVar

from solagent.agents.base import AgentContext, BaseAgent
from solagent.schema.agent import AgentMode


class ModeRegistry:
    _modes: ClassVar[dict[AgentMode, type[BaseAgent]]] = {}
    _lock: ClassVar[asyncio.Lock] = asyncio.Lock()
    
    @classmethod
    async def register(cls, mode: AgentMode, agent_cls: type[BaseAgent]) -> None:
        async with cls._lock:
            cls._modes[mode] = agent_cls
    
    @classmethod
    def register_sync(cls, mode: AgentMode, agent_cls: type[BaseAgent]) -> None:
        cls._modes[mode] = agent_cls
    
    @classmethod
    def get(cls, mode: AgentMode) -> type[BaseAgent]:
        if mode not in cls._modes:
            raise KeyError(f"Mode '{mode}' not registered. Available: {list(cls._modes.keys())}")
        return cls._modes[mode]
    
    @classmethod
    def create(cls, mode: AgentMode, ctx: AgentContext) -> BaseAgent:
        return cls.get(mode)(ctx)
    
    @classmethod
    def list_modes(cls) -> list[AgentMode]:
        return list(cls._modes.keys())
