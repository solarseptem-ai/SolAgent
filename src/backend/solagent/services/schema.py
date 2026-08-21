"""服务类型枚举：定义框架中所有可管理的服务分类标识。

各服务类型用于工厂注册、依赖解析和服务发现，
确保不同类型的服务在 DI 容器中有唯一的标识键。
"""
from enum import Enum


class ServiceType(str, Enum):
    """框架支持的服务类型枚举。

    每个枚举值同时作为 Cordis DI 上下文中的服务键名，
    也是 ServiceFactory 和 ServiceManager 进行注册与查找的依据。
    """
    SETTINGS_SERVICE = "settings_service"
    LLM_SERVICE = "llm_service"
    TOOL_SERVICE = "tool_service"
    MEMORY_SERVICE = "memory_service"
    AGENT_SERVICE = "agent_service"
    MCP_SERVICE = "mcp_service"
    SANDBOX_SERVICE = "sandbox_service"
    SKILL_SERVICE = "skill_service"
    KNOWLEDGE_SERVICE = "knowledge_service"