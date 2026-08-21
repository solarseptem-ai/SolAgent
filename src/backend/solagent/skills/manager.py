"""
技能管理器模块。

整合技能注册、加载、激活和工具策略，提供一站式技能生命周期管理。
支持内置、用户、项目三种来源的技能加载。
"""
from pathlib import Path

from solagent.skills.activation import SkillActivation
from solagent.skills.loader import SkillLoader
from solagent.skills.registry import SkillRegistry
from solagent.skills.sources.builtin import BuiltinSource
from solagent.skills.sources.project import ProjectSource
from solagent.skills.sources.user import UserSource
from solagent.skills.tool_policy import SkillToolPolicy


class SkillManager:
    """技能管理器，统筹技能注册、加载、激活和工具策略。

    Attributes:
        _registry: 技能注册中心。
        _activation: 技能激活管理器。
        _policy: 工具权限策略。
        _loader: 技能加载器。
        _sources: 技能来源列表（内置、用户、项目）。
    """

    def __init__(self, builtin_dir: str | None = None,
                 user_dir: str | None = None,
                 project_dir: str | None = None):
        self._registry = SkillRegistry()
        self._activation = SkillActivation(self._registry)
        self._policy = SkillToolPolicy()
        self._loader = SkillLoader(self._registry)
        self._sources: list = []
        # 根据传入的目录参数初始化对应的技能来源
        if builtin_dir:
            self._sources.append(BuiltinSource(Path(builtin_dir)))
        if user_dir:
            self._sources.append(UserSource())
        if project_dir:
            self._sources.append(ProjectSource(project_dir))

    def load(self, skill_names: list[str] | None = None) -> int:
        """从所有来源加载技能。

        Args:
            skill_names: 可选的白名单，仅加载指定名称的技能。

        Returns:
            成功加载的技能总数。
        """
        count = 0
        for source in self._sources:
            count += source.load(self._loader, self._registry, skill_names)
        return count

    def match_triggers(self, text: str) -> list:
        """根据文本匹配技能触发词。

        Args:
            text: 用户输入文本。

        Returns:
            匹配到的技能列表。
        """
        return self._activation.match_triggers(text)

    def get_active(self) -> list:
        """获取当前所有激活的技能。"""
        return self._activation.get_active()

    def get_tool_policy(self) -> SkillToolPolicy:
        """根据当前激活的技能生成工具权限策略。

        Returns:
            已应用当前激活技能的工具策略实例。
        """
        self._policy.apply(self._activation.get_active())
        return self._policy

    def activate(self, name: str) -> bool:
        """显式激活指定技能。

        Args:
            name: 技能名称。

        Returns:
            是否激活成功。
        """
        return self._activation.activate(name)

    @property
    def registry(self) -> SkillRegistry:
        """技能注册中心实例。"""
        return self._registry