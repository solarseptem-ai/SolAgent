"""
服务发现端口 — Agent 注册与查询的抽象接口。

用于多 Agent 场景下的服务注册、按条件查找及注销。
"""
from typing import Protocol

from solagent.schema.agent import AgentCapability


class DiscoveryPort(Protocol):
    """服务发现协议，支持 Agent 注册、查找、注销。"""

    async def register(self, capability: AgentCapability) -> None:
        """注册一个 Agent 的能力到发现服务。

        Args:
            capability: Agent 的能力描述信息。
        """
        ...

    async def find(self, criteria: dict) -> list[AgentCapability]:
        """按条件查找已注册的 Agent 能力。

        Args:
            criteria: 查询条件字典，如 {"tags": ["coding"]}。

        Returns:
            符合条件的 Agent 能力列表。
        """
        ...

    async def deregister(self, agent_id: str) -> None:
        """注销指定 Agent。

        Args:
            agent_id: 要注销的 Agent 唯一标识。
        """
        ...