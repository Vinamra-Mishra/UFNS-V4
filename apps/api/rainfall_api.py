"""M8 API layer — rainfall ingestion, nowcast, and provider management.

Provides versioned endpoints for:
  - Rainfall observations (latest, status, history)
  - Nowcast (latest, per-lead, status)
  - Provider management (list, health, metadata)

All endpoints:
  - Validate inputs
  - Expose provenance and source status
  - Reject invalid requests
  - Return structured errors
  - Never fabricate data or claim real-time when synthetic
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services.ingestion.dem import GRID_CELLS as DEFAULT_GRID_CELLS
from services.nowcast import NOWCAST_VERSION
from services.nowcast.cache import NowcastCache
from services.nowcast.engine import NowcastConfig, PersistenceNowcast
from services.nowcast.nowcast_record import NowcastRecord
from services.nowcast.providers import (
    RainfallObservation,
    RainfallProvider,
)
from services.nowcast.providers.fixture_provider import FixtureRainfallProvider
from services.nowcast.providers.synthetic_provider import SyntheticRainfallProvider
from services.nowcast.quality import (
    DataFreshness,
    QualityConfig,
    QualityResult,
    validate_observation,
)
from services.nowcast.verification import no_evaluation_available

# ---------------------------------------------------------------------------
# Global state (module-level singleton)
# ---------------------------------------------------------------------------

_default_providers: dict[str, RainfallProvider] = {}
_active_provider_id: str | None = None
_cache = NowcastCache(ttl_seconds=300)
_nowcast_config = NowcastConfig()
_quality_config = QualityConfig()
_engine = PersistenceNowcast(_nowcast_config)


def _init_default_providers() -> None:
    """Initialize default providers (synthetic + fixture)."""
    global _active_provider_id

    grid_shape = (DEFAULT_GRID_CELLS, DEFAULT_GRID_CELLS)

    # Synthetic provider
    synthetic = SyntheticRainfallProvider(
        provider_id="synthetic-v1",
        base_rate_mmh=15.0,
        pattern="convective_cell",
        grid_shape=grid_shape,
        seed=20260822,
    )
    _default_providers["synthetic-v1"] = synthetic

    # Fixture provider (based on the M5 S3 Extreme profile)
    from services.scenarios.profiles import build_profile_record
    extreme_profile = build_profile_record("P_EXTREME")
    fixture = FixtureRainfallProvider(
        provider_id="fixture-extreme-v1",
        profile_intensities_mmh=list(extreme_profile.intensities_mmh),
        interval_minutes=extreme_profile.temporal_resolution_minutes,
        pattern="convective_cell",
        grid_shape=grid_shape,
        seed=20260822,
        scenario_label="S3_EXTREME_FIXTURE",
    )
    _default_providers["fixture-extreme-v1"] = fixture

    # Default active provider is the synthetic one (NOT real data)
    _active_provider_id = "synthetic-v1"


# Initialize on import
_init_default_providers()


# ---------------------------------------------------------------------------
# Provider access
# ---------------------------------------------------------------------------

def get_active_provider() -> RainfallProvider:
    """Return the currently active rainfall provider."""
    if _active_provider_id is None or _active_provider_id not in _default_providers:
        raise RuntimeError("No active rainfall provider configured")
    return _default_providers[_active_provider_id]


def get_provider(provider_id: str) -> RainfallProvider | None:
    """Return a specific provider by ID."""
    return _default_providers.get(provider_id)


def list_providers() -> list[dict[str, Any]]:
    """List all registered providers with their health status."""
    result = []
    for pid, provider in _default_providers.items():
        h = provider.health()
        result.append({
            "provider_id": pid,
            "source_type": provider.source_type.value,
            "source_name": provider.source_name,
            "status": h.status.value,
            "active": pid == _active_provider_id,
            "metadata": provider.metadata(),
        })
    return result


def set_active_provider(provider_id: str) -> bool:
    """Set the active provider. Returns True if the provider exists."""
    global _active_provider_id
    if provider_id not in _default_providers:
        return False
    _active_provider_id = provider_id
    _cache.clear()  # clear cache when provider changes
    return True


# ---------------------------------------------------------------------------
# Observation access
# ---------------------------------------------------------------------------

def _missing_quality(message: str) -> QualityResult:
    return QualityResult(
        observation=None,
        freshness=DataFreshness.MISSING,
        valid=False,
        errors=[message],
        warnings=[],
        checked_at=datetime.now(timezone.utc),
    )


def get_nowcast_config() -> NowcastConfig:
    """Expose the active nowcast configuration for in-process services."""
    return _nowcast_config


def _latest_observation_typed() -> tuple[RainfallProvider, RainfallObservation | None, QualityResult]:
    """Typed latest-observation access with cache integration.

    This is the internal building block used by both the HTTP helpers and the
    M9 projection service. The established M8 behaviour is preserved: the
    observation is revalidated against ``now`` even when served from cache, and
    invalid observations are returned with a full QualityResult rather than
    being treated as AVAILABLE.
    """
    provider = get_active_provider()
    obs = provider.fetch_latest()
    if obs is None:
        return provider, None, _missing_quality("No observation available")
    cached = _cache.get_observation(_cache.observation_key(obs))
    if cached is not None:
        obs = cached
    quality = validate_observation(obs, _quality_config)
    if quality.valid:
        _cache.put_observation(obs)
    return provider, obs, quality


def fetch_latest_nowcast_records() -> tuple[
    RainfallProvider,
    RainfallObservation | None,
    QualityResult,
    list[NowcastRecord],
]:
    """Typed latest-nowcast access with M8 cache semantics preserved."""
    provider, obs, quality = _latest_observation_typed()
    if obs is None or not quality.valid:
        return provider, obs, quality, []
    leads = _nowcast_config.lead_times_minutes
    method = _nowcast_config.method
    cached = _cache.get_nowcast(obs, method, leads)
    if cached is not None:
        return provider, obs, quality, cached
    records = _engine.generate(obs, quality)
    if records:
        _cache.put_nowcast(obs, method, leads, records)
    return provider, obs, quality, records


def _observation_unavailable(provider: RainfallProvider, message: str) -> dict[str, Any]:
    """Build the established UNAVAILABLE observation response."""
    return {
        "status": "UNAVAILABLE",
        "source_type": provider.source_type.value,
        "provider_id": provider.provider_id,
        "observation": None,
        "quality": _missing_quality(message).to_dict(),
    }


def fetch_latest_observation() -> dict[str, Any]:
    """Fetch the latest observation from the active provider.

    Integrated with the nowcast cache: a valid observation is deep-copied and
    stored so subsequent requests for the same provider/observation can reuse a
    snapshot. An invalid observation is NEVER returned as AVAILABLE and is not
    cached as though it were valid.
    """
    provider, obs, quality = _latest_observation_typed()
    if obs is None:
        return _observation_unavailable(provider, "No observation available")
    return {
        "status": "AVAILABLE" if quality.valid else "UNAVAILABLE",
        "source_type": obs.source_type.value,
        "provider_id": provider.provider_id,
        "observation": obs.to_dict() if quality.valid else None,
        "quality": quality.to_dict(),
    }


def fetch_observation_at(observation_time: datetime) -> dict[str, Any]:
    """Fetch an observation at a specific time from the active provider.

    Integrated with the nowcast cache: the observation identity (provider +
    observation time + fingerprint) keys the cache. Invalid observations are
    returned as UNAVAILABLE (with the QualityResult) and are not cached as
    valid.
    """
    provider = get_active_provider()
    obs = provider.fetch_observation(observation_time)
    if obs is None:
        return _observation_unavailable(
            provider, "No observation available at requested time"
        )
    cached = _cache.get_observation(_cache.observation_key(obs))
    if cached is not None:
        obs = cached
    quality = validate_observation(obs, _quality_config)
    if quality.valid:
        _cache.put_observation(obs)
    return {
        "status": "AVAILABLE" if quality.valid else "UNAVAILABLE",
        "source_type": obs.source_type.value,
        "provider_id": provider.provider_id,
        "observation": obs.to_dict() if quality.valid else None,
        "quality": quality.to_dict(),
    }


def get_rainfall_status() -> dict[str, Any]:
    """Get the overall rainfall system status."""
    provider = get_active_provider()
    health = provider.health()
    obs = provider.fetch_latest()
    quality = validate_observation(obs, _quality_config) if obs else QualityResult(
        observation=None,
        freshness=DataFreshness.MISSING,
        valid=False,
        errors=["No observation available"],
        warnings=[],
        checked_at=datetime.now(timezone.utc),
    )
    return {
        "provider_id": provider.provider_id,
        "source_type": provider.source_type.value,
        "source_name": provider.source_name,
        "health": health.to_dict(),
        "quality": quality.to_dict(),
        "nowcast_version": NOWCAST_VERSION,
        "nowcast_method": _nowcast_config.method,
        "lead_times_minutes": list(_nowcast_config.lead_times_minutes),
        "max_lead_minutes": _nowcast_config.max_lead_minutes,
        "labels": ["SYNTHETIC", "DEMONSTRATION", "NOT_REAL_TIME"],
    }


# ---------------------------------------------------------------------------
# Nowcast access
# ---------------------------------------------------------------------------

def generate_nowcast(obs: RainfallObservation) -> list[dict[str, Any]]:
    """Generate nowcast records from an observation.

    Returns the serialised records; if the observation is invalid the engine
    produces no records (empty list). Callers must treat an empty result as
    UNAVAILABLE, not as a valid forecast.
    """
    quality = validate_observation(obs, _quality_config)
    records = _engine.generate(obs, quality)
    return [r.to_dict() for r in records]


def _nowcast_unavailable(
    provider: RainfallProvider, *, lead_minutes: int | None = None,
    quality: QualityResult | None = None,
) -> dict[str, Any]:
    """Build the established UNAVAILABLE nowcast response.

    The all-lead response carries an empty ``nowcast`` list; the per-lead
    response carries ``nowcast: None`` to match the original contract.
    """
    response: dict[str, Any] = {
        "status": "UNAVAILABLE",
        "source_type": provider.source_type.value,
        "provider_id": provider.provider_id,
        "method": _nowcast_config.method,
        "nowcast": [] if lead_minutes is None else None,
        "verification": no_evaluation_available().to_dict(),
        "labels": ["SYNTHETIC", "NO_DATA", "NOT_EVALUATED"],
    }
    if lead_minutes is not None:
        response["lead_minutes"] = lead_minutes
    if quality is not None:
        response["quality"] = quality.to_dict()
    return response


def fetch_latest_nowcast() -> dict[str, Any]:
    """Fetch the latest nowcast (all lead times) from the active provider.

    Integrated with the nowcast cache keyed by provider + observation
    fingerprint + method + lead configuration. Cached records are reused, but
    the underlying observation is always re-validated before serving so a stale
    or invalid observation is never presented as a valid forecast.
    """
    provider, obs, quality, records = fetch_latest_nowcast_records()
    if obs is None:
        return _nowcast_unavailable(provider)
    if not quality.valid:
        # Never present an invalid/failed forecast as AVAILABLE; include the
        # QualityResult and do not apply normal demonstration labels.
        return _nowcast_unavailable(provider, quality=quality)
    if not records:
        return _nowcast_unavailable(provider, quality=quality)

    return {
        "status": "AVAILABLE",
        "source_type": obs.source_type.value,
        "provider_id": provider.provider_id,
        "method": _nowcast_config.method,
        "initialization_time": obs.observation_time.isoformat(),
        "nowcast": [r.to_dict() for r in records],
        "quality": quality.to_dict(),
        "verification": no_evaluation_available(
            "No paired (forecast, observation) data for verification"
        ).to_dict(),
        "labels": ["SYNTHETIC", "DEMONSTRATION", "PERSISTENCE_BASELINE", "NOT_REAL_TIME"],
    }


def fetch_nowcast_at_lead(lead_minutes: int) -> dict[str, Any]:
    """Fetch the nowcast for a specific lead time."""
    if lead_minutes not in _nowcast_config.lead_times_minutes:
        return {
            "status": "INVALID_LEAD",
            "lead_minutes": lead_minutes,
            "valid_leads": list(_nowcast_config.lead_times_minutes),
            "nowcast": None,
        }
    provider = get_active_provider()
    obs = provider.fetch_latest()
    if obs is None:
        return _nowcast_unavailable(provider, lead_minutes=lead_minutes)
    quality = validate_observation(obs, _quality_config)
    if not quality.valid:
        return _nowcast_unavailable(provider, lead_minutes=lead_minutes, quality=quality)
    # Integrate the nowcast cache at the per-lead path as well. The cache is
    # keyed by provider + observation fingerprint + method + lead configuration.
    leads = _nowcast_config.lead_times_minutes
    method = _nowcast_config.method
    cached = _cache.get_nowcast(obs, method, leads)
    if cached is not None:
        record = next((r for r in cached if r.lead_minutes == lead_minutes), None)
        if record is not None:
            return {
                "status": "AVAILABLE",
                "lead_minutes": lead_minutes,
                "nowcast": record.to_dict(include_rates=True),
                "quality": quality.to_dict(),
                "labels": ["SYNTHETIC", "DEMONSTRATION", "PERSISTENCE_BASELINE"],
            }
    record = _engine.generate_for_lead(obs, lead_minutes, quality)
    if record is None:
        return _nowcast_unavailable(provider, lead_minutes=lead_minutes, quality=quality)
    # Store the full set so future per-lead requests hit the cache.
    _cache.put_nowcast(obs, method, leads, _engine.generate(obs, quality))
    return {
        "status": "AVAILABLE",
        "lead_minutes": lead_minutes,
        "nowcast": record.to_dict(include_rates=True),
        "quality": quality.to_dict(),
        "labels": ["SYNTHETIC", "DEMONSTRATION", "PERSISTENCE_BASELINE"],
    }


def get_nowcast_status() -> dict[str, Any]:
    """Get the overall nowcast system status."""
    provider = get_active_provider()
    health = provider.health()
    return {
        "nowcast_version": NOWCAST_VERSION,
        "method": _nowcast_config.method,
        "method_description": (
            "Persistence baseline: forecast(t+Δt) = latest_observed_field. "
            "No advection, no intensity evolution, no ML. "
            "Conservative short-horizon baseline only."
        ),
        "lead_times_minutes": list(_nowcast_config.lead_times_minutes),
        "max_lead_minutes": _nowcast_config.max_lead_minutes,
        "status": _nowcast_config.status,
        "uncertainty": _nowcast_config.uncertainty,
        "provider_id": provider.provider_id,
        "source_type": provider.source_type.value,
        "provider_health": health.to_dict(),
        "verification": no_evaluation_available().to_dict(),
        "labels": ["PERSISTENCE_BASELINE", "PROVISIONAL", "NOT_OPERATIONAL"],
    }


def get_cache_stats() -> dict[str, Any]:
    """Get cache statistics."""
    return _cache.stats()
