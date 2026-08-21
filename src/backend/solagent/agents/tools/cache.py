"""Tool result cache. 对标 nanobot read dedup + grok-build web_fetch TTL cache。"""
import json
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from solagent.schema.tools import ToolResult


@dataclass
class CacheEntry:
    result: ToolResult
    cached_at: float
    ttl: float
    mtime: float | None = None


class ToolResultCache:
    def __init__(self, max_size: int = 500):
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._max_size = max_size

    def get(self, tool_id: str, params: dict) -> ToolResult | None:
        key = self._make_key(tool_id, params)
        entry = self._cache.get(key)
        if entry is None:
            return None
        if entry.ttl != -1 and time.monotonic() - entry.cached_at > entry.ttl:
            return None
        if entry.mtime is not None:
            current = self._get_mtime(params)
            if current is None or current != entry.mtime:
                return None
        return entry.result

    def set(self, tool_id: str, params: dict, result: ToolResult, ttl: float = -1):
        if len(self._cache) >= self._max_size:
            self._cache.popitem(last=False)
        key = self._make_key(tool_id, params)
        if key in self._cache:
            del self._cache[key]
        self._cache[key] = CacheEntry(
            result=result, cached_at=time.monotonic(), ttl=ttl,
            mtime=self._get_mtime(params) if tool_id in ("read", "glob", "ls") else None,
        )

    def invalidate(self, tool_id: str):
        to_remove = [k for k in self._cache if k.startswith(f"{tool_id}:")]
        for k in to_remove:
            del self._cache[k]

    def invalidate_all(self):
        to_remove = [k for k, v in self._cache.items() if v.mtime is not None]
        for k in to_remove:
            del self._cache[k]

    def clear(self):
        self._cache.clear()

    def _make_key(self, tool_id: str, params: dict) -> str:
        return f"{tool_id}:{json.dumps(params, sort_keys=True, default=str)}"

    def _get_mtime(self, params: dict) -> float | None:
        path = params.get("path", "")
        if not path:
            return None
        try:
            return Path(path).stat().st_mtime
        except OSError:
            return None