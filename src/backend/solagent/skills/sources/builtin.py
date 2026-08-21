"""
内置技能来源模块。

从框架内置目录加载 SKILL.md 技能定义文件。
"""
from pathlib import Path


class BuiltinSource:
    """内置技能来源，从指定目录加载技能。

    Attributes:
        path: 技能文件所在的目录路径。
    """

    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self, loader, registry=None, skill_names: list[str] | None = None) -> int:
        """使用 loader 加载内置目录中的技能。

        Args:
            loader: SkillLoader 实例。
            registry: 可选的注册中心（loader 内部已持有）。
            skill_names: 可选的白名单。

        Returns:
            成功加载的技能数量。
        """
        return loader.load_directory(self.path)