"""Agent 预设的数据类型定义。

AgentPreset 是对 Agent 配置单元的数据封装，包含人格、工具、提示词等字段，
用于在预设目录中被 discovery 模块扫描和加载。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AgentPreset:
    """Agent 预设配置单元。

    属性:
        id: 预设的唯一标识。
        path: 预设所在的文件系统路径。
        name: 预设的显示名称。
        description: 预设的用途描述。
        persona: 预设的人格/角色描述文本。
        tools: 该预设默认启用的工具名列表。
        prompts: 预设附带的额外提示词字典。
        broken: 预设是否加载失败。
        broken_reason: 加载失败的原因说明。
    """
    id: str
    path: Path
    name: str = ""
    description: str = ""
    persona: str | None = None
    tools: list[str] = field(default_factory=list)
    prompts: dict[str, str] = field(default_factory=dict)
    broken: bool = False
    broken_reason: str = ""

    @property
    def is_broken(self) -> bool:
        """当前预设是否处于损坏/无法使用状态。"""
        return self.broken