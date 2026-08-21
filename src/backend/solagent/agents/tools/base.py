"""Deprecated: use solagent.agents.tools.defs.ToolDef instead."""
from solagent.agents.tools.defs import ToolDef as ToolDef


class BaseTool(ToolDef):
    def __init_subclass__(cls, **kwargs):
        import warnings
        warnings.warn("BaseTool is deprecated, use ToolDef instead", DeprecationWarning, stacklevel=2)
        super().__init_subclass__(**kwargs)