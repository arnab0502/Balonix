"""Disk-backed async TTL cache with single-flight and stale fallback.

Three properties matter on a 100-request/day plan:

* single-flight  - ten browser tabs asking at once cost one upstream call
* disk-backed    - restarting the server does not re-spend the daily quota
* stale fallback - when the budget is gone we serve yesterday's answer rather
                   than an error page
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any, Awaitable, Callable

from .config import CACHE_DIR

_DISK = CACHE_DIR / "entries"
_DISK.mkdir(parents=True, exist_ok=True)


def _path(key: str):
    return _DISK / (hashlib.sha256(key.encode()).hexdigest()[:24] + ".json")


class TTLCache:
    def __init__(self) -> None:
        self._mem: dict[str, tuple[float, Any]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self.hits = 0
        self.misses = 0
        self.stale_serves = 0
        self.upstream_calls = 0

    def _lock(self, key: str) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = self._locks[key] = asyncio.Lock()
        return lock

    # -- reads -------------------------------------------------------------
    def _read_disk(self, key: str) -> tuple[float, Any] | None:
        p = _path(key)
        try:
            raw = json.loads(p.read_text())
        except (OSError, ValueError):
            return None
        return raw.get("expires", 0), raw.get("value")

    def peek(self, key: str) -> Any | None:
        """Fresh value only, or None."""
        entry = self._mem.get(key) or self._read_disk(key)
        if not entry:
            return None
        expires, value = entry
        if expires < time.time():
            return None
        self._mem[key] = (expires, value)
        return value

    def peek_stale(self, key: str) -> Any | None:
        """Any value, however old. Used when the request budget is gone."""
        entry = self._mem.get(key) or self._read_disk(key)
        return entry[1] if entry else None

    def age(self, key: str, ttl: int) -> float | None:
        """Seconds since the entry was written, or None if absent."""
        entry = self._mem.get(key) or self._read_disk(key)
        if not entry:
            return None
        return max(0.0, time.time() - (entry[0] - ttl))

    # -- writes ------------------------------------------------------------
    def put(self, key: str, ttl: int, value: Any) -> None:
        expires = time.time() + ttl
        self._mem[key] = (expires, value)
        try:
            _path(key).write_text(json.dumps({"expires": expires, "value": value}))
        except (OSError, TypeError):
            pass

    async def get_or_set(
        self,
        key: str,
        ttl: int,
        producer: Callable[[], Awaitable[Any]],
        *,
        allow_stale: bool = True,
    ) -> Any:
        fresh = self.peek(key)
        if fresh is not None:
            self.hits += 1
            return fresh

        async with self._lock(key):
            fresh = self.peek(key)
            if fresh is not None:
                self.hits += 1
                return fresh
            self.misses += 1
            try:
                self.upstream_calls += 1
                value = await producer()
            except Exception:
                if allow_stale:
                    stale = self.peek_stale(key)
                    if stale is not None:
                        self.stale_serves += 1
                        return stale
                raise
            self.put(key, ttl, value)
            return value

    def invalidate(self, prefix: str = "") -> int:
        keys = [k for k in self._mem if k.startswith(prefix)]
        for k in keys:
            self._mem.pop(k, None)
            try:
                _path(k).unlink(missing_ok=True)
            except OSError:
                pass
        return len(keys)

    def stats(self) -> dict:
        total = self.hits + self.misses
        return {
            "memory_entries": len(self._mem),
            "disk_entries": len(list(_DISK.glob("*.json"))),
            "hits": self.hits,
            "misses": self.misses,
            "stale_serves": self.stale_serves,
            "upstream_calls": self.upstream_calls,
            "hit_rate": round(self.hits / total, 3) if total else 0.0,
        }


cache = TTLCache()
