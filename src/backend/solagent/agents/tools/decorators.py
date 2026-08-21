"""工具注册装饰器。对标 hermes-agent 自注册模式。"""
from typing import Callable


def register_tool(
    toolset: str = "core",
    priority: int = 0,
    check_fn: Callable[[], bool] | None = None,
    requires_env: list[str] | None = None,
):
    def decorator(cls):
        cls._tool_meta = {
            "toolset": toolset,
            "priority": priority,
            "check_fn": check_fn,
            "requires_env": requires_env or [],
        }
        return cls
    return decorator