"""
技能激活管理模块。

根据触发条件或显式调用激活技能，维护当前激活的技能集合。
始终激活的技能（always_active）会与动态激活的技能合并返回。
"""


class SkillActivation:
    """技能激活管理器。

    维护一个显式激活的技能名称集合，并支持通过触发词自动匹配激活。

    Attributes:
        _registry: 技能注册中心，用于查询技能信息。
        _active: 当前被显式激活的技能名称集合。
    """

    def __init__(self, registry):
        self._registry = registry
        self._active: set[str] = set()

    def activate(self, name: str) -> bool:
        """显式激活指定名称的技能。

        Args:
            name: 技能名称。

        Returns:
            若技能存在于注册中心且激活成功则返回 True，否则返回 False。
        """
        if self._registry.get(name):
            self._active.add(name)
            return True
        return False

    def deactivate(self, name: str) -> None:
        """取消激活指定名称的技能。

        Args:
            name: 技能名称。
        """
        self._active.discard(name)

    def match_triggers(self, text: str) -> list:
        """根据输入文本匹配触发词并自动激活对应技能。

        Args:
            text: 用户输入文本。

        Returns:
            匹配到的技能列表。
        """
        matched = self._registry.find_by_trigger(text)
        for s in matched:
            self._active.add(s.name)
        return matched

    def get_active(self) -> list:
        """获取当前所有应激活的技能列表。

        合并始终激活（always_active）和动态激活的技能。

        Returns:
            当前激活的技能对象列表。
        """
        always = self._registry.list_always_active()
        active_names = {s.name for s in always}
        active_names.update(self._active)
        return [s for s in self._registry.list_all() if s.name in active_names]