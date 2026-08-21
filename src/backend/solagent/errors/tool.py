"""工具调用相关的异常类型。"""

from solagent.errors.base import AgentError


class ToolError(AgentError):
    """工具相关错误的基类。"""


class ToolNotFoundError(ToolError):
    """请求调用的工具在注册表中不存在。

    Attributes:
        tool_name: 未找到的工具名称。
    """

    def __init__(self, tool_name: str, message: str | None = None):
        super().__init__(message or f"Tool not found: {tool_name}")
        self.tool_name = tool_name


class ToolExecutionError(ToolError):
    """工具执行过程中发生错误（如参数非法、运行时异常等）。

    Attributes:
        tool_name: 执行失败的工具名称。
    """

    def __init__(self, tool_name: str, message: str):
        super().__init__(f"Tool '{tool_name}' execution failed: {message}")
        self.tool_name = tool_name