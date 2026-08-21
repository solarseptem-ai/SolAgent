"""Fiber 插件生命周期状态机 —— 6 种状态、基于 epoch 的响应式依赖追踪。

Fiber 是 Cordis 框架管理插件完整生命周期的核心组件。
每个插件实例对应一个 Fiber，状态迁移由依赖可用性（epoch）驱动：
当所有注入的依赖都就绪时，Fiber 从 PENDING 进入 LOADING 再到 ACTIVE；
当任一依赖丢失时，Fiber 进入 UNLOADING 并回到 PENDING。

状态机：
  PENDING ──(deps ready)──▶ LOADING ──(ok)──▶ ACTIVE
     ▲                         │                 │
     │                    (error)                │(deps lost)
     │                         ▼                 ▼
     │                      FAILED          UNLOADING ──(ok)──▶ PENDING
     │                         │                                │
     │                    (deps back)                      (deps back)
     │                         │                                │
     └─────────────────────────┴────────────────────────────────┘
  任意状态 ──(dispose)──▶ DISPOSED
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator, Callable, Generator
from typing import Any

from solagent.cordis.symbols import (
    FIBER_ACTIVE,
    FIBER_DISPOSED,
    FIBER_FAILED,
    FIBER_LOADING,
    FIBER_PENDING,
    FIBER_UNLOADING,
    INACTIVE,
    INIT,
    INIT_HOOKS,
)
from solagent.cordis.utils import DisposableList, is_constructor

_logger = logging.getLogger(__name__)

Disposer = Callable[..., Any]  # 清理函数类型别名


class ValidationError(TypeError):
    """插件配置验证失败时抛出的异常。"""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.name = "ValidationError"


class CordisError(RuntimeError):
    """Cordis 框架级错误（例如在已释放的 Fiber 上注册 effect）。"""


def _resolve_config(runtime: Any, config: Any) -> Any:
    """通过 runtime.Config 验证并规范化插件配置。

    支持三种配置校验方式：
        1. 无 Config：直接返回原始配置。
        2. callable Config：调用函数进行校验。
        3. Pydantic model Config：使用 model_validate 进行模型校验。

    Args:
        runtime: 插件运行时对象，可能包含 Config 属性。
        config: 原始配置数据。

    Returns:
        校验通过后的配置对象。

    Raises:
        ValidationError: 配置校验失败时抛出。
    """
    if not runtime or not hasattr(runtime, "Config") or runtime.Config is None:
        return config
    schema = runtime.Config
    if callable(schema):
        try:
            return schema(config)
        except Exception as e:
            if isinstance(e, ValidationError):
                raise
            raise ValidationError(str(e)) from e
    try:
        # 检测 Pydantic 模型并执行模型校验
        if hasattr(schema, "model_validate"):
            return schema.model_validate(config)
    except Exception as e:
        raise ValidationError(str(e)) from e
    return config


class Fiber:
    """插件生命周期状态机，基于 epoch 字符串实现响应式依赖追踪。

    Fiber 管理一个插件实例从创建到释放的完整生命周期。
    核心机制：
        - epoch：由所有依赖实现的 id 拼接而成的字符串指纹，
          用于判断依赖集合是否发生变化。
        - 状态迁移：epoch 从 INACTIVE 变为有效值时触发加载；
          从有效值变为 INACTIVE 时触发卸载。
        - 副作用管理：通过 DisposableList 注册清理函数，
          在卸载或释放时逆序执行。

    状态机：
      PENDING ──(依赖就绪)──▶ LOADING ──(成功)──▶ ACTIVE
         ▲                         │                   │
         │                    (异常)                   │(依赖丢失)
         │                         ▼                   ▼
         │                      FAILED            UNLOADING ──(完成)──▶ PENDING
         │                         │                                  │
         │                    (依赖恢复)                           (依赖恢复)
         │                         │                                  │
         └─────────────────────────┴──────────────────────────────────┘
      任意状态 ──(dispose)──▶ DISPOSED
    """

    def __init__(
        self,
        parent_ctx: Any,
        config: Any = None,
        inject: dict[str, Any] | None = None,
        uid: int | None = None,
        runtime: Any = None,
        callback: Callable[..., Any] | None = None,
    ) -> None:
        """初始化 Fiber。

        Args:
            parent_ctx: 父级上下文。
            config: 插件配置。
            inject: 依赖注入映射 {名称: 配置}。
            uid: 唯一标识，0 表示根 Fiber。
            runtime: 插件运行时对象。
            callback: 插件入口函数或类构造函数。
        """
        self.uid: int | None = uid or 0
        self.parent = parent_ctx
        self.ctx: Any = parent_ctx
        self.config = config
        self._raw_config = config          # 保留原始配置，用于热更新
        self.inject: dict[str, Any] = inject or {}
        self.runtime = runtime
        self.callback = callback
        self.state: int = FIBER_PENDING
        self._deps: dict[str, Any] = {}    # 已解析的依赖实现（用于 _check_impl/_refresh）
        self.store: dict[str, Any] = {}    # 激活快照（依赖 + 已提供实现）
        self._epoch: str = INACTIVE        # 当前依赖指纹，INACTIVE 表示依赖未就绪
        self._error: Exception | None = None
        self._disposables: DisposableList = DisposableList()
        self._inertia: asyncio.Task[Any] | None = None  # 当前正在执行的加载/卸载任务
        self._disposed = False
        self.plugin: Any = None            # 插件实例（执行 callback 后的返回值）

        # 根 Fiber 无需加载过程，直接设为 ACTIVE
        if uid == 0 and runtime is None:
            self.state = FIBER_ACTIVE
            self._epoch = ""

    @property
    def name(self) -> str:
        """返回 Fiber 名称，优先使用 runtime.name，否则根据 uid 生成。"""
        if self.runtime and hasattr(self.runtime, "name") and self.runtime.name:
            return self.runtime.name
        return "root" if self.uid == 0 else f"plugin#{self.uid}"

    @property
    def active(self) -> bool:
        """判断 Fiber 是否处于 ACTIVE 状态。"""
        return self.state == FIBER_ACTIVE

    @property
    def is_active(self) -> bool:
        """判断 Fiber 是否处于 ACTIVE 状态（与 active 同义）。"""
        return self.state == FIBER_ACTIVE

    def assert_active(self) -> None:
        """断言 Fiber 未释放，否则抛出 CordisError。"""
        if self.uid is None or self._disposed:
            raise CordisError(f"INACTIVE_EFFECT: fiber {self.name} is disposed")

    # ---- effect system ----

    def effect(self, disposer: Disposer) -> Disposer:
        """注册一个副作用清理函数。

        若 Fiber 已释放，则立即执行该清理函数。
        否则将其加入 DisposableList，在 Fiber 卸载或释放时自动调用。

        Args:
            disposer: 清理函数，可返回另一个可调用对象作为二次清理。

        Returns:
            传入的 disposer 本身，便于链式调用。
        """
        if self._disposed:
            # Fiber 已释放，立即执行清理，不注册
            try:
                result = disposer()
                if callable(result):
                    result()
            except Exception:
                pass
            return disposer
        self.assert_active()
        self._disposables.push(disposer)
        return disposer

    def get_effects(self) -> list[dict[str, Any]]:
        """返回所有已注册 effect 的诊断信息列表。"""
        return [{"label": str(d)} for d in self._disposables]

    # ---- lifecycle ----

    async def await_start(self) -> "Fiber":
        """等待 Fiber 完成当前加载/卸载任务。

        若加载过程中发生错误，则抛出该错误。

        Returns:
            当前 Fiber 实例（支持 await fiber 语法）。
        """
        if self._inertia is not None:
            await self._inertia
        if self._error:
            raise self._error
        return self

    def __await__(self) -> Any:
        """使 Fiber 可直接被 await（如 await fiber）。"""
        return self.await_start().__await__()

    async def restart(self) -> None:
        """重新启动 Fiber：先卸载再重新加载。"""
        if self._disposed:
            raise CordisError("INACTIVE_EFFECT: cannot restart disposed fiber")
        await self._unload()
        await self._reload()

    async def update(self, config: Any) -> None:
        """热更新插件配置。

        仅在 ACTIVE 状态下触发重新加载流程。

        Args:
            config: 新的配置数据。
        """
        self._raw_config = config
        self.config = config
        if self.state == FIBER_ACTIVE:
            await self._unload()
            self._check_all_deps()
            await self._reload()

    # ---- reactive dependency resolution ----

    def _check_impl(self, name: str) -> None:
        """检查指定名称的依赖是否可从父上下文获取并可用。

        若依赖不可用或可用性检查失败，则从 _deps 中移除该条目。

        Args:
            name: 依赖名称。
        """
        if self.parent is None:
            return
        reflect = getattr(self.parent, "reflect", None)
        if reflect is None:
            return
        impl = reflect._get_impl(self.ctx, name)
        if impl is None:
            self._deps.pop(name, None)
            return
        # 若实现定义了 check 函数，执行可用性检查
        if impl.check is not None and callable(impl.check):
            try:
                if not impl.check():
                    self._deps.pop(name, None)
                    return
            except Exception:
                self._deps.pop(name, None)
                return
        self._deps[name] = impl

    def _check_all_deps(self) -> None:
        """遍历 inject 中所有依赖名称，逐一执行可用性检查。"""
        for name in self.inject:
            self._check_impl(name)

    def _refresh(self) -> None:
        """重新计算 epoch 并触发状态迁移。

        根据当前所有 inject 依赖的实现 id 拼接成新的 epoch 字符串。
        若任一依赖缺失，epoch 设为 INACTIVE，触发卸载；
        若从 INACTIVE 恢复，则触发加载。
        """
        self._check_all_deps()
        parts = []
        for name in self.inject:
            impl = self._deps.get(name)
            if impl is None:
                self._set_epoch(INACTIVE)
                return
            parts.append(f":{id(impl)}")
        new_epoch = "".join(parts) if parts else ""
        self._set_epoch(new_epoch)

    def _set_epoch(self, epoch: str) -> None:
        """设置新的 epoch 值并驱动状态机迁移。

        Args:
            epoch: 新的依赖指纹字符串，INACTIVE 表示依赖未就绪。
        """
        if epoch == self._epoch:
            return
        old = self._epoch
        self._epoch = epoch

        # 从依赖未就绪变为就绪：开始加载
        if old == INACTIVE and epoch != INACTIVE:
            self.state = FIBER_LOADING
            self._schedule_load()
            self._emit_status(old)
        # 从就绪变为未就绪：开始卸载
        elif old != INACTIVE and epoch == INACTIVE:
            self.state = FIBER_UNLOADING
            self._schedule_unload()
            self._emit_status(old)

    def _schedule_load(self) -> None:
        """调度异步加载任务。"""
        self._inertia = asyncio.ensure_future(self._reload())

    def _schedule_unload(self) -> None:
        """调度异步卸载任务。"""
        self._inertia = asyncio.ensure_future(self._unload())

    async def _reload(self) -> None:
        """激活 Fiber：快照依赖、解析配置、执行插件回调。

        执行流程：
            1. 将当前依赖复制到 store。
            2. 解析并校验配置。
            3. 执行插件入口（函数或类构造函数）。
            4. 若返回生成器，消费其中的 effect。
            5. 若 epoch 仍有效，标记为 ACTIVE 并通知相关服务。
        """
        self.store = dict(self._deps)
        try:
            if self.callback is not None:
                self.config = _resolve_config(self.runtime, self._raw_config)
                if is_constructor(self.callback):
                    result = self._execute_constructor()
                else:
                    result = self._execute_function()
                if result is not None and asyncio.iscoroutine(result):
                    result = await result
                self.plugin = result
                if isinstance(result, (Generator, AsyncGenerator)):
                    await self._consume_effects(result)
            # 若加载过程中依赖未丢失，标记为激活状态
            if self._epoch != INACTIVE:
                self.state = FIBER_ACTIVE
                self._error = None
                self._emit_plugin()
                self._notify_provided()
        except Exception as e:
            self._error = e
            if self._epoch != INACTIVE:
                self.state = FIBER_FAILED
            _logger.warning("fiber %s failed to load: %s", self.name, e)

    def _notify_provided(self) -> None:
        """通知父级反射服务：本 Fiber 提供的所有实现已就绪。

        遍历父级 reflect.store，找到 fiber 指向当前实例的实现条目，
        触发其名称的变更通知，促使依赖该实现的子 Fiber 重新检查。
        """
        if self.parent is not None and hasattr(self.parent, "reflect"):
            reflect = self.parent.reflect
            for key in list(reflect.store.keys()):
                impl = reflect.store.get(key)
                if impl is not None and impl.fiber is self:
                    reflect.notify([impl.name])

    def _execute_function(self) -> Any:
        """执行函数类型的插件入口。"""
        return self.callback(self.ctx, self.config)

    def _execute_constructor(self) -> Any:
        """执行类构造函数类型的插件入口。

        实例化后依次执行：
            1. @Inject 注入的初始化钩子（INIT_HOOKS）。
            2. 实例的 symbols.init 方法（若存在）。
        """
        instance = self.callback(self.ctx, self.config)
        for hook in getattr(instance, INIT_HOOKS, []) or []:
            hook()
        init = getattr(instance, INIT, None)
        if callable(init):
            return init()
        return instance

    async def _unload(self) -> None:
        """卸载 Fiber：逆序执行所有副作用清理函数，重置内部状态。

        清理完成后 Fiber 回到 PENDING 状态，等待依赖再次就绪后重新加载。
        """
        for disposer in reversed(list(self._disposables)):
            try:
                result = disposer()
                if asyncio.iscoroutine(result):
                    await result
                elif callable(result):
                    result()
            except Exception:
                pass
        self._disposables.clear()
        self.store = {}
        self.state = FIBER_PENDING

    async def _consume_effects(self, gen: Any) -> None:
        """消费生成器（同步或异步）产出的所有 effect 并注册到 Fiber。

        插件入口返回生成器时，生成器中 yield 的值会被当作副作用清理函数注册。
        """
        try:
            if isinstance(gen, AsyncGenerator):
                async for item in gen:
                    self.effect(item)
            else:
                for item in gen:
                    self.effect(item)
        except StopIteration:
            pass
        except StopAsyncIteration:
            pass

    def _emit_status(self, old_state: int) -> None:
        """触发 internal/status 事件，通知监听者 Fiber 状态发生变化。

        Args:
            old_state: 变化前的状态值。
        """
        if self.parent is not None and hasattr(self.parent, "events"):
            self.parent.events.emit("internal/status", self, old_state)
        if self.runtime is not None and hasattr(self.runtime, "ctx") and hasattr(self.runtime.ctx, "events"):
            self.runtime.ctx.events.emit("internal/status", self, old_state)

    def _emit_plugin(self) -> None:
        """触发 internal/plugin 事件，通知监听者插件已加载或已卸载。"""
        if self.parent is not None and hasattr(self.parent, "events"):
            self.parent.events.emit("internal/plugin", self)

    # ---- dispose ----

    async def dispose(self) -> None:
        """释放 Fiber：标记为 DISPOSED，取消进行中任务，执行所有清理函数。

        释放后的 Fiber 不能再被重新激活。
        """
        if self._disposed:
            return
        self._disposed = True
        self.state = FIBER_DISPOSED
        self.uid = None
        # 取消正在进行的加载/卸载任务
        if self._inertia is not None and not self._inertia.done():
            self._inertia.cancel()
            self._inertia = None
        # 从 runtime.fibers 列表中移除本 Fiber
        if self.runtime is not None and hasattr(self.runtime, "fibers"):
            try:
                self.runtime.fibers.remove(self)
            except (ValueError, KeyError):
                pass
        # 逆序执行所有副作用清理函数
        for disposer in reversed(list(self._disposables)):
            try:
                result = disposer()
                if asyncio.iscoroutine(result):
                    await result
                elif callable(result):
                    result()
            except Exception:
                pass
        self._disposables.clear()
        self.store.clear()
        self._deps.clear()
        self._emit_plugin()
