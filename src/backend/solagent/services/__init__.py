"""服务管理模块：定义 Service 抽象基类、工厂、管理器与依赖注入机制。

提供基于 Cordis 上下文的统一服务发现与生命周期管理能力，
支持服务注册、自动依赖解析和优雅关闭。
"""
from solagent.services.base import Service
from solagent.services.deps import get_service_manager
from solagent.services.factory import ServiceFactory, infer_dependencies
from solagent.services.manager import ServiceManager
from solagent.services.schema import ServiceType

__all__ = ["Service", "ServiceFactory", "ServiceManager", "ServiceType", "get_service_manager", "infer_dependencies"]