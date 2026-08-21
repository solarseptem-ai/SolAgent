"""
技能注册中心模块。

以名称为键存储技能对象，支持按标签、触发词、始终激活等条件查询。
"""


class SkillRegistry:
    """技能注册中心。

    Attributes:
        _skills: 技能名称到技能对象的映射字典。
    """

    def __init__(self):
        self._skills: dict[str, object] = {}

    def register(self, skill) -> None:
        """注册一个技能。

        Args:
            skill: 技能对象，需具有 name 属性。
        """
        self._skills[skill.name] = skill

    def get(self, name: str):
        """按名称获取技能。

        Args:
            name: 技能名称。

        Returns:
            技能对象，若不存在则返回 None。
        """
        return self._skills.get(name)

    def find_by_tag(self, tag: str) -> list:
        """按标签查找技能。

        Args:
            tag: 标签名称。

        Returns:
            包含该标签的技能列表。
        """
        return [s for s in self._skills.values() if tag in getattr(s, "tags", [])]

    def find_by_trigger(self, text: str) -> list:
        """按触发词查找技能（不区分大小写）。

        Args:
            text: 用户输入文本。

        Returns:
            触发词包含在输入文本中的技能列表。
        """
        return [
            s
            for s in self._skills.values()
            if any(t.lower() in text.lower() for t in getattr(s, "triggers", []))
        ]

    def list_always_active(self) -> list:
        """列出所有始终激活的技能。"""
        return [s for s in self._skills.values() if getattr(s, "always_active", False)]

    def list_all(self) -> list:
        """列出所有已注册的技能。"""
        return list(self._skills.values())

    def __len__(self) -> int:
        """返回已注册技能数量。"""
        return len(self._skills)