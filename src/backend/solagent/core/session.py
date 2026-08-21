"""会话上下文管理模块，维护单个 Agent 会话的运行时状态。

SessionContext 封装了会话级别的状态数据，包括关联的 Agent 配置、消息历史、
元数据以及生命周期信息。它提供了消息的增删查、历史截取和序列化能力，
是 Agent 执行循环中维护对话上下文的核心状态容器。
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from solagent.schema.agent import AgentConfig
from solagent.schema.messages import Message


class SessionContext:
    """Agent 会话上下文，保存单次用户交互会话的全部运行时状态。

    属性说明：
        id: 会话唯一标识符。
        agent_config: 当前会话使用的 Agent 配置。
        messages: 会话消息历史列表。
        metadata: 会话级扩展元数据。
        created_at: 会话创建时间（UTC）。
        updated_at: 会话最后更新时间（UTC）。
        is_active: 会话是否处于活跃状态。
    """

    def __init__(
        self,
        agent_config: AgentConfig,
        id: str | None = None,
        messages: list[Message] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """初始化会话上下文。

        Args:
            agent_config: Agent 的静态配置。
            id: 会话标识，None 则自动生成 UUID。
            messages: 初始消息列表，None 则为空列表。
            metadata: 初始元数据字典，None 则为空字典。
        """
        self.id = id or str(uuid.uuid4())
        self.agent_config = agent_config
        self.messages: list[Message] = messages or []
        self.metadata: dict[str, Any] = metadata or {}
        self.created_at = datetime.now(UTC)
        self.updated_at = self.created_at
        self.is_active = True

    def add_message(self, msg: Message) -> None:
        """向会话追加一条消息，并更新最后活跃时间。"""
        self.messages.append(msg)
        self.updated_at = datetime.now(UTC)

    def get_history(self, max_messages: int | None = None) -> list[Message]:
        """获取会话消息历史。

        Args:
            max_messages: 返回最近多少条消息，None 则返回全部。

        Returns:
            消息列表，按时间顺序排列。
        """
        if max_messages is None:
            return list(self.messages)
        return self.messages[-max_messages:]

    def clear(self) -> None:
        """清空会话消息历史，保留会话本身和其他元数据。"""
        self.messages.clear()
        self.updated_at = datetime.now(UTC)

    def to_dict(self) -> dict[str, Any]:
        """将会话上下文序列化为字典，便于 JSON 持久化或网络传输。"""
        return {
            "id": self.id,
            "agent_config": self.agent_config.model_dump(),
            "messages": [msg.model_dump() for msg in self.messages],
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "is_active": self.is_active,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionContext:
        """从字典反序列化恢复会话上下文。

        Args:
            data: 由 to_dict() 生成的字典数据。

        Returns:
            恢复后的 SessionContext 实例。
        """
        session = cls(
            id=data["id"],
            agent_config=AgentConfig.model_validate(data["agent_config"]),
            messages=[Message.model_validate(m) for m in data.get("messages", [])],
            metadata=data.get("metadata", {}),
        )
        session.created_at = datetime.fromisoformat(data["created_at"])
        session.updated_at = datetime.fromisoformat(data["updated_at"])
        session.is_active = data.get("is_active", True)
        return session