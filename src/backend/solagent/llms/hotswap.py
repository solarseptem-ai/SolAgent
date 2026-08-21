"""LLM 提供商配置热切换模块。

轮询监控提供商配置文件的变化，当文件发生修改时自动触发回调，
实现运行时无需重启服务即可更新提供商配置的能力。
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

_logger = logging.getLogger(__name__)


class ProviderWatcher:
    """提供商配置变更监听器，支持热切换。

    通过轮询检测配置文件的修改时间变化，一旦变更即触发用户注册的回调函数，
    从而实现在不重启服务的情况下更新提供商参数。

    属性:
        _registry: 提供商注册表。
        _poll_interval: 轮询间隔（秒）。
        _watchers: 被监听的配置项字典，键为提供商名称，值为 (路径, 修改时间, 回调函数) 元组。
        _running: 标记轮询循环是否正在运行。
    """

    def __init__(self, registry, poll_interval: float = 5.0):
        self._registry = registry
        self._poll_interval = poll_interval
        self._watchers: dict[str, tuple[Path, float, Callable]] = {}
        self._running = False

    def watch_config(self, provider_name: str, config_path: Path, on_change: Callable) -> None:
        """注册对某个配置文件的监听，变更时调用 on_change(provider_name)。"""
        self._watchers[provider_name] = (config_path, self._get_mtime(config_path), on_change)

    def _get_mtime(self, path: Path) -> float:
        """获取文件的最后修改时间，文件不存在或读取失败时返回 0.0。"""
        try:
            return path.stat().st_mtime if path.exists() else 0.0
        except OSError:
            return 0.0

    async def start(self) -> None:
        """启动轮询循环，持续检测已注册配置文件的变更。"""
        self._running = True
        import asyncio
        while self._running:
            for name, (path, old_mtime, on_change) in list(self._watchers.items()):
                new_mtime = self._get_mtime(path)
                if new_mtime > old_mtime:
                    # 文件已更新，刷新记录的修改时间并触发回调
                    self._watchers[name] = (path, new_mtime, on_change)
                    try:
                        on_change(name)
                    except Exception:
                        _logger.warning("LLM hotswap provider '%s' on_change callback failed", name, exc_info=True)
            await asyncio.sleep(self._poll_interval)

    def stop(self) -> None:
        """停止轮询循环。"""
        self._running = False

    def snapshot(self) -> dict[str, str]:
        """对当前所有注册提供商及其支持的模型列表进行快照，用于后续变更比对。"""
        snapshot = {}
        for profile in self._registry.list_profiles():
            snapshot[profile.name] = ",".join(profile.models)
        return snapshot

    def has_changed(self, old_snapshot: dict[str, str]) -> bool:
        """对比当前快照与旧快照，判断提供商配置是否发生变化。"""
        new_snapshot = self.snapshot()
        return new_snapshot != old_snapshot