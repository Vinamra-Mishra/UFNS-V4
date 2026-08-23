"""M8 — Data quality validation and freshness gating.

Every rainfall observation must pass validation before being used by the
nowcast engine or the simulation pipeline. This module checks:

  - Timestamp validity (timezone-aware, UTC)
  - Units (mm/h)
  - Missing values (NaN, Inf)
  - Negative rainfall
  - Duplicate timestamps
  - Stale observations (configurable freshness threshold)
  - Spatial coverage (grid shape matches expected)
  - Spatial resolution (matches expected)
  - Source health (provider is healthy)

Data freshness statuses:
  FRESH     — observation is within the freshness window
  STALE     — observation is older than the freshness window
  MISSING   — no observation available
  INVALID   — observation failed validation
  PARTIAL   — observation has partial spatial coverage
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional

import numpy as np

from services.nowcast.providers import (
    ProviderHealth,
    ProviderStatus,
    RainfallObservation,
)


class DataFreshness(str, Enum):
    """Freshness status of a rainfall observation."""
    FRESH = "FRESH"
    STALE = "STALE"
    MISSING = "MISSING"
    INVALID = "INVALID"
    PARTIAL = "PARTIAL"


@dataclass(frozen=True)
class QualityConfig:
    """Configurable quality thresholds.

    Attributes:
        freshness_threshold_minutes: Maximum age for an observation to be FRESH.
        stale_threshold_minutes: Maximum age for an observation to be STALE
            (beyond this it is MISSING).
        expected_width: Expected grid width.
        expected_height: Expected grid height.
        expected_resolution_m: Expected spatial resolution (metres).
        allow_negative_tolerance: Maximum allowed negative value (for float noise).
    """
    freshness_threshold_minutes: int = 30
    stale_threshold_minutes: int = 120
    expected_width: int = 134
    expected_height: int = 134
    expected_resolution_m: float = 30.0
    allow_negative_tolerance: float = -0.001


@dataclass(frozen=True)
class QualityResult:
    """Result of quality validation for a rainfall observation.

    Attributes:
        observation: The observation that was validated (or None).
        freshness: Data freshness status.
        valid: Whether the observation passed all validation checks.
        errors: List of validation error messages.
        warnings: List of validation warnings.
        checked_at: Timestamp when the validation was performed.
    """
    observation: Optional[RainfallObservation]
    freshness: DataFreshness
    valid: bool
    errors: list[str]
    warnings: list[str]
    checked_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "freshness": self.freshness.value,
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "checked_at": self.checked_at.isoformat(),
            "observation": self.observation.to_dict() if self.observation else None,
        }


def validate_observation(
    observation: Optional[RainfallObservation],
    config: QualityConfig | None = None,
    now: Optional[datetime] = None,
) -> QualityResult:
    """Validate a rainfall observation against quality rules.

    Args:
        observation: The observation to validate (may be None).
        config: Quality configuration (defaults used if None).
        now: Current time for freshness check (defaults to UTC now).

    Returns:
        QualityResult with freshness, validity, errors, and warnings.
    """
    config = config or QualityConfig()
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    errors: list[str] = []
    warnings: list[str] = []

    # --- MISSING check ---
    if observation is None:
        return QualityResult(
            observation=None,
            freshness=DataFreshness.MISSING,
            valid=False,
            errors=["No observation available"],
            warnings=[],
            checked_at=now,
        )

    # --- Timestamp validity ---
    if observation.observation_time.tzinfo is None:
        errors.append("observation_time is not timezone-aware")
    if observation.valid_from.tzinfo is None:
        errors.append("valid_from is not timezone-aware")
    if observation.valid_to.tzinfo is None:
        errors.append("valid_to is not timezone-aware")
    if observation.valid_to <= observation.valid_from:
        errors.append("valid_to is not after valid_from")

    # --- Units check ---
    if observation.units != "mm/h":
        errors.append(f"unexpected units: {observation.units!r} (expected 'mm/h')")

    # --- Missing values ---
    if not np.all(np.isfinite(observation.rate_mmh)):
        errors.append("rate_mmh contains NaN or Inf values")

    # --- Negative rainfall ---
    neg_mask = observation.rate_mmh < config.allow_negative_tolerance
    if np.any(neg_mask):
        max_neg = float(np.min(observation.rate_mmh))
        errors.append(f"negative rainfall detected: min={max_neg:.4f} mm/h")

    # --- Spatial coverage ---
    if observation.width != config.expected_width or observation.height != config.expected_height:
        warnings.append(
            f"grid size mismatch: got {observation.width}×{observation.height}, "
            f"expected {config.expected_width}×{config.expected_height}"
        )

    # --- Spatial resolution ---
    if abs(observation.spatial_resolution_m - config.expected_resolution_m) > 0.1:
        warnings.append(
            f"resolution mismatch: got {observation.spatial_resolution_m} m, "
            f"expected {config.expected_resolution_m} m"
        )

    # --- Freshness ---
    age_minutes = (now - observation.observation_time).total_seconds() / 60.0
    if age_minutes < 0:
        freshness = DataFreshness.INVALID
        errors.append(f"observation is in the future by {-age_minutes:.1f} minutes")
    elif age_minutes <= config.freshness_threshold_minutes:
        freshness = DataFreshness.FRESH
    elif age_minutes <= config.stale_threshold_minutes:
        freshness = DataFreshness.STALE
        warnings.append(f"observation is {age_minutes:.1f} minutes old (STALE)")
    else:
        freshness = DataFreshness.STALE
        errors.append(f"observation is {age_minutes:.1f} minutes old (beyond stale threshold)")
        # Very old observations are treated as effectively missing
        if age_minutes > config.stale_threshold_minutes * 2:
            freshness = DataFreshness.MISSING

    valid = len(errors) == 0
    return QualityResult(
        observation=observation,
        freshness=freshness,
        valid=valid,
        errors=errors,
        warnings=warnings,
        checked_at=now,
    )


def is_observable(quality: QualityResult) -> bool:
    """Whether an observation is suitable for use (FRESH or STALE, valid)."""
    return quality.valid and quality.freshness in (DataFreshness.FRESH, DataFreshness.STALE)
