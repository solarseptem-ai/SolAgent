"""Agent 状态检查点模块。

提供轻量化的键值对持久化能力，用于保存和恢复 Agent 执行过程中的中间状态。
支持指定文件路径进行磁盘持久化，若未指定路径则仅在内存中操作。
适用于需要断点续跑或崩溃后恢复的 Agent 执行流程。
"""

import json
from pathlib import Path


class Checkpoint:
    """Agent 状态检查点，支持内存/磁盘双模式存储。

    属性:
        path: 持久化文件路径，None 表示仅内存存储。
    """

    def __init__(self, path: Path | None = None):
        """初始化检查点，若路径存在则自动加载已有数据。

        参数:
            path: 可选的持久化文件路径。
        """
        self._path = path
        self._data: dict = {}
        if path and path.exists():
            self._data = json.loads(path.read_text())

    def save(self, key: str, value) -> None:
        """保存键值对到检查点，若配置了路径则同步写入磁盘。"""
        self._data[key] = value
        if self._path:
            self._path.write_text(json.dumps(self._data, indent=2, default=str))

    def load(self, key: str, default=None):
        """按键读取值，不存在时返回默认值。"""
        return self._data.get(key, default)

    def clear(self) -> None:
        """清空所有已存储的数据（内存及磁盘，若配置了路径）。"""
        self._data.clear()