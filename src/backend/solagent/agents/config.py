"""Agent 配置的 YAML 序列化与反序列化模块。

提供将运行中的 Agent 状态导出为 YAML 快照的能力，以及从 YAML 文件恢复配置的功能。
适用于配置持久化、版本管理和 Agent 实例的克隆/迁移场景。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from solagent.schema.agent import AgentSnapshot, ProviderConfig

if TYPE_CHECKING:
    from solagent.agents.base import BaseAgent


class AgentSerializer:
    """Agent 配置的 YAML 序列化器。

    将 BaseAgent 的运行时配置（模型参数、工具列表、终止条件等）导出为结构化的 YAML 快照，
    便于保存到文件系统或纳入版本控制；也支持从 YAML 还原为 AgentSnapshot 对象。
    """

    @staticmethod
    def save(agent: "BaseAgent", path: Path) -> None:
        """将 Agent 的当前配置保存为 YAML 文件。

        参数:
            agent: 要导出配置的 Agent 实例。
            path: 目标 YAML 文件路径。
        """
        provider_type = agent.provider.__class__.__name__.lower().replace("provider", "")
        snapshot = AgentSnapshot(
            config=agent.config,
            provider=ProviderConfig(
                provider_type=provider_type,
                model=agent.config.model,
                temperature=agent.config.temperature,
                max_tokens=agent.config.max_tokens,
            ),
            tools=agent.tools.to_snapshot(),
            termination=getattr(agent.config, 'termination_conditions', []),
        )
        path.write_text(
            yaml.dump(snapshot.model_dump(exclude_none=True, mode="json"), default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )

    @staticmethod
    def load(path: Path) -> AgentSnapshot:
        """从 YAML 文件加载 Agent 配置快照。

        参数:
            path: YAML 文件路径。

        返回:
            解析并校验后的 AgentSnapshot 对象。
        """
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return AgentSnapshot.model_validate(data)