"""M8 — Forecast verification metrics framework.

Defines the verification metrics appropriate for rainfall nowcasting and
provides computation functions for when paired (forecast, observation) data
becomes available.

IMPORTANT: Verification metrics MUST NOT be computed or reported until real
paired data exists. The default status is NOT_EVALUATED.

Metrics implemented:
  - MAE (Mean Absolute Error) — continuous
  - RMSE (Root Mean Square Error) — continuous
  - Bias — continuous
  - Correlation (Pearson) — continuous
  - CSI (Critical Success Index) — categorical
  - POD (Probability of Detection) — categorical
  - FAR (False Alarm Ratio) — categorical

References:
  - Germann & Zawadzki (2002, 2004) — scale-dependent predictability
  - Roberts & Lean (2008) — FSS for gridded rainfall
  - WMO (2017) — verification standards
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np


class VerificationStatus:
    """Status of forecast verification."""
    NOT_EVALUATED = "NOT_EVALUATED"
    EVALUATED = "EVALUATED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True)
class VerificationResult:
    """Result of forecast verification for a single metric or metric set.

    Attributes:
        status: NOT_EVALUATED / EVALUATED / INSUFFICIENT_DATA.
        metrics: Dictionary of metric name -> value.
        n_samples: Number of paired samples used.
        method: Verification method description.
        notes: Additional notes.
    """
    status: str = VerificationStatus.NOT_EVALUATED
    metrics: dict[str, float] = field(default_factory=dict)
    n_samples: int = 0
    method: str = "pairwise_comparison"
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "metrics": self.metrics,
            "n_samples": self.n_samples,
            "method": self.method,
            "notes": self.notes,
        }


def compute_mae(forecast: np.ndarray, observed: np.ndarray) -> float:
    """Mean Absolute Error (mm/h)."""
    return float(np.mean(np.abs(forecast - observed)))


def compute_rmse(forecast: np.ndarray, observed: np.ndarray) -> float:
    """Root Mean Square Error (mm/h)."""
    return float(np.sqrt(np.mean((forecast - observed) ** 2)))


def compute_bias(forecast: np.ndarray, observed: np.ndarray) -> float:
    """Bias (mean forecast − mean observed). Positive = overforecast."""
    return float(np.mean(forecast) - np.mean(observed))


def compute_correlation(forecast: np.ndarray, observed: np.ndarray) -> float:
    """Pearson correlation coefficient between forecast and observed fields."""
    f_flat = forecast.ravel()
    o_flat = observed.ravel()
    if np.std(f_flat) < 1e-12 or np.std(o_flat) < 1e-12:
        return 0.0  # constant field has zero correlation
    return float(np.corrcoef(f_flat, o_flat)[0, 1])


def compute_csi(
    forecast: np.ndarray,
    observed: np.ndarray,
    threshold: float = 0.1,
) -> float:
    """Critical Success Index (CSI) for a rain/no-rain threshold (mm/h).

    CSI = hits / (hits + misses + false_alarms)
    """
    f_rain = forecast >= threshold
    o_rain = observed >= threshold
    hits = np.sum(f_rain & o_rain)
    misses = np.sum(~f_rain & o_rain)
    false_alarms = np.sum(f_rain & ~o_rain)
    denom = hits + misses + false_alarms
    return float(hits / denom) if denom > 0 else 0.0


def compute_pod(
    forecast: np.ndarray,
    observed: np.ndarray,
    threshold: float = 0.1,
) -> float:
    """Probability of Detection (POD) for a rain/no-rain threshold (mm/h).

    POD = hits / (hits + misses)
    """
    f_rain = forecast >= threshold
    o_rain = observed >= threshold
    hits = np.sum(f_rain & o_rain)
    misses = np.sum(~f_rain & o_rain)
    denom = hits + misses
    return float(hits / denom) if denom > 0 else 0.0


def compute_far(
    forecast: np.ndarray,
    observed: np.ndarray,
    threshold: float = 0.1,
) -> float:
    """False Alarm Ratio (FAR) for a rain/no-rain threshold (mm/h).

    FAR = false_alarms / (hits + false_alarms)
    """
    f_rain = forecast >= threshold
    o_rain = observed >= threshold
    hits = np.sum(f_rain & o_rain)
    false_alarms = np.sum(f_rain & ~o_rain)
    denom = hits + false_alarms
    return float(false_alarms / denom) if denom > 0 else 0.0


def verify_pair(
    forecast: np.ndarray,
    observed: np.ndarray,
    rain_threshold_mmh: float = 0.1,
) -> VerificationResult:
    """Compute all verification metrics for one (forecast, observed) pair.

    Args:
        forecast: Forecast rainfall field (mm/h).
        observed: Observed rainfall field (mm/h).
        rain_threshold_mmh: Threshold for categorical metrics.

    Returns:
        VerificationResult with all metrics.
    """
    if forecast.shape != observed.shape:
        return VerificationResult(
            status=VerificationStatus.INSUFFICIENT_DATA,
            notes=f"shape mismatch: forecast {forecast.shape} vs observed {observed.shape}",
        )

    metrics = {
        "mae_mmh": compute_mae(forecast, observed),
        "rmse_mmh": compute_rmse(forecast, observed),
        "bias_mmh": compute_bias(forecast, observed),
        "correlation": compute_correlation(forecast, observed),
        "csi": compute_csi(forecast, observed, rain_threshold_mmh),
        "pod": compute_pod(forecast, observed, rain_threshold_mmh),
        "far": compute_far(forecast, observed, rain_threshold_mmh),
    }
    return VerificationResult(
        status=VerificationStatus.EVALUATED,
        metrics=metrics,
        n_samples=1,
        method="pairwise_comparison",
        notes=f"rain_threshold={rain_threshold_mmh} mm/h",
    )


def no_evaluation_available(reason: str = "") -> VerificationResult:
    """Return a NOT_EVALUATED result (the default until real data exists)."""
    return VerificationResult(
        status=VerificationStatus.NOT_EVALUATED,
        metrics={},
        n_samples=0,
        method="none",
        notes=reason or (
            "No paired (forecast, observation) data available. "
            "Verification requires real-time observations. "
            "Status is NOT_EVALUATED — no skill scores are fabricated."
        ),
    )
