"""Rainfall spatial fields (ARCHITECTURE §7.2, MODEL_ASSUMPTIONS §2).

A rainfall field is the mean rain rate over [valid_from, valid_to) — never an
instantaneous sample. External units mm/h; solver units m/s. Conversions are
exact and unit-tested. Missing rain is never silently replaced with zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np

MMH_TO_MS = 1.0 / (1000.0 * 3600.0)  # exact
MS_TO_MMH = 1000.0 * 3600.0


def mmh_to_ms(rate_mmh: float | np.ndarray) -> float | np.ndarray:
    return rate_mmh * MMH_TO_MS


def ms_to_mmh(rate_ms: float | np.ndarray) -> float | np.ndarray:
    return rate_ms * MS_TO_MMH


def rainfall_volume_m3(rate_mmh: np.ndarray, cell_area_m2: float, dt_s: float) -> float:
    """Rainfall volume from a mm/h field over one interval (exact ledger term)."""
    return float(np.sum(mmh_to_ms(rate_mmh.astype(np.float64))) * cell_area_m2 * dt_s)


@dataclass(frozen=True)
class FieldInterval:
    """One forcing interval of a spatial rainfall field."""

    index: int
    valid_from: datetime
    valid_to: datetime
    lead_minutes: int
    rate_mmh: np.ndarray  # shape (height, width)

    def __post_init__(self) -> None:
        if self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be after valid_from")
        if np.any(self.rate_mmh < 0):
            raise ValueError("negative rainfall rates are not allowed")
        if not np.all(np.isfinite(self.rate_mmh)):
            raise ValueError("rainfall rates must be finite")

    @property
    def mean_rate_mmh(self) -> float:
        return float(np.mean(self.rate_mmh))


def uniform_field(shape: tuple[int, int], rate_mmh: float) -> np.ndarray:
    return np.full(shape, rate_mmh, dtype=np.float32)


def convective_cell_field(
    shape: tuple[int, int],
    base_rate_mmh: float,
    cell_amplitude_mmh: float,
    cx: float = 0.55,
    cy: float = 0.45,
    sigma: float = 0.12,
    seed: int = 0,
) -> np.ndarray:
    """Base field + Gaussian convective cell + seeded small-scale texture.

    The cell centre/amplitude drift across intervals is controlled by the
    caller (cell advection); this function renders one interval's pattern.
    """
    rng = np.random.default_rng(seed)
    n_y, n_x = shape
    x = np.linspace(0.0, 1.0, n_x)
    y = np.linspace(0.0, 1.0, n_y)
    xx, yy = np.meshgrid(x, y, indexing="xy")
    cell = cell_amplitude_mmh * np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * sigma**2)))
    texture = 0.15 * base_rate_mmh * rng.standard_normal(shape)
    field = np.full(shape, base_rate_mmh, dtype=np.float64) + cell + texture
    return np.clip(field, 0.0, None).astype(np.float32)


def render_interval(
    shape: tuple[int, int],
    pattern: str,
    rate_mmh: float,
    index: int,
    seed: int,
    cell_speed: float = 0.05,
) -> np.ndarray:
    """Render one interval's spatial pattern.

    - uniform: constant rate everywhere.
    - convective_cell: base rate + a cell that advects eastward per interval
      (deterministic; seeds derive from the scenario seed + interval index).
    """
    if pattern == "uniform":
        return uniform_field(shape, rate_mmh)
    if pattern == "convective_cell":
        cx = 0.25 + cell_speed * index
        cy = 0.45 + 0.03 * np.sin(index * 0.9)
        return convective_cell_field(
            shape, rate_mmh * 0.6, rate_mmh * 2.5, cx=cx, cy=cy, sigma=0.1, seed=seed + index
        )
    raise ValueError(f"unknown spatial pattern: {pattern}")
