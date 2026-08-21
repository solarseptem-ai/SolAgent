"""多层 YAML 配置加载器。

支持三层配置合并（默认值 → 用户目录 → 项目目录），并提供环境变量解析功能。
合并策略采用深度合并：字典递归合并，列表按 name/model 键去重后追加。
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

_HAS_YAML = False
try:
    import yaml

    _HAS_YAML = True
except ImportError:
    yaml = None  # type: ignore

from solagent.config.config_model import AppConfig

_DEFAULTS_PATH = Path(__file__).parent / "defaults.yaml"


class ConfigLoader:
    """多层配置加载器，负责从多个来源加载并合并 YAML 配置。

    加载优先级（后加载的覆盖先加载的）：
        1. 内置默认值（defaults.yaml 或硬编码）
        2. 用户目录配置（~/.solagent/config.yaml）
        3. 项目目录配置（<project_path>/solagent.yaml）
    """

    _ENV_VAR_RE = re.compile(r"\$\{(\w+)\}|\$(\w+)")

    _DEFAULT_CONFIG_YAML = """\
default_model: gpt-4o
default_mode: react
log:
  level: INFO
  format: json
providers: []
agents: []
mcp_servers: []
tools: []
skills: []
"""

    def __init__(self, project_path: str | Path | None = None) -> None:
        """
        Args:
            project_path: 项目根目录路径，默认使用当前工作目录。
        """
        self._project_path = Path(project_path) if project_path else Path.cwd()
        self._user_config_dir = Path.home() / ".solagent"
        self._user_config_file = self._user_config_dir / "config.yaml"
        self._project_config_file = self._project_path / "solagent.yaml"

    def _load_defaults(self) -> dict[str, Any]:
        """加载默认配置，优先从 defaults.yaml 文件读取，回退到内置 YAML 字符串。"""
        if _DEFAULTS_PATH.exists():
            result = self._read_yaml(_DEFAULTS_PATH)
            if result:
                return result
        if _HAS_YAML:
            import yaml as _yaml
            return _yaml.safe_load(self._DEFAULT_CONFIG_YAML) or {}
        return {}

    def load(self) -> AppConfig:
        """执行完整的多层配置加载、合并、环境变量解析，并返回 AppConfig 实例。

        Returns:
            合并后的应用配置对象。
        """
        layers: list[dict[str, Any]] = []

        layers.append(self._load_defaults())

        if self._user_config_file.exists():
            layers.append(self._read_yaml(self._user_config_file))

        if self._project_config_file.exists():
            layers.append(self._read_yaml(self._project_config_file))

        merged = self._merge_dicts(layers)
        merged = self._resolve_env_vars(merged)
        merged = self._resolve_provider_configs(merged)
        return AppConfig(**merged)

    def _read_yaml(self, path: Path) -> dict[str, Any]:
        """读取单个 YAML 文件并返回字典。

        Args:
            path: YAML 文件路径。

        Returns:
            解析后的字典，出错或 yaml 未安装时返回空字典。
        """
        if yaml is None:
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except yaml.YAMLError as e:
            import sys
            print(f"Warning: YAML parse error in {path}: {e}", file=sys.stderr)
            return {}

    def _merge_dicts(self, layers: list[dict[str, Any]]) -> dict[str, Any]:
        """将多层配置字典深度合并为单一字典。"""
        result: dict[str, Any] = {}
        for layer in layers:
            self._deep_merge(result, layer)
        return result

    def _deep_merge(self, base: dict[str, Any], overlay: dict[str, Any]) -> None:
        """递归深度合并两个字典。

        合并规则：
            - 字典：递归合并。
            - 列表：按 name/model 键去重，保留 overlay 中的项并追加到 base。
            - 其他：overlay 直接覆盖 base。
        """
        for key, value in overlay.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            elif key in base and isinstance(base[key], list) and isinstance(value, list):
                overlaid = {self._list_item_key(item) for item in value}
                base[key] = [item for item in base[key] if self._list_item_key(item) not in overlaid]
                base[key].extend(value)
            else:
                base[key] = value

    @staticmethod
    def _list_item_key(item: Any) -> str:
        """从列表项中提取用于去重的标识键。

        优先使用 "name" 字段，其次 "model" 字段，否则返回整个项的字符串表示。
        """
        if isinstance(item, dict):
            name = item.get("name")
            if name is not None:
                return str(name)
            model = item.get("model")
            if model is not None:
                return str(model)
            return ""
        return str(item)

    def _resolve_env_vars(self, data: Any) -> Any:
        """递归解析字符串中的环境变量引用（${VAR} 或 $VAR）。

        若环境变量未设置，替换为空字符串。
        """
        if isinstance(data, dict):
            return {k: self._resolve_env_vars(v) for k, v in data.items()}
        if isinstance(data, list):
            return [self._resolve_env_vars(item) for item in data]
        if isinstance(data, str):
            return self._ENV_VAR_RE.sub(
                lambda m: os.getenv(m.group(1) or m.group(2) or "", ""), data
            )
        return data

    def _resolve_provider_configs(self, merged: dict[str, Any]) -> dict[str, Any]:
        """解析提供商配置中的环境变量引用和默认值。

        若指定了 api_key_env 但未指定 api_key，则从对应环境变量读取。
        若未指定 display_name，则默认使用 name。
        """
        providers = merged.get("providers", [])
        if not isinstance(providers, list):
            return merged
        for pc in providers:
            if isinstance(pc, dict):
                if pc.get("api_key_env") and not pc.get("api_key"):
                    pc["api_key"] = os.getenv(pc["api_key_env"], "")
                if not pc.get("display_name"):
                    pc["display_name"] = pc.get("name", "")
        return merged