"""
项目技能来源模块。

从用户项目目录加载 SKILL.md 技能定义文件，支持按技能名称白名单过滤。
"""
from pathlib import Path


class ProjectSource:
    """项目技能来源，从项目指定目录加载技能。

    Attributes:
        path: 项目技能文件所在的目录路径。
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self, loader, registry=None, skill_names=None) -> int:
        """使用 loader 加载项目目录中的技能。

        Args:
            loader: SkillLoader 实例。
            registry: 可选的注册中心。
            skill_names: 可选的白名单，仅加载指定名称的技能。

        Returns:
            成功加载的技能数量。
        """
        return loader.load_directory(self.path, skill_names)