"""Agent 预设（Preset）模块的入口。

预设是将一组配置（人格、工具、提示词等）打包为可复用单元，便于快速部署具有特定能力的 Agent。
本模块提供预设的扫描发现（discovery）、挂载到上下文（mount）以及预设类型定义（types）。
"""

from solagent.presets.discovery import discover_presets
from solagent.presets.mount import compose_presets, mount_preset
from solagent.presets.types import AgentPreset

__all__ = ["AgentPreset", "compose_presets", "discover_presets", "mount_preset"]