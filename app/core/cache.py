"""轻量缓存与幂等：接口与 Redis 对齐，便于后续替换。"""
from __future__ import annotations

import threading
import time
from typing import Any


class TTLCache:
    def __init__(self, ttl_seconds: float = 300.0, max_items: int = 2000) -> None:
        self._ttl = ttl_seconds
        self._max = max_items
        self._data: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            item = self._data.get(key)
            if not item:
                return None
            expire_at, value = item
            if expire_at < time.time():
                self._data.pop(key, None)
                return None
            return value

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        with self._lock:
            if len(self._data) >= self._max:
                # 简易 LRU：淘汰最早过期的一条
                oldest = min(self._data.items(), key=lambda kv: kv[1][0])[0]
                self._data.pop(oldest, None)
            self._data[key] = (time.time() + (ttl or self._ttl), value)

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


class IdempotencyStore:
    """幂等：同一 key 只成功执行一次，重复返回首次结果。"""

    def __init__(self) -> None:
        self._done: dict[str, dict[str, Any]] = {}
        self._inflight: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def _lock_for(self, key: str) -> threading.Lock:
        with self._guard:
            return self._inflight.setdefault(key, threading.Lock())

    def get(self, key: str) -> dict[str, Any] | None:
        return self._done.get(key)

    def run_once(self, key: str, fn) -> tuple[dict[str, Any], bool]:
        """返回 (结果, 是否首次执行)。"""
        with self._lock_for(key):
            if key in self._done:
                return self._done[key], False
            result = fn()
            self._done[key] = result
            return result, True

    def clear(self) -> None:
        with self._guard:
            self._done.clear()
            self._inflight.clear()


cache = TTLCache(ttl_seconds=300)
idempotency = IdempotencyStore()
