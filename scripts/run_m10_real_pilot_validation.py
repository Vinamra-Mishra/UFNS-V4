"""M10 — Real-pilot validation execution driver.

Runs the EXISTING M10 ingestion/validation/normalization/audit/mapping
machinery against the real artifacts in the canonical raw-data location
(data/raw/) and writes the machine-readable gate evidence to
data/processed/m10_real_pilot_validation.json.

Authoritative pilot: the pilot GridSpec (pilot_grid_spec) is derived from
the real Copernicus GLO-30 DEM tile (bagjola_kolkata_glo30_dem.tif).
Previous synthetic M1 grid replaced 2026-08-23 by human decision.

This driver performs no analysis of its own beyond spatial-coherence
geometry (bounds/overlap between the actual datasets and the authoritative
pilot GridSpec). All validation semantics come from
services/ingestion/{dem_real,drainage_real}.py — no parallel pipeline.

Run: python scripts/run_m10_real_pilot_validation.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.ingestion.dem_real import ingest_dem, normalize_dem, pilot_grid_spec
from services.ingestion.drainage_real import (
    WB_AMRUT_EXTERNAL_CRS_PROVENANCE,
    audit_wb_amrut_drains,
    map_drainage_entities,
)

DATA_RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed" / "m10_real_pilot_validation.json"

DEM_PATH = DATA_RAW / "bagjola_kolkata_glo30_dem.tif"
DRAINS_PATH = DATA_RAW / "WB_AMRUT_Stormwater_drains.parquet"
VENTS_PATH = DATA_RAW / "WB_AMRUT_Stormwater_vents.parquet"


def _wgs_overlap(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
    if not a or not b or len(a) < 4 or len(b) < 4:
        return False
    return min(a[2], b[2]) - max(a[0], b[0]) > 0 and min(a[3], b[3]) - max(a[1], b[1]) > 0


def _pilot_grid_wgs() -> tuple[float, float, float, float]:
    from rasterio.warp import transform_bounds

    grid = pilot_grid_spec()
    return tuple(transform_bounds(grid.crs_wkt_or_epsg, "EPSG:4326", *grid.bounds, densify_pts=21))


def main() -> int:
    missing = [p.name for p in (DEM_PATH, DRAINS_PATH, VENTS_PATH) if not p.exists()]
    if missing:
        print(f"real artifacts missing from {DATA_RAW}: {missing}")
        return 1

    dem_ingest = ingest_dem(DEM_PATH)
    dem_norm = normalize_dem(DEM_PATH)

    drains_audit = audit_wb_amrut_drains(
        DRAINS_PATH, external_crs_provenance=WB_AMRUT_EXTERNAL_CRS_PROVENANCE
    )
    vents_audit = audit_wb_amrut_drains(
        VENTS_PATH, external_crs_provenance=WB_AMRUT_EXTERNAL_CRS_PROVENANCE
    )
    drains_map = map_drainage_entities(
        DRAINS_PATH, external_crs_provenance=WB_AMRUT_EXTERNAL_CRS_PROVENANCE
    )
    vents_map = map_drainage_entities(
        VENTS_PATH, external_crs_provenance=WB_AMRUT_EXTERNAL_CRS_PROVENANCE
    )

    # Spatial coherence (actual metadata only; never filenames).
    pilot_wgs = _pilot_grid_wgs()
    dem_wgs = tuple(dem_ingest.output_bounds or ())
    drains_wgs = (
        (drains_audit.spatial_coverage.west, drains_audit.spatial_coverage.south,
         drains_audit.spatial_coverage.east, drains_audit.spatial_coverage.north)
        if drains_audit.spatial_coverage else ()
    )
    vents_wgs = (
        (vents_audit.spatial_coverage.west, vents_audit.spatial_coverage.south,
         vents_audit.spatial_coverage.east, vents_audit.spatial_coverage.north)
        if vents_audit.spatial_coverage else ()
    )

    coherence = {
        "pilot_grid_wgs": {k: round(v, 6) for k, v in zip(("west", "south", "east", "north"), pilot_wgs)},
        "dem_wgs": {k: round(v, 6) for k, v in zip(("west", "south", "east", "north"), dem_wgs)},
        "drains_wgs": {k: round(v, 6) for k, v in zip(("west", "south", "east", "north"), drains_wgs)},
        "vents_wgs": {k: round(v, 6) for k, v in zip(("west", "south", "east", "north"), vents_wgs)},
        "dem_overlaps_pilot_grid": _wgs_overlap(dem_wgs, pilot_wgs),
        "drains_overlaps_pilot_grid": _wgs_overlap(drains_wgs, pilot_wgs),
        "vents_overlaps_pilot_grid": _wgs_overlap(vents_wgs, pilot_wgs),
        "dem_overlaps_drains_extent": _wgs_overlap(dem_wgs, drains_wgs),
        "dem_overlaps_vents_extent": _wgs_overlap(dem_wgs, vents_wgs),
        "note": (
            "Pilot area is the authoritative real-pilot GridSpec (pilot_grid_spec), "
            "derived from bagjola_kolkata_glo30_dem.tif (88.60–88.85°E, 22.65–22.90°N). "
            "Overlap computed from actual raster/geometry bounds in EPSG:4326. "
            "Previous synthetic M1 grid replaced 2026-08-23."
        ),
    }

    report = {
        "executed_at_utc": dem_norm.provenance.acquisition_timestamp.isoformat() if dem_norm.provenance.acquisition_timestamp else None,
        "artifacts": {
            "dem": {"path": str(DEM_PATH.relative_to(ROOT))},
            "drains": {"path": str(DRAINS_PATH.relative_to(ROOT))},
            "vents": {"path": str(VENTS_PATH.relative_to(ROOT))},
        },
        "dem_ingest": dem_ingest.to_dict(),
        "dem_normalize": {k: v for k, v in dem_norm.to_dict().items() if k != "elevation_shape"},
        "drains_audit": drains_audit.to_dict(),
        "vents_audit": vents_audit.to_dict(),
        "drains_mapping": {
            k: v for k, v in drains_map.to_dict().items() if k not in ("entities",)
        },
        "vents_mapping": {
            k: v for k, v in vents_map.to_dict().items() if k not in ("entities",)
        },
        "spatial_coherence": coherence,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, sort_keys=False))

    print(f"DEM ingest:        {dem_ingest.status.value}  warnings={list(dem_ingest.validation_warnings)}")
    print(f"DEM normalize:     {dem_norm.status.value}  errors={list(dem_norm.validation_errors)}")
    print(f"Drains audit:      {drains_audit.status.value}  records={drains_audit.record_count}  "
          f"crs_valid={drains_audit.crs_valid}  unsupported={drains_audit.unsupported_geometry_count}")
    a = drains_audit.audit
    print(f"  duplicates={a.duplicate_count}  invalid_geom={a.invalid_geometry_count}  "
          f"extent={coherence['drains_wgs']}")
    print(f"  missing hydraulics: {drains_audit.missing_hydraulic_parameters}")
    print(f"Vents audit:       {vents_audit.status.value}  records={vents_audit.record_count}  "
          f"crs_valid={vents_audit.crs_valid}  geom_type={vents_audit.audit.geometry_type}")
    print(f"Drains mapping:    {drains_map.status.value}  blockers={list(drains_map.blockers)}")
    print(f"Vents mapping:     {vents_map.status.value}  blockers={list(vents_map.blockers)}")
    print(f"Spatial coherence: {json.dumps(coherence, indent=2)}")
    print(f"evidence: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
