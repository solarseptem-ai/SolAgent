"""Cordis 框架的通用工具模块。

提供 ScopeDict（原型链字典）、DisposableList（有序可清理集合）、
错误组合、构造函数检测以及 bail 判断等基础工具函数，支撑 Cordis 的运行时基础设施。
"""

from __future__ import annotations

import asyncio
import traceback
from collections.abc import Callable, Iterator
from typing import Any


class ScopeDict:
    """基于原型链的字典实现，模拟 JavaScript Object.create() 的语义。

    用于 Cordis 的 _intercept 和 _isolate 作用域，支持层级查找：
    先在自身数据中查找，未命中则沿 parent 链向上查找。
    """

    def __init__(self, parent: "ScopeDict | None" = None, data: dict[str, Any] | None = None) -> None:
        self._parent = parent
        self._data: dict[str, Any] = {}
        if data:
            self._data.update(data)

    @property
    def parent(self) -> "ScopeDict | None":
        """返回父级 ScopeDict，None 表示当前为根节点。"""
        return self._parent

    def own(self, key: str) -> bool:
        """检查键是否直接定义在当前层级（不考虑父级）。"""
        return key in self._data

    def __getitem__(self, key: str) -> Any:
        """沿原型链查找键对应的值，未找到则抛出 KeyError。"""
        if key in self._data:
            return self._data[key]
        if self._parent is not None:
            return self._parent[key]
        raise KeyError(key)

    def __setitem__(self, key: str, value: Any) -> None:
        """在当前层级设置键值对。"""
        self._data[key] = value

    def __contains__(self, key: str) -> bool:
        """检查键是否存在于自身或任意父级中。"""
        return key in self._data or (self._parent is not None and key in self._parent)

    def get(self, key: str, default: Any = None) -> Any:
        """沿原型链查找键，未找到则返回默认值。"""
        try:
            return self[key]
        except KeyError:
            return default

    def keys(self) -> Iterator[str]:
        """返回所有层级中不重复的键迭代器（去重）。"""
        seen: set[str] = set()
        node: ScopeDict | None = self
        while node is not None:
            for k in node._data:
                if k not in seen:
                    seen.add(k)
                    yield k
            node = node._parent

    def __repr__(self) -> str:
        items = {k: self[k] for k in self.keys()}
        return f"ScopeDict({items})"


class DisposableList:
    """有序的可清理对象集合，支持 O(1) 按值删除和逆序清理。

    使用自增序列号（sn）作为内部键，通过 id(value)->sn 的映射实现快速查找。
    常用于管理副作用清理函数、事件监听器等需要生命周期管理的对象。
    """

    def __init__(self) -> None:
        self._sn = 0
        self._map: dict[int, Any] = {}   # sn -> value
        self._weak: dict[int, int] = {}  # id(value) -> sn

    def __len__(self) -> int:
        """返回当前集合中的元素数量。"""
        return len(self._map)

    def push(self, value: Any) -> Callable[[], bool]:
        """向集合追加一个元素，返回用于移除该元素的 dispose 函数。

        Args:
            value: 要管理的对象。

        Returns:
            调用后从集合中移除该对象的函数，返回是否成功移除。
        """
        self._sn += 1
        sn = self._sn
        self._map[sn] = value
        self._weak[id(value)] = sn

        def _dispose() -> bool:
            return self._map.pop(sn, None) is not None

        return _dispose

    def delete(self, value: Any) -> bool:
        """按值从集合中删除元素。

        Args:
            value: 要删除的对象。

        Returns:
            是否成功删除。
        """
        sn = self._weak.pop(id(value), None)
        if sn is not None:
            return self._map.pop(sn, None) is not None
        return False

    def clear(self) -> list[Any]:
        """清空集合并按逆序返回所有元素（后入先出，符合清理顺序约定）。

        Returns:
            逆序排列的元素列表。
        """
        result = list(reversed(self._map.values()))
        self._map.clear()
        return result

    def __iter__(self) -> Iterator[Any]:
        """按插入顺序迭代集合中的元素。"""
        return iter(self._map.values())

    def __contains__(self, value: Any) -> bool:
        """判断指定值是否存在于集合中。"""
        return id(value) in self._weak

    def values(self) -> Iterator[Any]:
        """按逆序迭代集合中的元素（后入先出）。"""
        return reversed(self._map.values())


def is_bailed(value: Any) -> bool:
    """判断值是否表示"已拦截/已处理"（bail 语义）。

    在 Cordis 事件系统中，监听器返回非 None 且非 False 的值表示事件已被处理，
    后续监听器应跳过。
    """
    return value is not None and value is not False


def is_constructor(func: Any) -> bool:
    """判断一个可调用对象是否为类构造函数（而非普通函数或生成器）。

    检测逻辑：
        - 非可调用对象返回 False。
        - async 函数和生成器函数返回 False。
        - 具有自定义 __init__ 方法的类返回 True。
    """
    if not callable(func):
        return False
    if hasattr(func, "__qualname__") and func.__qualname__.startswith("async"):
        return False
    if hasattr(func, "__qualname__") and "Generator" in func.__qualname__:
        return False
    return hasattr(func, "__init__") and func.__init__ is not object.__init__


def compose_error(callback: Callable[[], Any], outer_stack: list[str] | None = None) -> Any:
    """执行回调函数，若发生异常则将外部堆栈帧附加到错误对象上。

    支持同步回调和返回协程的异步回调，便于在跨边界调用时保留完整的错误上下文。

    Args:
        callback: 要执行的回调函数。
        outer_stack: 外部堆栈帧列表，用于补充错误信息。

    Returns:
        回调函数的返回值，或异步包装器（若回调返回协程）。
    """
    try:
        result = callback()
        if asyncio.iscoroutine(result):

            async def _wrap() -> Any:
                try:
                    return await result
                except Exception as e:
                    if outer_stack:
                        _append_stack(e, outer_stack)
                    raise

            return _wrap()
        return result
    except Exception as e:
        if outer_stack:
            _append_stack(e, outer_stack)
        raise


def build_outer_stack(offset: int = 0) -> list[str]:
    """捕获当前调用者的堆栈帧，用于后续的错误组合。

    Args:
        offset: 跳过的栈帧数，用于调整捕获的起点。

    Returns:
        格式化后的堆栈帧字符串列表。
    """
    stack = traceback.extract_stack()
    return [f"  at {frame.filename}:{frame.lineno} in {frame.name}" for frame in stack[:-3 - offset]]


def _append_stack(error: Exception, frames: list[str]) -> None:
    """将外部堆栈帧附加到异常对象的 __cordis_outer__ 属性上。"""
    existing = getattr(error, "__cordis_outer__", [])
    existing.extend(frames)
    error.__cordis_outer__ = existing