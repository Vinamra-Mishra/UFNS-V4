"""M8 — Synthetic rainfall provider (deterministic, clearly labelled).

Generates rainfall observations from a mathematical model. Every observation
carries source_type=SYNTHETIC. This provider is for testing, demonstration,
and development ONLY — it is never presented as real data.

The synthetic provider must:
  - Always identify itself as SYNTHETIC.
  - Never be silently substituted for missing real data.
  - Produce deterministic output for a given seed and time.
  - Carry full provenance in every observation.
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


class SyntheticRainfallProvider(RainfallProvider):
    """Generates deterministic synthetic rainfall fields.

    Uses the existing M2 rainfall field renderer (services/rainfall/fields.py)
    to produce spatially-structured synthetic observations.

    Configuration:
        base_rate_mmh: Base rainfall rate for the synthetic field.
        pattern: Spatial pattern ("uniform" or "convective_cell").
        grid_shape: (height, width) of the output grid.
        seed: Random seed for deterministic generation.
        temporal_resolution_minutes: Interval between observations.
    """

    def __init__(
        self,
        *,
        provider_id: str = "synthetic-v1",
        base_rate_mmh: float = 15.0,
        pattern: str = "convective_cell",
        grid_shape: tuple[int, int] = (134, 134),
        seed: int = 20260822,
        temporal_resolution_minutes: int = 15,
        spatial_reference: str = "EPSG:32645",
        spatial_resolution_m: float = 30.0,
    ) -> None:
        if temporal_resolution_minutes <= 0:
            raise ValueError("temporal_resolution_minutes must be > 0")
        self._provider_id = provider_id
        self._base_rate_mmh = base_rate_mmh
        self._pattern = pattern
        self._grid_shape = grid_shape
        self._seed = seed
        self._temporal_resolution_minutes = temporal_resolution_minutes
        self._spatial_reference = spatial_reference
        self._spatial_resolution_m = spatial_resolution_m
        self._last_observation: Optional[RainfallObservation] = None

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def source_type(self) -> SourceType:
        return SourceType.SYNTHETIC

    @property
    def source_name(self) -> str:
        return (
            f"UFNS Synthetic Rainfall Generator "
            f"({self._base_rate_mmh} mm/h, {self._pattern})"
        )

    @property
    def spatial_reference(self) -> str:
        return self._spatial_reference

    @property
    def spatial_resolution_m(self) -> float:
        return self._spatial_resolution_m

    def _generate_observation(self, obs_time: datetime) -> RainfallObservation:
        """Generate a synthetic observation for the given time."""
        if obs_time.tzinfo is None:
            obs_time = obs_time.replace(tzinfo=timezone.utc)

        interval_s = self._temporal_resolution_minutes * 60
        # Derive a deterministic interval index from the observation time
        epoch = datetime(2026, 1, 1, tzinfo=timezone.utc)
        delta_s = (obs_time - epoch).total_seconds()
        interval_idx = max(0, int(delta_s // interval_s))

        rate_field = render_interval(
            self._grid_shape,
            self._pattern,
            self._base_rate_mmh,
            interval_idx,
            self._seed + interval_idx,
        )

        valid_from = obs_time
        valid_to = obs_time + timedelta(minutes=self._temporal_resolution_minutes)

        obs = RainfallObservation(
            observation_time=obs_time,
            valid_from=valid_from,
            valid_to=valid_to,
            rate_mmh=rate_field.astype(np.float32),
            source_type=SourceType.SYNTHETIC,
            source_name=self.source_name,
            source_provider_id=self._provider_id,
            spatial_reference=self._spatial_reference,
            spatial_resolution_m=self._spatial_resolution_m,
            width=self._grid_shape[1],
            height=self._grid_shape[0],
            quality_flags=("SYNTHETIC", "NOT_REAL_DATA"),
            metadata={
                "base_rate_mmh": self._base_rate_mmh,
                "pattern": self._pattern,
                "seed": self._seed,
                "interval_index": interval_idx,
            },
        )
        self._last_observation = obs
        return obs

    def fetch_latest(self) -> Optional[RainfallObservation]:
        """Generate a synthetic observation at the current UTC time."""
        return self._generate_observation(datetime.now(timezone.utc))

    def fetch_observation(self, observation_time: datetime) -> Optional[RainfallObservation]:
        """Generate a synthetic observation at the specified time."""
        return self._generate_observation(observation_time)

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            provider_id=self._provider_id,
            status=ProviderStatus.HEALTHY,
            source_type=SourceType.SYNTHETIC,
            last_observation_time=(
                self._last_observation.observation_time
                if self._last_observation else None
            ),
            message="Synthetic provider operating (NOT real data)",
            metadata={
                "base_rate_mmh": self._base_rate_mmh,
                "pattern": self._pattern,
                "grid_shape": list(self._grid_shape),
            },
        )

    def metadata(self) -> dict[str, Any]:
        return {
            "provider_id": self._provider_id,
            "source_type": self.source_type.value,
            "source_name": self.source_name,
            "capabilities": ["single_field_generation", "deterministic_replay"],
            "limitations": [
                "NOT real data — mathematical model only",
                "No temporal correlation between observations",
                "No storm evolution or dissipation",
            ],
            "configuration": {
                "base_rate_mmh": self._base_rate_mmh,
                "pattern": self._pattern,
                "grid_shape": list(self._grid_shape),
                "seed": self._seed,
                "temporal_resolution_minutes": self._temporal_resolution_minutes,
                "spatial_reference": self._spatial_reference,
                "spatial_resolution_m": self._spatial_resolution_m,
            },
        }
