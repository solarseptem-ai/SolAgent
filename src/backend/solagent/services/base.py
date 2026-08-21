"""Service 抽象基类：定义所有可管理服务的通用接口与生命周期钩子。

子类需实现 name 属性，并可通过 ready/set_ready 管理初始化状态，
teardown 方法用于释放资源（如关闭连接、清理缓存等）。
"""

from abc import ABC, abstractmethod


class Service(ABC):
    """所有可管理服务的抽象基类。

    属性:
        _ready: 服务是否已完成初始化。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """服务的唯一名称标识，子类必须实现。"""
        ...

    @property
    def ready(self) -> bool:
        """返回服务当前是否已就绪。"""
        return self._ready

    def __init__(self):
        self._ready = False

    def set_ready(self) -> None:
        """标记服务为就绪状态，通常在初始化完成后调用。"""
        self._ready = True

    async def teardown(self) -> None:
        """服务关闭时的资源释放钩子，子类可重写以实现自定义清理逻辑。"""
        pass