"""Synthetic DEM fixture (M1) — SYNTHETIC, never presented as real terrain.

Design (documented, seeded, deterministic):
- 134 x 134 cells at 30 m -> 4020 m x 4020 m domain in EPSG:32645 (UTM 45N).
- Base plane sloping NW -> SE at 0.002 m/m (topographic gradient).
- A central street corridor (W->E) lowered 0.4 m to guide surface flow.
- A shallow depression basin (Gaussian, ~1.2 m deep) in the south-centre
  where pluvial water ponds — intentionally NOT filled (D-014).
- Regular raised "building blocks" (1.5 m) on a 150 m grid to mimic a DSM.
- Small sinusoidal micro-relief for realism; seeded RNG 20260821.

Vertical reference: SYNTHETIC_LOCAL_DATUM (B08: fixture surface and any future
fixture drainage share this datum by construction). No conditioning is applied;
a no-op conditioning report is written for traceability.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from affine import Affine

from services.ingestion.crs import WB_PROJECTED_CRS

GRID_CELLS = 134
CELL_SIZE_M = 30.0
DOMAIN_M = GRID_CELLS * CELL_SIZE_M  # 4020 m
SEED = 20260821
ORIGIN_X = 300000.0  # synthetic metric origin inside UTM 45N (arbitrary but fixed)
ORIGIN_Y = 2500000.0
VERTICAL_REFERENCE = "SYNTHETIC_LOCAL_DATUM"


def grid_affine(origin_x: float = ORIGIN_X, origin_y: float = ORIGIN_Y, size: float = CELL_SIZE_M) -> Affine:
    """Pixel-is-area convention: north-up, origin at top-left corner."""
    return Affine(size, 0.0, origin_x, 0.0, -size, origin_y + DOMAIN_M)


def synthetic_dem(
    seed: int = SEED,
    cells: int = GRID_CELLS,
    origin_x: float = ORIGIN_X,
    origin_y: float = ORIGIN_Y,
) -> np.ndarray:
    """Return the synthetic DSM (float32, m). Deterministic for a given seed."""
    rng = np.random.default_rng(seed)
    n = cells
    x = np.linspace(0.0, 1.0, n)
    y = np.linspace(0.0, 1.0, n)
    xx, yy = np.meshgrid(x, y, indexing="xy")

    # Base plane: high at NW (x=0,y=0), low at SE; gradient 0.002
    z = 20.0 + 0.002 * (DOMAIN_M) * (1.0 - (xx + yy) / 2.0)

    # Central street corridor (W -> E along the middle row band), lowered
    street = np.abs(yy - 0.5) < 0.012  # ~48 m band
    z = z - 0.4 * street

    # Secondary cross street (N -> S along middle column band)
    cross = np.abs(xx - 0.5) < 0.012
    z = z - 0.3 * cross

    # Depression basin (south-centre), intentionally unfilled
    bx, by, bdepth, bsigma = 0.55, 0.72, 1.2, 0.06
    basin = bdepth * np.exp(-(((xx - bx) ** 2 + (yy - by) ** 2) / (2 * bsigma**2)))
    z = z - basin

    # Building blocks on a regular grid (DSM-like raised cells)
    for gx in np.arange(0.15, 0.9, 0.25):
        for gy in np.arange(0.15, 0.9, 0.25):
            block = (np.abs(xx - gx) < 0.03) & (np.abs(yy - gy) < 0.03)
            z = z + 1.5 * block

    # Micro-relief noise (small, deterministic)
    z = z + 0.05 * rng.standard_normal((n, n))
    z = z - 0.05 * rng.standard_normal((n, n)) * (yy > 0.8)  # flatter far south

    return z.astype(np.float32)


def write_geotiff(z: np.ndarray, out_path: Path, origin_x: float = ORIGIN_X, origin_y: float = ORIGIN_Y) -> Path:
    import rasterio

    transform = grid_affine(origin_x, origin_y)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        out_path,
        "w",
        driver="GTiff",
        height=z.shape[0],
        width=z.shape[1],
        count=1,
        dtype="float32",
        crs=WB_PROJECTED_CRS,
        transform=transform,
        compress="deflate",
    ) as dst:
        dst.write(z, 1)
        dst.update_tags(
            ARENA_VERTICAL_REFERENCE=VERTICAL_REFERENCE,
            ARENA_PROVENANCE="SYNTHETIC",
            ARENA_SEED=str(SEED),
            ARENA_DESCRIPTION="UFNS synthetic DSM fixture; not real terrain",
        )
    return out_path


def conditioning_report(z_before: np.ndarray, z_after: np.ndarray, out_path: Path) -> Path:
    """No-op conditioning (fixture depressions are deliberate; D-014)."""
    changed = int(np.count_nonzero(~np.isclose(z_before, z_after, atol=1e-9)))
    vol_change = float(np.sum(z_after - z_before)) * CELL_SIZE_M * CELL_SIZE_M
    report = {
        "operation": "none",
        "reason": "synthetic fixture; depressions are intentional ponding features",
        "affected_cells": changed,
        "volume_change_m3": vol_change,
        "algorithms": [],
        "before_sha256": None,  # filled by provenance layer
        "after_sha256": None,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2))
    return out_path
