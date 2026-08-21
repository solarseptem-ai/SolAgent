"""服务工厂：封装 Service 的创建逻辑与自动依赖推断。

ServiceFactory 将具体服务类与其类型绑定，支持延迟实例化；
infer_dependencies 通过反射解析 create() 方法的类型注解，自动识别所需依赖服务。
"""

import logging
from inspect import get_annotations

_logger = logging.getLogger(__name__)

from solagent.services.base import Service
from solagent.services.schema import ServiceType


class ServiceFactory:
    """服务工厂，用于延迟创建指定类型的 Service 实例。

    属性:
        service_class: 具体 Service 子类。
        service_type: 该工厂对应的服务类型枚举。
        dependencies: 该服务依赖的其他服务类型列表（通常由 infer_dependencies 自动填充）。
    """

    def __init__(self, service_class: type[Service], service_type: ServiceType):
        self.service_class = service_class
        self.service_type = service_type
        self.dependencies: list[ServiceType] = []

    def create(self, **kwargs) -> Service:
        """创建并返回 Service 实例，将 kwargs 传递给服务类构造函数。

        参数:
            **kwargs: 传递给 service_class 构造函数的命名参数。

        返回:
            Service 实例。
        """
        return self.service_class(**kwargs)


def infer_dependencies(factory_class: type) -> list[ServiceType]:
    """通过反射自动推断工厂 create() 方法的依赖服务类型。

    扫描 create() 方法参数的类型注解，将匹配 ServiceType 枚举值的服务类型加入依赖列表。

    参数:
        factory_class: 包含 create 方法的 ServiceFactory 子类。

    返回:
        推断出的 ServiceType 依赖列表。
    """
    deps = []
    try:
        hints = get_annotations(factory_class.create)
        for name, hint in hints.items():
            if name == "return":
                continue
            type_name = getattr(hint, "__name__", str(hint)).lower()
            for st in ServiceType:
                if st.value.replace("_service", "") in type_name:
                    deps.append(st)
    except Exception:
        _logger.warning("Service dependency inference failed", exc_info=True)
    return deps