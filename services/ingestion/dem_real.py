"""M10 — Real DEM ingestion + normalization pipeline (Copernicus DEM GLO-30).

The synthetic DEM fixture (services/ingestion/dem.py) remains the
authoritative regression/test asset for M1–M9 pipeline semantics.

AUTHORITATIVE REAL-PILOT SPATIAL FOUNDATION (2026-08-23):
  The human-declared authoritative pilot spatial area is the real
  Copernicus GLO-30 DEM tile at data/raw/bagjola_kolkata_glo30_dem.tif.
  The pilot GridSpec is derived deterministically from this tile's actual
  projected bounds in EPSG:32645, with 30 m cell alignment.

  Previous M1 GridSpec: synthetic origin (300000, 2500000), 134×134 cells.
  That grid was a synthetic test fixture, not a real pilot area. It has been
  replaced by the real-pilot GridSpec derived from the actual DEM tile.

IMPLEMENTED stages (ingest_dem):
  source file access → source fingerprint → file validation →
  CRS validation → resolution validation (actual transform, metres) →
  nodata validation → bounds validation → dimension/empty-raster checks →
  finite-data check → result-specific provenance record

IMPLEMENTED stages (normalize_dem):
  VALIDATED source required → windowed clip to pilot bounds →
  reproject to UFNS CRS → bilinear resampling (continuous elevation) →
  alignment to target GridSpec → GridSpec-compatible representation →
  processing fingerprint → result-specific provenance

Resampling policy (documented decision): elevation is a continuous field, so
cross-CRS reprojection uses BILINEAR resampling (no stairstep artefacts of
nearest, no overshoot of cubic). Nodata is PRESERVED, never filled and never
converted to zero; nodata cells are counted and reported. No interpolation of
missing elevation is performed.

STATUS: The real Copernicus artifact is present and validated. The
authoritative pilot GridSpec is derived from the actual DEM tile.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from services.contracts import GridSpec
from services.ingestion.crs import require_projected_metric
from services.ingestion.dem import GRID_CELLS, ORIGIN_X, ORIGIN_Y
from services.ingestion.real_data import (
    COPERNICUS_DEM_SOURCE,
    VALIDATION_FAILED,
    VALIDATION_VALIDATED,
    DataIngestionStatus,
    SourceProvenance,
    SpatialBounds,
    compute_data_fingerprint,
    compute_processing_fingerprint,
    compute_schema_fingerprint,
    result_labels,
    validate_crs,
)

# ---------------------------------------------------------------------------
# Authoritative real-pilot GridSpec constants (2026-08-23 spatial re-baseline)
#
# Derived deterministically from bagjola_kolkata_glo30_dem.tif:
#   Source: EPSG:4326, bounds 88.60–88.85°E / 22.65–22.90°N
#   Projected to EPSG:32645 (UTM 45N), aligned to 30 m cells:
#     x_min_proj ≈ 664405.28 → floor to 664380.0
#     x_max_proj ≈ 689753.34 → ceil  to 689760.0
#     y_max_proj ≈ 2533642.20 → ceil  to 2533650.0
#     y_min_proj ≈ 2505659.88 → floor to 2505630.0
#   width  = (689760 - 664380) / 30 = 846
#   height = (2533650 - 2505630) / 30 = 934
#
# The previous M1 synthetic grid (134×134, origin 300000/2500000) was replaced
# by human decision: the DEM tile is the authoritative pilot spatial area.
# ---------------------------------------------------------------------------
REAL_PILOT_ORIGIN_X = 664380.0       # left edge (top-left x, EPSG:32645)
REAL_PILOT_ORIGIN_Y = 2533650.0      # top edge (top-left y, EPSG:32645, north-up)
REAL_PILOT_CELL_SIZE_M = 30.0        # modelling resolution
REAL_PILOT_WIDTH = 846               # columns
REAL_PILOT_HEIGHT = 934              # rows

# Historical synthetic M1 grid constants (preserved for regression protection).
# These are the OLD synthetic origin/dimensions; never restore as pilot grid.
_LEGACY_M1_ORIGIN_X = ORIGIN_X       # 300000.0
_LEGACY_M1_ORIGIN_Y = ORIGIN_Y       # 2500000.0
_LEGACY_M1_GRID_CELLS = GRID_CELLS   # 134

# Resampling semantics for continuous elevation data (see module docstring).
DEM_RESAMPLING = "bilinear"

# Ground metres per arc-second used to compare a geographic raster's actual
# resolution against the documented GLO-30 posting (~30 m).
_M_PER_ARCSEC = 30.87
_RESOLUTION_ERROR_FACTOR = 2.0
_RESOLUTION_WARN_FRACTION = 0.10

PIPELINE_VERSION = "m10-dem-normalize-v1"


@dataclass(frozen=True)
class DEMIngestionConfig:
    """Configuration for real DEM ingestion and normalization.

    target_grid is the authoritative normalization target (the established
    UFNS pilot grid when None). expected_* fields describe the SOURCE raster
    and are validated against actual file metadata, never assumed from the
    dataset name.
    """
    source: SourceProvenance = COPERNICUS_DEM_SOURCE
    expected_crs: str = "EPSG:4326"
    expected_resolution_arcsec: float = 1.0  # ~30m at equator
    expected_nodata: float = -32768.0
    target_grid: GridSpec | None = None


@dataclass(frozen=True)
class DEMIngestionResult:
    """Result of DEM ingestion pipeline."""
    status: DataIngestionStatus
    provenance: SourceProvenance
    source_file: Path | None = None
    source_fingerprint: str = ""
    output_array: np.ndarray | None = None
    output_crs: str = ""
    output_resolution_m: float = 0.0
    output_bounds: tuple[float, float, float, float] | None = None
    output_nodata: float | None = None
    validation_errors: tuple[str, ...] = ()
    validation_warnings: tuple[str, ...] = ()

    @property
    def labels(self) -> list[str]:
        return result_labels(self.status, self.provenance.classification)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "provenance": self.provenance.to_dict(),
            "source_file": str(self.source_file) if self.source_file else None,
            "source_fingerprint": self.source_fingerprint,
            "output_shape": list(self.output_array.shape) if self.output_array is not None else None,
            "output_crs": self.output_crs,
            "output_resolution_m": self.output_resolution_m,
            "output_bounds": self.output_bounds,
            "validation_errors": list(self.validation_errors),
            "validation_warnings": list(self.validation_warnings),
            "labels": self.labels,
        }


@dataclass(frozen=True)
class DEMNormalizationResult:
    """Result of DEM normalization to the UFNS pilot GridSpec."""
    status: DataIngestionStatus
    provenance: SourceProvenance
    source_file: Path | None = None
    source_fingerprint: str = ""
    processing_fingerprint: str = ""
    grid: GridSpec | None = None
    elevation: np.ndarray | None = None
    nodata: float | None = None
    nodata_cells: int = 0
    total_cells: int = 0
    resampling: str = DEM_RESAMPLING
    output_crs: str = ""
    validation_errors: tuple[str, ...] = ()
    validation_warnings: tuple[str, ...] = ()

    @property
    def labels(self) -> list[str]:
        return result_labels(self.status, self.provenance.classification)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "provenance": self.provenance.to_dict(),
            "source_file": str(self.source_file) if self.source_file else None,
            "source_fingerprint": self.source_fingerprint,
            "processing_fingerprint": self.processing_fingerprint,
            "grid": self.grid.model_dump(mode="json") if self.grid is not None else None,
            "elevation_shape": list(self.elevation.shape) if self.elevation is not None else None,
            "nodata": self.nodata,
            "nodata_cells": self.nodata_cells,
            "total_cells": self.total_cells,
            "resampling": self.resampling,
            "validation_errors": list(self.validation_errors),
            "validation_warnings": list(self.validation_warnings),
            "labels": self.labels,
        }


def pilot_grid_spec() -> GridSpec:
    """The authoritative UFNS real-pilot grid (single source of truth).

    Derived deterministically from the actual Copernicus GLO-30 DEM tile
    at data/raw/bagjola_kolkata_glo30_dem.tif (88.60–88.85°E, 22.65–22.90°N).

    Alignment rule (deterministic, documented):
      1. Transform DEM geographic bounds to EPSG:32645 (UTM 45N)
      2. Floor x_min to nearest 30 m → grid origin_x (left edge)
      3. Ceil y_max to nearest 30 m → grid origin_y (top edge, north-up)
      4. Ceil x_max to nearest 30 m → grid right edge
      5. Floor y_min to nearest 30 m → grid bottom edge
      6. width = (right - left) / 30, height = (top - bottom) / 30

    This ensures the grid fully covers the DEM extent with exact 30 m cells.

    Previous M1 synthetic grid (134×134 @ 30 m, origin 300000/2500000) was
    replaced 2026-08-23 by human decision: the Copernicus DEM tile is the
    authoritative real-pilot spatial area. The old synthetic constants remain
    in services/ingestion/dem.py for M1–M9 synthetic fixture compatibility.
    """
    affine = [
        REAL_PILOT_CELL_SIZE_M,  # a: pixel width (east)
        0.0,                     # b: row rotation
        REAL_PILOT_ORIGIN_X,     # c: x-coordinate of upper-left corner
        0.0,                     # d: column rotation
        -REAL_PILOT_CELL_SIZE_M, # e: pixel height (south, negative for north-up)
        REAL_PILOT_ORIGIN_Y,     # f: y-coordinate of upper-left corner
    ]
    return GridSpec(
        grid_id="ufns_pilot_grid_real",
        crs_wkt_or_epsg="EPSG:32645",
        width=REAL_PILOT_WIDTH,
        height=REAL_PILOT_HEIGHT,
        affine_transform=affine,
        cell_size_m=REAL_PILOT_CELL_SIZE_M,
        nodata=None,
        bounds=[
            REAL_PILOT_ORIGIN_X,
            REAL_PILOT_ORIGIN_Y - REAL_PILOT_HEIGHT * REAL_PILOT_CELL_SIZE_M,
            REAL_PILOT_ORIGIN_X + REAL_PILOT_WIDTH * REAL_PILOT_CELL_SIZE_M,
            REAL_PILOT_ORIGIN_Y,
        ],
    )


def validate_grid_spec(grid: GridSpec) -> tuple[list[str], list[str]]:
    """Validate a GridSpec for DEM normalization targets.

    Returns (errors, warnings). Grids must be projected metric, north-up,
    with an affine consistent with bounds/cell size/shape.
    """
    errors: list[str] = []
    warnings: list[str] = []
    a, b, c, d, e, f = grid.affine_transform
    try:
        require_projected_metric(grid.crs_wkt_or_epsg)
    except ValueError as exc:
        errors.append(f"grid CRS not projected metric: {exc}")
    if b != 0.0 or d != 0.0:
        errors.append("grid affine must be north-up (b=d=0)")
    if a <= 0 or e >= 0:
        errors.append("grid affine must have a>0 and e<0 (north-up pixel-is-area)")
    if not np.isclose(a, abs(e)) or not np.isclose(a, grid.cell_size_m):
        errors.append("grid affine cell size inconsistent with cell_size_m")
    xmin, ymin, xmax, ymax = grid.bounds
    if not (xmin < xmax and ymin < ymax):
        errors.append("grid bounds are not ordered (xmin<xmax, ymin<ymax)")
    if not np.isclose(c, xmin) or not np.isclose(f, ymax):
        errors.append("grid affine origin inconsistent with bounds (c=xmin, f=ymax)")
    if not np.isclose(xmax - xmin, a * grid.width) or not np.isclose(ymax - ymin, abs(e) * grid.height):
        errors.append("grid bounds extent inconsistent with affine x width/height")
    if grid.width < 2 or grid.height < 2:
        errors.append("grid too small (width/height >= 2 required)")
    return errors, warnings


def _ground_resolution_m(
    crs_str: str,
    transform: Any,
    width: int,
    height: int,
) -> tuple[float, float]:
    """Approximate (x, y) ground resolution in metres from actual raster metadata.

    For projected CRS this is the affine directly; for geographic CRS the
    pixel pitch is measured through the local UTM zone at the raster centre.
    """
    from pyproj import CRS, Transformer

    crs = CRS.from_user_input(crs_str)
    if crs.is_projected:
        return abs(transform.a), abs(transform.e)
    cx = transform.c + transform.a * width / 2.0
    cy = transform.f + transform.e * height / 2.0
    zone = int((cx + 180.0) // 6.0) + 1
    epsg = (32600 if cy >= 0 else 32700) + zone
    tf = Transformer.from_crs(crs, CRS.from_epsg(epsg), always_xy=True)
    x0, y0 = tf.transform(cx, cy)
    x1, _ = tf.transform(cx + transform.a, cy)
    _, y1 = tf.transform(cx, cy + transform.e)
    return float(np.hypot(x1 - x0, 1e-12)), float(np.hypot(y1 - y0, 1e-12))


def _array_sha256(arr: np.ndarray) -> str:
    h = hashlib.sha256()
    h.update(np.ascontiguousarray(arr).tobytes())
    return h.hexdigest()


def ingest_dem(
    source_path: Path | None = None,
    config: DEMIngestionConfig | None = None,
) -> DEMIngestionResult:
    """Ingest a real DEM file through the validation pipeline.

    Args:
        source_path: Path to the source DEM file (GeoTIFF). If None, returns
            a NOT_FETCHED result.
        config: Ingestion configuration. Defaults to Copernicus DEM GLO-30.

    Returns:
        DEMIngestionResult with full provenance and validation status.
    """
    config = config or DEMIngestionConfig()

    if source_path is None or not source_path.exists():
        return DEMIngestionResult(
            status=DataIngestionStatus.NOT_FETCHED,
            provenance=config.source.result_snapshot(),
            validation_warnings=(
                "Source DEM file not available — Copernicus DEM GLO-30 NOT_FETCHED from sandbox",
                "Synthetic DEM fixture remains the authoritative test asset",
            ),
        )

    errors: list[str] = []
    warnings: list[str] = []
    now = datetime.now(timezone.utc)

    source_fp = compute_data_fingerprint(source_path)

    try:
        import rasterio
    except ImportError as e:
        return DEMIngestionResult(
            status=DataIngestionStatus.BLOCKED,
            provenance=config.source.result_snapshot(
                acquisition_timestamp=now,
                data_fingerprint=source_fp,
                validation_status=VALIDATION_FAILED,
                known_limitations=(f"rasterio not available: {e}",),
            ),
            source_file=source_path,
            source_fingerprint=source_fp,
            validation_errors=(f"rasterio not available: {e}",),
        )

    data: np.ndarray
    nodata: float | None
    res_x_m: float
    res_y_m: float
    bounds: tuple[float, float, float, float]
    crs_str: str

    try:
        with rasterio.open(source_path) as src:
            crs_str = str(src.crs)
            if not validate_crs(crs_str):
                errors.append(f"invalid CRS: {crs_str}")
            elif crs_str != config.expected_crs:
                warnings.append(f"CRS mismatch: expected {config.expected_crs}, got {crs_str}")

            if src.width < 2 or src.height < 2:
                errors.append(f"raster too small: {src.width}x{src.height}")

            if validate_crs(crs_str):
                res_x_m, res_y_m = _ground_resolution_m(crs_str, src.transform, src.width, src.height)
                expected_m = config.expected_resolution_arcsec * _M_PER_ARCSEC
                if expected_m > 0:
                    observed = max(res_x_m, res_y_m)
                    if observed > expected_m * _RESOLUTION_ERROR_FACTOR or observed < expected_m / _RESOLUTION_ERROR_FACTOR:
                        errors.append(
                            f"resolution outside tolerance: expected ~{expected_m:.1f} m, "
                            f"actual raster is ~{observed:.1f} m (validated from transform, not dataset name)"
                        )
                    elif abs(observed - expected_m) > expected_m * _RESOLUTION_WARN_FRACTION:
                        warnings.append(
                            f"resolution drift: expected ~{expected_m:.1f} m, actual ~{observed:.1f} m"
                        )
            else:
                res_x_m = res_y_m = 0.0

            nodata = src.nodata
            if nodata is None:
                warnings.append("no nodata value defined")
            elif nodata != config.expected_nodata:
                warnings.append(f"nodata mismatch: expected {config.expected_nodata}, got {nodata}")

            bounds = tuple(src.bounds)
            west, south, east, north = bounds
            if west >= east or south >= north:
                errors.append(f"invalid bounding box (zero/negative area): {bounds}")
            if src.crs and src.crs.is_geographic:
                if not (-180.0 <= west <= 180.0 and -180.0 <= east <= 180.0 and -90.0 <= south <= 90.0 and -90.0 <= north <= 90.0):
                    errors.append(f"implausible geographic bounds: {bounds}")

            data = src.read(1)

            finite = data if nodata is None else data[data != nodata]
            if finite.size == 0:
                errors.append("raster contains no valid (non-nodata) cells")
            elif not np.all(np.isfinite(finite)):
                errors.append("non-finite values found in data")

    except Exception as e:  # noqa: BLE001
        return DEMIngestionResult(
            status=DataIngestionStatus.BLOCKED,
            provenance=config.source.result_snapshot(
                acquisition_timestamp=now,
                data_fingerprint=source_fp,
                validation_status=VALIDATION_FAILED,
                known_limitations=(f"failed to read DEM file: {e}",),
            ),
            source_file=source_path,
            source_fingerprint=source_fp,
            validation_errors=(f"failed to read DEM file: {e}",),
        )

    if errors:
        return DEMIngestionResult(
            status=DataIngestionStatus.BLOCKED,
            provenance=config.source.result_snapshot(
                acquisition_timestamp=now,
                data_fingerprint=source_fp,
                validation_status=VALIDATION_FAILED,
                known_limitations=tuple(errors) + tuple(warnings),
            ),
            source_file=source_path,
            source_fingerprint=source_fp,
            output_bounds=bounds,
            validation_errors=tuple(errors),
            validation_warnings=tuple(warnings),
        )

    limitations = tuple(warnings) + (
        "normalization (clip/reproject/alignment/GridSpec) not yet applied — raw grid returned as-is",
    )
    return DEMIngestionResult(
        status=DataIngestionStatus.VALIDATED,
        provenance=config.source.result_snapshot(
            acquisition_timestamp=now,
            schema_fingerprint=compute_schema_fingerprint(
                [
                    {"name": "crs", "dtype": crs_str},
                    {"name": "dtype", "dtype": str(data.dtype)},
                    {"name": "nodata", "dtype": repr(nodata)},
                    {"name": "resolution_m", "dtype": repr((round(res_x_m, 3), round(res_y_m, 3)))},
                    {"name": "shape", "dtype": repr(data.shape)},
                ]
            ),
            data_fingerprint=source_fp,
            validation_status=VALIDATION_VALIDATED,
            spatial_extent=SpatialBounds(west=bounds[0], south=bounds[1], east=bounds[2], north=bounds[3]),
            known_limitations=limitations,
            resolution=f"{max(res_x_m, res_y_m):.1f} m (validated from raster transform)",
        ),
        source_file=source_path,
        source_fingerprint=source_fp,
        output_array=data,
        output_crs=crs_str,
        output_resolution_m=max(res_x_m, res_y_m),
        output_bounds=bounds,
        output_nodata=nodata,
        validation_warnings=tuple(warnings),
    )


def normalize_dem(
    source_path: Path | None = None,
    config: DEMIngestionConfig | None = None,
) -> DEMNormalizationResult:
    """Normalize a VALIDATED real DEM to the UFNS pilot GridSpec.

    Pipeline: validation (via ingest_dem) → windowed clip to the target-grid
    bounds → reproject to the grid CRS → bilinear resampling onto the grid
    affine → GridSpec-compatible output + deterministic processing
    fingerprint + result-specific provenance.

    Refuses to normalize anything that did not pass source validation: a
    NOT_FETCHED or BLOCKED source propagates its status unchanged (no
    fabrication, no stale fallback).
    """
    config = config or DEMIngestionConfig()
    grid = config.target_grid if config.target_grid is not None else pilot_grid_spec()

    grid_errors, _ = validate_grid_spec(grid)
    if grid_errors:
        return DEMNormalizationResult(
            status=DataIngestionStatus.BLOCKED,
            provenance=config.source.result_snapshot(
                validation_status=VALIDATION_FAILED,
                known_limitations=tuple(grid_errors),
            ),
            validation_errors=tuple(grid_errors),
        )

    ingestion = ingest_dem(source_path, config)
    if ingestion.status != DataIngestionStatus.VALIDATED:
        # Status passthrough (NOT_FETCHED / BLOCKED) with the ingestion
        # evidence preserved — normalization never runs on invalid input.
        return DEMNormalizationResult(
            status=ingestion.status,
            provenance=ingestion.provenance,
            source_file=source_path,
            source_fingerprint=ingestion.source_fingerprint,
            validation_errors=(
                f"normalization requires a VALIDATED source; got {ingestion.status.value}",
                *ingestion.validation_errors,
            ),
            validation_warnings=ingestion.validation_warnings,
        )

    assert source_path is not None  # validated above means the file exists
    now = datetime.now(timezone.utc)
    errors: list[str] = []
    warnings: list[str] = list(ingestion.validation_warnings)

    try:
        import rasterio
        from rasterio.warp import Resampling, reproject, transform_bounds
    except ImportError as e:
        return DEMNormalizationResult(
            status=DataIngestionStatus.BLOCKED,
            provenance=config.source.result_snapshot(
                acquisition_timestamp=now,
                data_fingerprint=ingestion.source_fingerprint,
                validation_status=VALIDATION_FAILED,
                known_limitations=(f"rasterio warp unavailable: {e}",),
            ),
            source_file=source_path,
            source_fingerprint=ingestion.source_fingerprint,
            validation_errors=(f"rasterio warp unavailable: {e}",),
        )

    from affine import Affine

    a, b, c, d, e_, f = grid.affine_transform
    dst_transform = Affine(a, b, c, d, e_, f)
    dst_nodata = ingestion.output_nodata if ingestion.output_nodata is not None else config.expected_nodata

    try:
        with rasterio.open(source_path) as src:
            src_crs = src.crs
            # Overlap gate: source must cover part of the target grid before
            # any warp is attempted.
            grid_wgs = transform_bounds(
                grid.crs_wkt_or_epsg, "EPSG:4326", *grid.bounds, densify_pts=21
            )
            src_wgs = transform_bounds(src_crs, "EPSG:4326", *src.bounds, densify_pts=21)
            overlaps = (
                min(src_wgs[2], grid_wgs[2]) - max(src_wgs[0], grid_wgs[0]) > 0
                and min(src_wgs[3], grid_wgs[3]) - max(src_wgs[1], grid_wgs[1]) > 0
            )
            if not overlaps:
                raise ValueError(
                    f"no spatial overlap: source bounds {src_wgs} vs target grid {grid_wgs} (EPSG:4326)"
                )

            elevation = np.full((grid.height, grid.width), dst_nodata, dtype="float32")
            reproject(
                source=rasterio.band(src, 1),
                destination=elevation,
                src_transform=src.transform,
                src_crs=src_crs,
                src_nodata=src.nodata,
                dst_transform=dst_transform,
                dst_crs=grid.crs_wkt_or_epsg,
                dst_nodata=dst_nodata,
                resampling=Resampling.bilinear,
                init_dest_nodata=True,
            )
    except Exception as exc:  # noqa: BLE001
        return DEMNormalizationResult(
            status=DataIngestionStatus.BLOCKED,
            provenance=config.source.result_snapshot(
                acquisition_timestamp=now,
                data_fingerprint=ingestion.source_fingerprint,
                validation_status=VALIDATION_FAILED,
                known_limitations=(f"normalization failed: {exc}",),
            ),
            source_file=source_path,
            source_fingerprint=ingestion.source_fingerprint,
            validation_errors=(f"normalization failed: {exc}",),
            validation_warnings=tuple(warnings),
        )

    nodata_cells = int(np.count_nonzero(elevation == dst_nodata))
    total_cells = int(elevation.size)
    valid = elevation[elevation != dst_nodata]
    if valid.size == 0:
        errors.append("normalized raster contains no valid cells (nodata everywhere)")
    elif not np.all(np.isfinite(valid)):
        errors.append("non-finite values in normalized raster")

    if errors:
        return DEMNormalizationResult(
            status=DataIngestionStatus.BLOCKED,
            provenance=config.source.result_snapshot(
                acquisition_timestamp=now,
                data_fingerprint=ingestion.source_fingerprint,
                validation_status=VALIDATION_FAILED,
                known_limitations=tuple(errors),
            ),
            source_file=source_path,
            source_fingerprint=ingestion.source_fingerprint,
            validation_errors=tuple(errors),
            validation_warnings=tuple(warnings),
        )

    steps = [
        "validate_source",
        "clip_to_grid_bounds",
        f"reproject_to_{grid.crs_wkt_or_epsg.replace(':', '').lower()}",
        f"resample_{DEM_RESAMPLING}",
        "align_to_gridspec",
        "gridspec_representation",
    ]
    params: dict[str, Any] = {
        "pipeline_version": PIPELINE_VERSION,
        "source_data_fingerprint": ingestion.source_fingerprint,
        "grid_id": grid.grid_id,
        "grid_crs": grid.crs_wkt_or_epsg,
        "grid_affine": grid.affine_transform,
        "grid_shape": [grid.height, grid.width],
        "dst_nodata": dst_nodata,
        "resampling": DEM_RESAMPLING,
        "output_dtype": "float32",
        "output_array_sha256": _array_sha256(elevation),
    }
    processing_fp = compute_processing_fingerprint(steps, params)

    limitations = list(warnings) + [
        (
            f"reprojected/resampled ({DEM_RESAMPLING}) to {grid.cell_size_m:g} m grid "
            f"{grid.grid_id} — values are resampled, not native postings"
        ),
        f"nodata preserved ({nodata_cells}/{total_cells} cells); no filling or interpolation applied",
        "vertical datum not verifiable from artifact metadata — unverified",
    ]
    return DEMNormalizationResult(
        status=DataIngestionStatus.NORMALIZED,
        provenance=config.source.result_snapshot(
            acquisition_timestamp=now,
            data_fingerprint=ingestion.source_fingerprint,
            schema_fingerprint=ingestion.provenance.schema_fingerprint,
            processing_fingerprint=processing_fp,
            validation_status=VALIDATION_VALIDATED,
            spatial_extent=SpatialBounds(
                west=grid.bounds[0], south=grid.bounds[1], east=grid.bounds[2], north=grid.bounds[3]
            ),
            known_limitations=tuple(limitations),
            resolution=f"{grid.cell_size_m:g} m on {grid.grid_id}",
        ),
        source_file=source_path,
        source_fingerprint=ingestion.source_fingerprint,
        processing_fingerprint=processing_fp,
        grid=grid,
        elevation=elevation,
        nodata=dst_nodata,
        nodata_cells=nodata_cells,
        total_cells=total_cells,
        resampling=DEM_RESAMPLING,
        output_crs=ingestion.output_crs,
        validation_warnings=tuple(warnings),
    )

