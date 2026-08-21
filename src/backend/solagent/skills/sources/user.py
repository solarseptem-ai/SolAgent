"""
用户技能来源模块。

从用户主目录下的 ~/.solagent/skills 加载 SKILL.md 技能定义文件。
"""
from pathlib import Path


class UserSource:
    """用户技能来源，从用户主目录加载技能。

    Attributes:
        path: 默认路径为 ~/.solagent/skills。
    """

    def __init__(self):
        self.path = Path.home() / ".solagent" / "skills"

    def load(self, loader, registry=None, skill_names: list[str] | None = None) -> int:
        """使用 loader 加载用户目录中的技能。

        Args:
            loader: SkillLoader 实例。
            registry: 可选的注册中心。
            skill_names: 可选的白名单。

        Returns:
            成功加载的技能数量。
        """
        return loader.load_directory(self.path)