"""M8 — Fixture rainfall provider (static precomputed observations).

Reads rainfall observations from precomputed fixture data (e.g., the existing
M5 rainfall GeoTIFFs or a JSON-defined scenario). Every observation carries
source_type=FIXTURE and explicit provenance.

The fixture provider is for:
  - Regression testing (deterministic, reproducible)
  - Demonstration replay (historical scenario playback)
  - Development (no external dependencies)

It must NEVER be presented as real data or live observations.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import numpy as np

from services.nowcast.providers import (
    ProviderHealth,
    ProviderStatus,
    RainfallObservation,
    RainfallProvider,
    SourceType,
)
from services.rainfall.fields import render_interval


class FixtureRainfallProvider(RainfallProvider):
    """Provides rainfall observations from a precomputed scenario fixture.

    Generates observations at regular intervals from a rainfall profile
    (derived from the M5 scenario engine). Each observation is deterministic
    and reproducible.

    Configuration:
        profile_intensities_mmh: List of rainfall intensities (mm/h) per interval.
        interval_minutes: Duration of each interval.
        start_time: Start time of the fixture scenario.
        pattern: Spatial pattern ("uniform" or "convective_cell").
        grid_shape: (height, width) of the output grid.
        seed: Random seed for deterministic spatial patterns.
    """

    def __init__(
        self,
        *,
        provider_id: str = "fixture-v1",
        profile_intensities_mmh: list[float],
        interval_minutes: int = 15,
        start_time: Optional[datetime] = None,
        pattern: str = "convective_cell",
        grid_shape: tuple[int, int] = (134, 134),
        seed: int = 20260822,
        spatial_reference: str = "EPSG:32645",
        spatial_resolution_m: float = 30.0,
        scenario_label: str = "FIXTURE_SCENARIO",
    ) -> None:
        if not profile_intensities_mmh:
            raise ValueError("profile_intensities_mmh must not be empty")
        if interval_minutes <= 0:
            raise ValueError("interval_minutes must be > 0")
        self._provider_id = provider_id
        self._intensities = tuple(profile_intensities_mmh)
        self._interval_minutes = interval_minutes
        self._start_time = start_time or datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
        self._pattern = pattern
        self._grid_shape = grid_shape
        self._seed = seed
        self._spatial_reference = spatial_reference
        self._spatial_resolution_m = spatial_resolution_m
        self._scenario_label = scenario_label
        self._last_observation: Optional[RainfallObservation] = None

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def source_type(self) -> SourceType:
        return SourceType.FIXTURE

    @property
    def source_name(self) -> str:
        return f"UFNS Fixture Provider ({self._scenario_label})"

    @property
    def spatial_reference(self) -> str:
        return self._spatial_reference

    @property
    def spatial_resolution_m(self) -> float:
        return self._spatial_resolution_m

    def _observation_for_interval(self, interval_idx: int) -> RainfallObservation:
        """Generate a fixture observation for a given interval index.

        The intensity index is clamped to the defined fixture range. The
        observation timestamp is derived from the SAME clamped index so that a
        request beyond the fixture duration never produces a future timestamp
        carrying the final fixture rainfall value.
        """
        idx = max(0, min(interval_idx, len(self._intensities) - 1))
        rate = self._intensities[idx]
        rate_field = render_interval(
            self._grid_shape,
            self._pattern,
            rate,
            idx,
            self._seed + idx,
        )
        obs_time = self._start_time + timedelta(minutes=idx * self._interval_minutes)
        valid_from = obs_time
        valid_to = obs_time + timedelta(minutes=self._interval_minutes)

        obs = RainfallObservation(
            observation_time=obs_time,
            valid_from=valid_from,
            valid_to=valid_to,
            rate_mmh=rate_field.astype(np.float32),
            source_type=SourceType.FIXTURE,
            source_name=self.source_name,
            source_provider_id=self._provider_id,
            spatial_reference=self._spatial_reference,
            spatial_resolution_m=self._spatial_resolution_m,
            width=self._grid_shape[1],
            height=self._grid_shape[0],
            quality_flags=("FIXTURE", "PRECOMPUTED", "NOT_REAL_DATA"),
            metadata={
                "interval_index": idx,
                "nominal_rate_mmh": rate,
                "scenario_label": self._scenario_label,
                "profile_length": len(self._intensities),
                "total_depth_mm": sum(self._intensities) * self._interval_minutes / 60.0,
            },
        )
        self._last_observation = obs
        return obs

    def fetch_latest(self) -> Optional[RainfallObservation]:
        """Return the last interval of the fixture (end-of-scenario observation)."""
        return self._observation_for_interval(len(self._intensities) - 1)

    def fetch_observation(self, observation_time: datetime) -> Optional[RainfallObservation]:
        """Return the fixture observation closest to the given time."""
        if observation_time.tzinfo is None:
            observation_time = observation_time.replace(tzinfo=timezone.utc)
        delta = (observation_time - self._start_time).total_seconds()
        if delta < 0:
            return self._observation_for_interval(0)
        idx = int(delta // (self._interval_minutes * 60))
        return self._observation_for_interval(idx)

    def fetch_sequence(self, start_idx: int = 0, end_idx: Optional[int] = None) -> list[RainfallObservation]:
        """Return a sequence of fixture observations."""
        if end_idx is None:
            end_idx = len(self._intensities)
        return [self._observation_for_interval(i) for i in range(start_idx, end_idx)]

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            provider_id=self._provider_id,
            status=ProviderStatus.HEALTHY,
            source_type=SourceType.FIXTURE,
            last_observation_time=(
                self._last_observation.observation_time
                if self._last_observation else None
            ),
            message="Fixture provider operating (precomputed data, NOT real)",
            metadata={
                "scenario_label": self._scenario_label,
                "profile_length": len(self._intensities),
                "interval_minutes": self._interval_minutes,
            },
        )

    def metadata(self) -> dict[str, Any]:
        return {
            "provider_id": self._provider_id,
            "source_type": self.source_type.value,
            "source_name": self.source_name,
            "capabilities": ["scenario_replay", "deterministic_sequence"],
            "limitations": [
                "Precomputed fixture — NOT real data",
                "Limited to the defined scenario duration",
                "No temporal evolution beyond the fixture",
            ],
            "configuration": {
                "profile_intensities_mmh": list(self._intensities),
                "interval_minutes": self._interval_minutes,
                "start_time": self._start_time.isoformat(),
                "pattern": self._pattern,
                "grid_shape": list(self._grid_shape),
                "seed": self._seed,
                "scenario_label": self._scenario_label,
            },
        }
