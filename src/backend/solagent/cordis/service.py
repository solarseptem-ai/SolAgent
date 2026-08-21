"""Cordis 服务基类，提供自动注册、生命周期钩子和配置解析能力。

本模块定义了所有 Cordis 服务的公共基类。服务在构造时自动通过 ctx.reflect.provide()
注册到依赖注入容器中，支持拦截配置合并、上下文过滤和属性扩展等高级功能。
"""

from __future__ import annotations

from typing import Any

from solagent.cordis.symbols import CHECK, CONFIG, EXTEND, INIT, RESOLVE_CONFIG


class Service:
    """Cordis 服务基类。

    构造函数会自动将服务实例注册到当前上下文的反射服务中，
    使其可通过 ctx.service_name 的方式被其他组件访问。
    支持代理/可调用包装后的 isinstance 检查。
    """

    # 绑定生命周期钩子符号，子类可覆盖这些静态属性来定制行为
    init = INIT
    check = CHECK
    config = CONFIG
    extend = EXTEND
    resolveConfig = RESOLVE_CONFIG

    name: str = ""
    ctx: Any = None

    def __init__(self, ctx: Any, name: str, check: Any = None) -> None:
        """初始化服务并自动注册到 DI 容器。

        Args:
            ctx: 所属 Cordis 上下文。
            name: 服务注册名称，其他组件通过该名称引用此服务。
            check: 可选的可用性检查函数。
        """
        self.ctx = ctx
        self.name = name
        self._check = check

        # 自动注册到反射服务，使 ctx.name 可直接访问该服务
        if name:
            self.ctx.reflect.provide(self.ctx, name, self, check)

    @classmethod
    def __instancecheck__(cls, instance: Any) -> bool:
        """支持对代理或 callable 包装后的服务实例进行 isinstance 检查。

        通过遍历 MRO 链来判断实例是否属于 Service 类型层次。
        """
        if not instance:
            return False
        constructor = type(instance)
        while constructor is not None:
            if constructor is cls:
                return True
            constructor = getattr(constructor, "__base__", None)
        return False

    def _filter(self, ctx: Any) -> bool:
        """上下文过滤器，判断目标上下文是否与本服务处于同一隔离作用域。"""
        return ctx._isolate.get(self.name) == self.ctx._isolate.get(self.name)

    def _extend(self, props: dict[str, Any] | None = None) -> "Service":
        """创建当前服务的浅拷贝副本，可覆盖部分属性。

        Args:
            props: 要覆盖的属性字典。

        Returns:
            新的 Service 实例，共享原实例的大部分状态。
        """
        cls = type(self)
        instance = cls.__new__(cls)
        instance.__dict__.update(self.__dict__)
        if props:
            instance.__dict__.update(props)
        return instance

    def _resolve_config(self, base: Any = None, head: Any = None) -> Any:
        """从拦截器链中解析并合并服务的配置。

        遍历上下文的 _intercept 层级（从祖先到当前），收集所有与本服务相关的
        配置片段，按顺序合并。若配置项为字典则执行深度合并，否则返回最后遇到的值。

        Args:
            base: 基础配置，作为合并的起点。
            head: 最高优先级配置，覆盖其他所有配置。

        Returns:
            合并后的配置对象，若无配置则返回 None。
        """
        intercept = getattr(self.ctx, "_intercept", {})
        configs: list[Any] = []
        # 沿拦截器链从祖先到当前收集配置
        while hasattr(intercept, "own"):
            if intercept.own(self.name):
                configs.insert(0, intercept[self.name])
            intercept = intercept.parent
        if base is not None:
            configs.insert(0, base)
        if head is not None:
            configs.append(head)
        if configs and isinstance(configs[0], dict):
            result: dict[str, Any] = {}
            for c in configs:
                if isinstance(c, dict):
                    result.update(c)
            return result
        if configs:
            return configs[-1]
        return None