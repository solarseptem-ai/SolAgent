"""
技能工具策略模块。

根据当前激活的技能集合，计算允许和禁止使用的工具集合，
实现白名单+黑名单的权限控制。
"""


class SkillToolPolicy:
    """技能工具权限策略。

    合并所有激活技能的 allowed_tools（白名单）和 disallowed_tools（黑名单），
    判断某个工具是否被允许调用。

    Attributes:
        _allowed: 允许使用的工具名称集合。
        _denied: 禁止使用的工具名称集合。
    """

    def __init__(self):
        self._allowed: set[str] = set()
        self._denied: set[str] = set()

    def apply(self, active_skills: list) -> None:
        """根据激活的技能重新计算工具权限。

        Args:
            active_skills: 当前激活的技能对象列表。
        """
        self._allowed.clear()
        self._denied.clear()
        for skill in active_skills:
            self._allowed.update(getattr(skill, "allowed_tools", []))
            self._denied.update(getattr(skill, "disallowed_tools", []))

    def is_allowed(self, tool_name: str) -> bool:
        """判断指定工具是否被允许使用。

        规则：
        1. 若在黑名单中，直接拒绝。
        2. 若白名单非空且工具不在白名单中，拒绝。
        3. 其余情况允许。

        Args:
            tool_name: 工具名称。

        Returns:
            是否允许调用该工具。
        """
        # 黑名单优先
        if tool_name in self._denied:
            return False
        # 白名单存在时仅在白名单内允许
        if self._allowed and tool_name not in self._allowed:
            return False
        return True