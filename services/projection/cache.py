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

    def __init__(self, ttl_seconds: int = 300) -> None:
        self._ttl_seconds = ttl_seconds
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
            self._entries[key] = _CacheEntry(value=value, cached_at=datetime.now(timezone.utc))
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
