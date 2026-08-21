"""
技能加载器模块。

扫描目录下的 SKILL.md 文件，解析为 SkillTemplate 并注册到 SkillRegistry。
支持按指定技能名称白名单过滤加载。
"""
import logging
from pathlib import Path

from solagent.skills.registry import SkillRegistry
from solagent.skills.template import SkillTemplate

_logger = logging.getLogger(__name__)


class SkillLoader:
    """技能加载器，负责从文件系统加载 Markdown 格式的技能定义。

    Attributes:
        _registry: 技能注册中心，加载后的技能将注册到此。
    """

    def __init__(self, registry: SkillRegistry):
        self._registry = registry

    def load_directory(self, path: Path, skill_names: list[str] | None = None) -> int:
        """递归扫描目录，加载所有 SKILL.md 技能文件。

        Args:
            path: 要扫描的目录路径。
            skill_names: 若指定，仅加载名称在此列表中的技能；为 None 则加载全部。

        Returns:
            成功加载并注册的技能数量。
        """
        count = 0
        if not path.exists():
            return 0
        # 递归查找所有 SKILL.md 文件
        for md_file in path.glob("**/SKILL.md"):
            try:
                skill = SkillTemplate.from_markdown(md_file.read_text())
                if skill.name:
                    # 若指定了白名单且不在白名单中，则跳过
                    if skill_names is not None and skill.name not in skill_names:
                        continue
                    self._registry.register(skill)
                    count += 1
            except Exception:
                _logger.warning("Skill loading failed", exc_info=True)
        return count