"""服务管理器：统一管理 Service 的注册、延迟实例化、依赖注入与生命周期关闭。

内部维护工厂注册表和实例缓存，支持递归解析依赖树；
同时将已创建的服务注册到 Cordis DI 上下文，供框架其他部分统一消费。
"""

from solagent.cordis import Context
from solagent.services.base import Service
from solagent.services.factory import ServiceFactory
from solagent.services.schema import ServiceType


class ServiceManager:
    """Service 统一管理者。

    属性:
        _factories: 已注册的服务工厂字典（ServiceType -> ServiceFactory）。
        _services: 已实例化的服务缓存字典（ServiceType -> Service）。
        _ctx: Cordis DI 上下文，用于向框架提供已创建的服务实例。
    """

    def __init__(self):
        self._factories: dict[ServiceType, ServiceFactory] = {}
        self._services: dict[ServiceType, Service] = {}
        self._ctx = Context()

    def register_factory(self, factory: ServiceFactory) -> None:
        """注册一个服务工厂。

        参数:
            factory: 要注册的服务工厂实例。
        """
        self._factories[factory.service_type] = factory

    def get(self, service_type: ServiceType) -> Service:
        """获取指定类型的服务实例；若尚未创建，则通过工厂延迟实例化并递归解析依赖。

        参数:
            service_type: 要获取的服务类型枚举。

        返回:
            对应类型的 Service 实例。

        异常:
            KeyError: 当未注册对应类型的工厂时抛出。
        """
        if service_type in self._services:
            return self._services[service_type]
        if service_type not in self._factories:
            raise KeyError(f"No factory registered for {service_type}")
        factory = self._factories[service_type]
        # 递归解析并注入依赖服务
        kwargs = {}
        for dep in factory.dependencies:
            kwargs[dep.value] = self.get(dep)
        service = factory.create(**kwargs)
        service.set_ready()
        self._services[service_type] = service
        self._ctx.provide(service_type.value, service)
        return service

    def list_registered(self) -> list[ServiceType]:
        """返回当前已注册的所有服务类型列表。"""
        return list(self._factories.keys())

    async def teardown_all(self) -> None:
        """依次调用所有已创建服务的 teardown 方法，清空缓存并释放 Cordis 上下文资源。"""
        for service in self._services.values():
            await service.teardown()
        self._services.clear()
        await self._ctx.dispose_all()