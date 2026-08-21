"""DEPRECATED: MultiAgentProtocol is replaced by solagent.ports.agent_port.AgentPort.
This module is kept for backward compatibility and will be removed in a future version."""

from typing import Protocol


class MultiAgentProtocol(Protocol):
    async def execute(self, tasks: list, config) -> list: ...