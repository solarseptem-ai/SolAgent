"""
技能（Skill）模块聚合导出。

提供 Agent 技能的完整生命周期管理：加载（Loader）、注册（Registry）、
激活（Activation）、管理（Manager）、模板解析（Template）以及工具策略（ToolPolicy）。
"""
from solagent.skills.activation import SkillActivation
from solagent.skills.loader import SkillLoader
from solagent.skills.manager import SkillManager
from solagent.skills.registry import SkillRegistry
from solagent.skills.template import SkillTemplate
from solagent.skills.tool_policy import SkillToolPolicy

__all__ = ["SkillActivation", "SkillLoader", "SkillManager", "SkillRegistry", "SkillTemplate", "SkillToolPolicy"]