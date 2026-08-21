"""预设扫描与加载模块。

负责在指定的根目录中遍历子目录，识别符合命名规范的预设文件夹，
并读取其中的 preset.yaml 文件解析为 AgentPreset 对象。对于格式不正确或缺失配置文件的预设，
会标记为 broken 状态并附带原因，避免在后续流程中引发崩溃。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

from solagent.presets.types import AgentPreset

_logger = logging.getLogger(__name__)

# 预设 ID 的合法命名正则：小写字母、数字、连字符，且不能以连字符开头
_PRESET_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def discover_presets(roots: list[Path]) -> list[AgentPreset]:
    """扫描多个根目录下的预设文件夹，返回解析后的 AgentPreset 列表。

    参数:
        roots: 需要扫描的根目录路径列表。

    返回:
        所有合法预设的列表，重复 ID 会去重保留首次出现的。
    """
    """Scan preset roots for valid preset directories."""
    presets: list[AgentPreset] = []
    seen: set[str] = set()

    for root in roots:
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            if not entry.is_dir():
                continue
            preset_id = entry.name
            if not _PRESET_ID_RE.match(preset_id):
                continue
            if preset_id in seen:
                continue
            seen.add(preset_id)

            preset = _load_preset(preset_id, entry)
            presets.append(preset)

    return presets


def _load_preset(preset_id: str, directory: Path) -> AgentPreset:
    """读取单个预设目录中的 preset.yaml 并解析为 AgentPreset。

    参数:
        preset_id: 预设的唯一标识（通常为目录名）。
        directory: 预设所在的目录路径。

    返回:
        解析成功返回完整的 AgentPreset；若文件缺失或 YAML 格式错误，
        则返回标记为 broken 的 AgentPreset 并附带原因。
    """
    preset_yaml = directory / "preset.yaml"
    if not preset_yaml.is_file():
        return AgentPreset(
            id=preset_id, path=directory,
            broken=True, broken_reason=f"missing preset.yaml in {directory}",
        )

    try:
        data = yaml.safe_load(preset_yaml.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        return AgentPreset(
            id=preset_id, path=directory,
            broken=True, broken_reason=f"invalid YAML: {e}",
        )

    return AgentPreset(
        id=preset_id,
        path=directory,
        name=data.get("name", preset_id),
        description=data.get("description", ""),
        persona=data.get("persona"),
        tools=data.get("tools", []),
        prompts=data.get("prompts", {}),
    )