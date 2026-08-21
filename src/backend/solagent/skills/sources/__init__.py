"""
技能来源（Source）聚合导出。

提供三种技能来源：内置（BuiltinSource）、项目（ProjectSource）、用户（UserSource）。
每种来源负责从不同路径加载 SKILL.md 技能定义。
"""
from solagent.skills.sources.builtin import BuiltinSource
from solagent.skills.sources.project import ProjectSource
from solagent.skills.sources.user import UserSource

__all__ = ["BuiltinSource", "ProjectSource", "UserSource"]