"""
Cordis 模块的统一入口，导出框架的依赖注入容器和插件生命周期管理组件。

Cordis 是 SolAgent 的核心基础设施层，提供层次化的 DI 容器、事件总线、
插件注册表、反射服务、日志服务和追踪代理等能力，支撑 Agent 框架的模块化架构。
"""
from solagent.cordis.context import Context
from solagent.cordis.events import AfterAgentLoopEvent, AgentLifecycleEvent, BeforeAgentLoopEvent, EventsService
from solagent.cordis.fiber import CordisError, Fiber, ValidationError
from solagent.cordis.logger import LOG_DEBUG, LOG_ERROR, LOG_INFO, LOG_WARN, Logger, LoggerService, LogMessage
from solagent.cordis.plugin_manager import PluginManagerService
from solagent.cordis.reflect import Impl, ReflectService
from solagent.cordis.registry import Inject, PluginRuntime, RegistryService
from solagent.cordis.service import Service
from solagent.cordis.traceable import ShadowContext, TraceableProxy, get_traceable
from solagent.cordis.utils import DisposableList, is_bailed

__all__ = [
    "AfterAgentLoopEvent",
    "AgentLifecycleEvent",
    "BeforeAgentLoopEvent",
    "Context",
    "CordisError",
    "DisposableList",
    "EventsService",
    "Fiber",
    "Impl",
    "Inject",
    "LOG_DEBUG",
    "LOG_ERROR",
    "LOG_INFO",
    "LOG_WARN",
    "Logger",
    "LoggerService",
    "LogMessage",
    "PluginManagerService",
    "PluginRuntime",
    "ReflectService",
    "RegistryService",
    "Service",
    "ShadowContext",
    "TraceableProxy",
    "ValidationError",
    "get_traceable",
    "is_bailed",
]