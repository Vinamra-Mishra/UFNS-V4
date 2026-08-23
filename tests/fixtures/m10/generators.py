"""M10 SYNTHETIC TEST FIXTURE generators (deterministic, offline).

Classification: DataSourceClassification.FIXTURE for every artifact produced
here. These fixtures exercise the real-data ingestion MACHINERY (validation,
normalization, audit, mapping, provenance). They are NOT real-world data and
prove nothing about the actual pilot datasets (NOT_FETCHED/BLOCKED).

Test coverage using these fixtures answers "does the pipeline work", never
"has the real pilot dataset been validated".
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from services.ingestion.crs import to_lonlat
from services.ingestion.real_data import DataSourceClassification, SourceProvenance

FIXTURE_CLASSIFICATION = DataSourceClassification.FIXTURE

# Provenance template for fixtures — classification FIXTURE so results can
# never be labelled REAL_DATA.
FIXTURE_DEM_SOURCE = SourceProvenance(
    source_name="UFNS SYNTHETIC TEST FIXTURE",
    dataset_name="m10-fixture-dem",
    version="fixture-v1",
    acquisition_timestamp=datetime(2026, 8, 22, tzinfo=timezone.utc),
    source_url="fixture://tests/fixtures/m10/generators.py",
    license_id="none-synthetic",
    classification=FIXTURE_CLASSIFICATION,
    crs="EPSG:4326",
    resolution="1 arc-second grid (synthetic)",
    known_limitations=("SYNTHETIC TEST FIXTURE — not real terrain",),
)

FIXTURE_DRAINAGE_SOURCE = SourceProvenance(
    source_name="UFNS SYNTHETIC TEST FIXTURE",
    dataset_name="m10-fixture-drains",
    version="fixture-v1",
    acquisition_timestamp=datetime(2026, 8, 22, tzinfo=timezone.utc),
    source_url="fixture://tests/fixtures/m10/generators.py",
    license_id="none-synthetic",
    classification=FIXTURE_CLASSIFICATION,
    crs="EPSG:4326",
    known_limitations=("SYNTHETIC TEST FIXTURE — not real drainage geometry",),
)

NODATA = -32768.0


def pilot_lonlat_window(pad_deg: float = 0.01) -> tuple[float, float, float, float]:
    """(west, south, east, north) of the pilot grid in EPSG:4326, padded.

    Derives from the authoritative pilot GridSpec (pilot_grid_spec), so
    fixtures always overlap the current pilot area regardless of spatial
    re-baseline changes.
    """
    from services.ingestion.dem_real import pilot_grid_spec

    grid = pilot_grid_spec()
    xmin, ymin, xmax, ymax = grid.bounds
    sw = to_lonlat(xmin, ymin)
    ne = to_lonlat(xmax, ymax)
    return (
        min(sw.lon, ne.lon) - pad_deg,
        min(sw.lat, ne.lat) - pad_deg,
        max(sw.lon, ne.lon) + pad_deg,
        max(sw.lat, ne.lat) + pad_deg,
    )


def _plane_elevation(nx: int, ny: int, seed: int) -> np.ndarray:
    """Synthetic elevation plane normalized to [0, 1] coordinate space.

    Uses normalized coordinates (0→1) so the elevation range is independent
    of array dimensions. Base plane slopes NW→SE around 100 m with small
    noise, giving a consistent ~88–112 m range regardless of grid size.
    """
    rng = np.random.default_rng(seed)
    xx = np.linspace(0.0, 1.0, nx)
    yy = np.linspace(0.0, 1.0, ny)
    xg, yg = np.meshgrid(xx, yy)
    z = 100.0 - 12.0 * xg + 6.0 * yg + 0.05 * rng.standard_normal((ny, nx))
    return np.rint(z).astype("int16")


def write_dem_fixture(
    path: Path,
    *,
    window: tuple[float, float, float, float] | None = None,
    cell_deg: float = 1.0 / 3600.0,
    nodata_patch: bool = True,
    seed: int = 20260822,
    crs: str = "EPSG:4326",
) -> Path:
    """Deterministic int16 GeoTIFF DEM fixture with a central nodata patch."""
    import rasterio
    from affine import Affine

    west, south, east, north = window if window is not None else pilot_lonlat_window()
    nx = max(2, round((east - west) / cell_deg))
    ny = max(2, round((north - south) / cell_deg))
    z = _plane_elevation(nx, ny, seed)
    if nodata_patch:
        z[ny // 2 - 10 : ny // 2 + 10, nx // 2 - 10 : nx // 2 + 10] = int(NODATA)
    transform = Affine(cell_deg, 0.0, west, 0.0, -cell_deg, south + ny * cell_deg)
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=nx,
        height=ny,
        count=1,
        dtype="int16",
        crs=crs,
        nodata=NODATA,
        transform=transform,
    ) as dst:
        dst.write(z, 1)
        dst.update_tags(ARENA_PROVENANCE="SYNTHETIC TEST FIXTURE")
    return path


def write_dem_fixture_no_overlap(path: Path) -> Path:
    """DEM fixture at correct ~1-arcsec resolution but far from the pilot grid."""
    return write_dem_fixture(path, window=(10.0, 50.0, 10.06, 50.06), seed=7)


def write_nan_dem_fixture(path: Path) -> Path:
    """Float32 DEM fixture containing NaN values outside the nodata mask."""
    import rasterio
    from affine import Affine

    cell = 1.0 / 3600.0
    west, south, east, north = pilot_lonlat_window()
    nx = max(2, round((east - west) / cell))
    ny = max(2, round((north - south) / cell))
    z = _plane_elevation(nx, ny, 3).astype("float32")
    z[5, 5] = np.nan
    transform = Affine(cell, 0.0, west, 0.0, -cell, south + ny * cell)
    with rasterio.open(
        path, "w", driver="GTiff", width=nx, height=ny, count=1,
        dtype="float32", crs="EPSG:4326", nodata=NODATA, transform=transform,
    ) as dst:
        dst.write(z, 1)
    return path


def _drain_rows(variant: str) -> tuple[list[tuple], list[str]]:
    from shapely import wkb
    from shapely.geometry import LineString, Point

    def line(x0: float, y0: float, x1: float, y1: float) -> bytes:
        return wkb.dumps(LineString([(x0, y0), (x1, y1)]))

    # Geometry lives inside the pilot lon/lat window (real-pilot: 88.6–88.85°E,
    # 22.65–22.90°N). Coordinates chosen to fall within the pilot area.
    if variant == "unsupported_geometry":
        rows = [
            ("p1", "Vent pt", "vent", 300.0, 0.013, wkb.dumps(Point((88.70, 22.72)))),
            ("p2", "Manhole pt", "manhole", None, None, wkb.dumps(Point((88.71, 22.73)))),
        ]
        return rows, ["id", "name", "type", "diameter_mm", "manning_n", "geometry"]
    if variant == "invalid_geometry":
        rows = [
            ("d1", "Bad wkb", "drain", 300.0, 0.013, b"garbage-not-wkb"),
            ("d2", "Null geom", "drain", 300.0, 0.013, None),
            ("d3", "Valid", "drain", 300.0, 0.013, line(88.68, 22.70, 88.69, 22.71)),
        ]
        return rows, ["id", "name", "type", "diameter_mm", "manning_n", "geometry"]
    if variant == "duplicate_ids":
        rows = [
            ("d1", "First", "drain", 300.0, 0.013, line(88.68, 22.70, 88.69, 22.71)),
            ("d1", "Dup id", "drain", 300.0, 0.013, line(88.70, 22.70, 88.71, 22.71)),
            ("d3", "Unique", "pipe", 450.0, 0.013, line(88.69, 22.72, 88.70, 22.72)),
        ]
        return rows, ["id", "name", "type", "diameter_mm", "manning_n", "geometry"]
    if variant == "unknown_types":
        rows = [
            ("d1", "Mystery", "mystery feature", 300.0, 0.013, line(88.68, 22.70, 88.69, 22.71)),
            ("d2", "Empty type", "", 300.0, 0.013, line(88.69, 22.71, 88.70, 22.72)),
            ("d3", "Known", "drain", 300.0, 0.013, line(88.70, 22.70, 88.71, 22.70)),
        ]
        return rows, ["id", "name", "type", "diameter_mm", "manning_n", "geometry"]
    if variant == "missing_hydraulics":
        rows = [
            ("d1", "Main", "drain", line(88.68, 22.70, 88.69, 22.71)),
            ("d2", "Cross", "pipe", line(88.69, 22.71, 88.70, 22.72)),
        ]
        return rows, ["id", "name", "type", "geometry"]
    if variant == "ambiguous_units":
        rows = [
            ("d1", "Ambiguous", "drain", 300.0, 0.097, 100.5, line(88.68, 22.70, 88.69, 22.71)),
            ("d2", "Ambiguous2", "pipe", 450.0, 0.011, 99.5, line(88.69, 22.71, 88.70, 22.72)),
        ]
        return rows, ["id", "name", "type", "diameter", "roughness", "invert_level_m", "geometry"]
    if variant == "non_numeric_diameter":
        rows = [
            ("d1", "Str diam", "drain", "wide", 0.013, line(88.68, 22.70, 88.69, 22.71)),
        ]
        return rows, ["id", "name", "type", "diameter_m", "manning_n", "geometry"]
    if variant == "no_id_column":
        rows = [
            ("Main", "drain", 300.0, 0.013, line(88.68, 22.70, 88.69, 22.71)),
            ("Cross", "pipe", 450.0, 0.013, line(88.69, 22.71, 88.70, 22.72)),
        ]
        return rows, ["name", "type", "diameter_mm", "manning_n", "geometry"]

    # default: valid_lines
    rows = [
        ("d1", "Main drain", "drain", 300.0, 0.013, line(88.68, 22.70, 88.69, 22.71)),
        ("d2", "Pipe A", "pipe", 450.0, 0.013, line(88.69, 22.71, 88.70, 22.72)),
        ("d3", "Storm drain", "stormwater drain", None, 0.014, line(88.70, 22.70, 88.71, 22.70)),
        ("d4", "Channel", "channel", 900.0, 0.025, line(88.68, 22.73, 88.71, 22.73)),
    ]
    return rows, ["id", "name", "type", "diameter_mm", "manning_n", "geometry"]


def write_drainage_fixture(
    path: Path,
    *,
    variant: str = "valid_lines",
    crs: bool = True,
) -> Path:
    """Deterministic GeoParquet drainage fixture (SYNTHETIC TEST FIXTURE).

    Variants: valid_lines (default), missing_hydraulics, duplicate_ids,
    invalid_geometry, unsupported_geometry, unknown_types, ambiguous_units,
    non_numeric_diameter, no_id_column.
    """
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq
    from pyproj import CRS

    rows, columns = _drain_rows(variant)
    df = pd.DataFrame({c: [r[i] for r in rows] for i, c in enumerate(columns)})
    table = pa.Table.from_pandas(df)
    meta = dict(table.schema.metadata or {})
    geo: dict[str, Any] = {
        "primary_column": "geometry",
        "columns": {
            "geometry": {
                "encoding": "WKB",
                "crs": CRS.from_epsg(4326).to_wkt() if crs else None,
            }
        },
    }
    meta[b"geo"] = json.dumps(geo).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table.replace_schema_metadata(meta), path)
    return path


def write_plain_parquet_fixture(path: Path) -> Path:
    """Plain (non-geospatial) parquet: id/name/type/hydraulic columns, no geometry."""
    import pandas as pd

    df = pd.DataFrame(
        {
            "id": ["a", "b"],
            "name": ["n1", "n2"],
            "type": ["drain", "drain"],
            "diameter": [0.3, 0.5],
            "invert_level": [100.0, 99.0],
            "capacity": [0.01, 0.02],
            "manning_n": [0.013, 0.013],
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)
    return path


def write_not_a_parquet(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"this is not a parquet file")
    return path


def write_not_a_geotiff(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"this is not a geotiff")
    return path
