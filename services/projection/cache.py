from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Generic, TypeVar

T = TypeVar("T")


@dataclass
class _CacheEntry(Generic[T]):
    value: T
    cached_at: datetime


class ProjectionCache:
    """Thread-safe TTL cache for expensive M9 projection bundles."""

    def __init__(self, ttl_seconds: int = 300, max_size: int = 100) -> None:
        if max_size <= 0:
            raise ValueError(f"max_size must be positive, got {max_size}")
        if ttl_seconds <= 0:
            raise ValueError(f"ttl_seconds must be positive, got {ttl_seconds}")
        self._ttl_seconds = ttl_seconds
        self._max_size = max_size
        self._lock = threading.RLock()
        self._entries: dict[str, _CacheEntry[Any]] = {}

    def _expired(self, cached_at: datetime, now: datetime) -> bool:
        return (now - cached_at).total_seconds() > self._ttl_seconds

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            now = datetime.now(timezone.utc)
            if self._expired(entry.cached_at, now):
                del self._entries[key]
                return None
            return entry.value

    def put(self, key: str, value: Any) -> str:
        with self._lock:
            now = datetime.now(timezone.utc)
            expired_keys = [k for k, v in self._entries.items() if self._expired(v.cached_at, now)]
            for k in expired_keys:
                del self._entries[k]
            
            self._entries[key] = _CacheEntry(value=value, cached_at=now)
            
            while len(self._entries) > self._max_size:
                oldest_key = next(iter(self._entries))
                del self._entries[oldest_key]
        return key

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._entries)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            now = datetime.now(timezone.utc)
            active = sum(1 for entry in self._entries.values() if not self._expired(entry.cached_at, now))
            return {
                "ttl_seconds": self._ttl_seconds,
                "entries": len(self._entries),
                "active_entries": active,
            }
