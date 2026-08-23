"""M8 — Nowcast caching layer.

Caches rainfall observations and nowcast records to avoid redundant computation.
Cache keys include the rainfall fingerprint, method, and relevant parameters.

Thread-safety: cache operations are guarded by a single re-entrant lock so that
concurrent API callers cannot observe torn state, race expiry/deletion/insertion,
or iterate while another thread mutates the cache. All expiry checks and
deletions happen inside the protected section.

Immutability/snapshots: the cache never exposes caller-owned mutable state.
On ``put`` the caller's observation/record is deep-copied; on ``get`` an
independent snapshot is returned. Callers may mutate the object they passed in
or the object they received without affecting the cached value.

Never returns stale results as current without explicitly labelling them.
"""

from __future__ import annotations

import copy
import threading
from datetime import datetime, timezone
from typing import Any, Optional

from services.nowcast.nowcast_record import NowcastRecord
from services.nowcast.providers import RainfallObservation


class NowcastCache:
    """Thread-safe in-memory cache for observations and nowcast records.

    Cache key = provider_id + observation identity/fingerprint + method + leads.
    Entries expire after a configurable TTL.
    """

    def __init__(self, ttl_seconds: int = 300) -> None:
        self._ttl_seconds = ttl_seconds
        self._lock = threading.RLock()
        self._observation_cache: dict[str, tuple[RainfallObservation, datetime]] = {}
        self._nowcast_cache: dict[str, tuple[list[NowcastRecord], datetime]] = {}

    # ------------------------------------------------------------------
    # Key derivation (public so the API can build keys for cache-first lookups)
    # ------------------------------------------------------------------

    def _obs_key(self, obs: RainfallObservation) -> str:
        return f"{obs.source_provider_id}:{obs.observation_time.isoformat()}:{obs.fingerprint()}"

    def _nowcast_key(self, obs: RainfallObservation, method: str, leads: tuple[int, ...]) -> str:
        return (
            f"{obs.source_provider_id}:{obs.observation_time.isoformat()}:"
            f"{obs.fingerprint()}:{method}:{leads}"
        )

    def observation_key(self, obs: RainfallObservation) -> str:
        """Return the cache key for an observation."""
        return self._obs_key(obs)

    def nowcast_key(self, obs: RainfallObservation, method: str, leads: tuple[int, ...]) -> str:
        """Return the cache key for a nowcast set."""
        return self._nowcast_key(obs, method, leads)

    # ------------------------------------------------------------------
    # Snapshot helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _copy_observation(obs: RainfallObservation) -> RainfallObservation:
        """Return an independent deep copy of an observation."""
        if obs is None:
            return obs
        return copy.deepcopy(obs)

    @staticmethod
    def _copy_nowcast(records: list[NowcastRecord]) -> list[NowcastRecord]:
        """Return an independent deep copy of a list of nowcast records."""
        if records is None:
            return records
        return copy.deepcopy(records)

    def _is_expired(self, cached_at: datetime, now: datetime) -> bool:
        age = (now - cached_at).total_seconds()
        return age > self._ttl_seconds

    # ------------------------------------------------------------------
    # Observation cache
    # ------------------------------------------------------------------

    def get_observation(self, key: str) -> Optional[RainfallObservation]:
        """Retrieve a cached observation as an independent snapshot."""
        with self._lock:
            entry = self._observation_cache.get(key)
            if entry is None:
                return None
            obs, cached_at = entry
            if self._is_expired(cached_at, datetime.now(timezone.utc)):
                del self._observation_cache[key]
                return None
            return self._copy_observation(obs)

    def put_observation(self, obs: RainfallObservation) -> str:
        """Deep-copy and cache an observation, returning its key."""
        key = self._obs_key(obs)
        with self._lock:
            self._observation_cache[key] = (self._copy_observation(obs), datetime.now(timezone.utc))
        return key

    # ------------------------------------------------------------------
    # Nowcast cache
    # ------------------------------------------------------------------

    def get_nowcast(
        self, obs: RainfallObservation, method: str, leads: tuple[int, ...]
    ) -> Optional[list[NowcastRecord]]:
        """Retrieve cached nowcast records as independent snapshots."""
        with self._lock:
            key = self._nowcast_key(obs, method, leads)
            entry = self._nowcast_cache.get(key)
            if entry is None:
                return None
            records, cached_at = entry
            if self._is_expired(cached_at, datetime.now(timezone.utc)):
                del self._nowcast_cache[key]
                return None
            return self._copy_nowcast(records)

    def put_nowcast(
        self,
        obs: RainfallObservation,
        method: str,
        leads: tuple[int, ...],
        records: list[NowcastRecord],
    ) -> str:
        """Deep-copy and cache nowcast records, returning the key."""
        key = self._nowcast_key(obs, method, leads)
        with self._lock:
            self._nowcast_cache[key] = (self._copy_nowcast(records), datetime.now(timezone.utc))
        return key

    # ------------------------------------------------------------------
    # Lifecycle / introspection
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Clear all cached entries."""
        with self._lock:
            self._observation_cache.clear()
            self._nowcast_cache.clear()

    @property
    def size(self) -> int:
        """Total number of cached entries (including expired-but-not-yet-pruned)."""
        with self._lock:
            return len(self._observation_cache) + len(self._nowcast_cache)

    def stats(self) -> dict[str, Any]:
        """Cache statistics (active entries exclude expired-but-present entries)."""
        with self._lock:
            now = datetime.now(timezone.utc)
            active_obs = sum(
                1 for _, (_, t) in self._observation_cache.items()
                if not self._is_expired(t, now)
            )
            active_nc = sum(
                1 for _, (_, t) in self._nowcast_cache.items()
                if not self._is_expired(t, now)
            )
            return {
                "ttl_seconds": self._ttl_seconds,
                "observation_entries": len(self._observation_cache),
                "observation_active": active_obs,
                "nowcast_entries": len(self._nowcast_cache),
                "nowcast_active": active_nc,
                "total_entries": len(self._observation_cache) + len(self._nowcast_cache),
            }
