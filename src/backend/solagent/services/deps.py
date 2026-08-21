"""服务依赖管理：提供全局 ServiceManager 单例的获取函数。

作为服务定位器模式（Service Locator）的简易实现，
方便在无法直接注入依赖的场景（如路由处理器、工具函数）中快速获取服务实例。
"""

from solagent.services.manager import ServiceManager

_default_manager: ServiceManager | None = None


def get_service_manager() -> ServiceManager:
    """获取全局默认的 ServiceManager 单例；若不存在则自动创建。

    返回:
        ServiceManager 实例。
    """
    global _default_manager
    if _default_manager is None:
        _default_manager = ServiceManager()
    return _default_manager