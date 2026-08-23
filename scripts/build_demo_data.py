#!/usr/bin/env python3
"""M1 entry point: build the deterministic data/demo bundle.

Outputs (all SYNTHETIC/SIMULATED, documented derivations):
  data/demo/dem.tif            synthetic DSM fixture (EPSG:32645, 30 m)
  data/demo/dem_conditioning.json
  data/demo/rain/{i:02d}.tif   provisional scenario rainfall fields (15-min)
  data/demo/manifest.json      provenance + checksums
  data/demo/preview_dem.png    visual inspection artifact
  data/demo/preview_rain.png
Reproducible: identical inputs -> identical sha256 outputs (tested).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.contracts import (  # noqa: E402
    GridSpec,
    ProvenanceClass,
    QualityFlag,
)
from services.ingestion import crs as crs_mod  # noqa: E402
from services.ingestion.dem import (  # noqa: E402
    CELL_SIZE_M,
    DOMAIN_M,
    GRID_CELLS,
    SEED,
    VERTICAL_REFERENCE,
    conditioning_report,
    grid_affine,
    synthetic_dem,
    write_geotiff,
)
from services.ingestion.provenance import Manifest, make_lineage  # noqa: E402
from services.ingestion.timeutil import forecast_intervals  # noqa: E402
from services.rainfall.fields import render_interval  # noqa: E402
from services.rainfall.scenarios import (  # noqa: E402
    DURATION_MINUTES,
    INTERVAL_MINUTES,
    build_demo_scenarios,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "demo"
ISSUE_TIME = datetime(2026, 8, 21, 0, 0, tzinfo=timezone.utc)
PILOT_ID = "synthetic_wb_fixture_v1"

# Fixture rainfall for M1 representation tests: provisional "heavy" profile,
# convective pattern. (The four approved scenarios are defined in scenarios.py.)
FIXTURE_PATTERN = "convective_cell"
FIXTURE_PROFILE_ID = "heavy_v1"


_LUT_ELEV = np.array(
    [[20, 70, 30], [60, 110, 40], [120, 160, 60], [190, 200, 110],
     [220, 210, 150], [235, 235, 235], [200, 200, 210]],
    dtype=np.float64,
)
_LUT_RAIN = np.array(
    [[245, 248, 255], [180, 215, 250], [80, 160, 240], [30, 90, 200],
     [120, 60, 200], [200, 40, 120], [220, 20, 30]],
    dtype=np.float64,
)


def _preview_png(array: np.ndarray, path: Path, vmin=None, vmax=None, lut=_LUT_ELEV) -> None:
    """Colour-ramp preview PNG (no matplotlib dependency; LUTs documented above)."""
    from PIL import Image

    norm = (array.astype(np.float64) - (vmin if vmin is not None else array.min()))
    span = (vmax if vmax is not None else array.max()) - (vmin if vmin is not None else array.min())
    if span <= 0:
        span = 1.0
    norm = np.clip(norm / span, 0, 1)
    idx = (norm * (len(lut) - 1)).astype(np.int32)
    rgb = lut[idx].astype(np.uint8)
    Image.fromarray(rgb, mode="RGB").save(path)


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    manifest = Manifest(PILOT_ID, base_dir=DATA_DIR)

    # -- grid -----------------------------------------------------------------
    affine = grid_affine()
    xmin, ymax = affine.c, affine.f
    grid = GridSpec(
        grid_id=f"{PILOT_ID}_grid",
        crs_wkt_or_epsg=crs_mod.WB_PROJECTED_CRS,
        vertical_crs=VERTICAL_REFERENCE,
        width=GRID_CELLS,
        height=GRID_CELLS,
        affine_transform=[affine.a, affine.b, affine.c, affine.d, affine.e, affine.f],
        cell_size_m=CELL_SIZE_M,
        nodata=None,
        bounds=[xmin, ymax - DOMAIN_M, xmin + DOMAIN_M, ymax],
    )

    # -- DEM ------------------------------------------------------------------
    dem_path = DATA_DIR / "dem.tif"
    dem = synthetic_dem(seed=SEED)
    write_geotiff(dem, dem_path)
    dem_lineage = make_lineage(
        dataset_id=f"{PILOT_ID}_dem",
        version="v1",
        source_name="UFNS synthetic DSM fixture (seeded procedural terrain)",
        provenance_class=ProvenanceClass.SYNTHETIC,
        content=dem_path,
        licence_id="internal-generated",
        quality_flags=[QualityFlag.SYNTHETIC],
        native_crs=crs_mod.WB_PROJECTED_CRS,
        native_resolution={"x": CELL_SIZE_M, "y": CELL_SIZE_M, "unit": "m"},
        processing_steps=["seeded procedural generation (seed=20260821); no conditioning"],
        acquired_at=ISSUE_TIME,
    )
    manifest.add_asset("dem", dem_path, dem_lineage, extra={"vertical_reference": VERTICAL_REFERENCE})

    cond_path = DATA_DIR / "dem_conditioning.json"
    conditioning_report(dem, dem, cond_path)  # no-op; depressions intentional

    # -- Rainfall fields (fixture: provisional heavy profile, convective) -----
    rain_dir = DATA_DIR / "rain"
    rain_dir.mkdir(exist_ok=True)
    from services.ingestion.provenance import sha256_file
    from services.rainfall.scenarios import build_profile

    from services.ingestion.timeutil import iso_utc

    profile = build_profile("heavy", 45.0)
    intervals = forecast_intervals(ISSUE_TIME, DURATION_MINUTES, INTERVAL_MINUTES)
    first = None
    rain_index = {"profile": profile.model_dump(mode="json"), "files": []}
    for (vf, vt, lead), rate in zip(intervals, profile.intensities_mmh):
        field = render_interval((GRID_CELLS, GRID_CELLS), FIXTURE_PATTERN, rate, lead // INTERVAL_MINUTES, SEED)
        rp = rain_dir / f"rain_{lead:03d}.tif"
        import rasterio

        with rasterio.open(
            rp, "w", driver="GTiff", height=GRID_CELLS, width=GRID_CELLS, count=1,
            dtype="float32", crs=crs_mod.WB_PROJECTED_CRS, transform=grid_affine(), compress="deflate",
        ) as dst:
            dst.write(field, 1)
            dst.update_tags(
                ARENA_PROVENANCE="SIMULATED_SCENARIO",
                ARENA_VALID_FROM=iso_utc(vf),
                ARENA_VALID_TO=iso_utc(vt),
                ARENA_LEAD_MIN=str(lead),
                ARENA_UNITS="mm/h",
                ARENA_DERIVATION="alternating-block (Chow et al. 1988); PROVISIONAL",
            )
        rain_index["files"].append(
            {"uri": f"rain/{rp.name}", "valid_from": iso_utc(vf), "valid_to": iso_utc(vt),
             "lead_minutes": lead, "sha256": sha256_file(rp)}
        )
        if first is None:
            first = field
    rain_index_path = DATA_DIR / "rain_index.json"
    rain_index_path.write_text(json.dumps(rain_index, indent=2, sort_keys=True))
    rain_lineage = make_lineage(
        dataset_id=f"{PILOT_ID}_rain_fixture",
        version="v1",
        source_name="UFNS provisional demo rainfall (alternating-block; see scenarios.py)",
        provenance_class=ProvenanceClass.SIMULATED_SCENARIO,
        content=rain_index_path,
        licence_id="internal-generated",
        quality_flags=[QualityFlag.SYNTHETIC, QualityFlag.PROVISIONAL],
        native_resolution={"x": CELL_SIZE_M, "y": CELL_SIZE_M, "unit": "m"},
        processing_steps=[
            "alternating-block hyetograph (Chow et al. 1988), PROVISIONAL parameters",
            "convective-cell spatial pattern (seeded)",
        ],
        acquired_at=ISSUE_TIME,
    )
    manifest.add_asset(
        "rainfall_fixture", rain_index_path, rain_lineage,
        extra={"interval_minutes": INTERVAL_MINUTES, "n_intervals": len(intervals),
               "profile_id": FIXTURE_PROFILE_ID, "review_status": "PROVISIONAL"},
    )

    # -- Scenario definitions (contract preview) -----------------------------
    dem_uri = str(Path("data/demo/dem.tif"))
    network_uri = str(Path("data/demo/drainage_synthetic.inp"))  # built in M3
    scenarios = build_demo_scenarios(grid, dem_uri, network_uri, ISSUE_TIME, dem_lineage)
    scenario_doc = {s.scenario_id: s.model_dump(mode="json") for s in scenarios}
    scenario_path = DATA_DIR / "scenarios.json"
    scenario_path.write_text(json.dumps(scenario_doc, indent=2, sort_keys=True, default=str))
    manifest.add_asset(
        "scenario_definitions", scenario_path,
        make_lineage(
            dataset_id=f"{PILOT_ID}_scenarios", version="v1",
            source_name="UFNS scenario definitions (M5 preview)",
            provenance_class=ProvenanceClass.SIMULATED_SCENARIO,
            content=scenario_path, licence_id="internal-generated",
            quality_flags=[QualityFlag.SYNTHETIC, QualityFlag.PROVISIONAL],
            acquired_at=ISSUE_TIME,
        ),
        extra={"review_status": "PROVISIONAL"},
    )

    # -- Previews --------------------------------------------------------------
    _preview_png(dem, DATA_DIR / "preview_dem.png", lut=_LUT_ELEV)
    _preview_png(first, DATA_DIR / "preview_rain.png", lut=_LUT_RAIN)
    manifest.add_asset("preview_dem", DATA_DIR / "preview_dem.png",
                       make_lineage("preview_dem", "v1", "UFNS preview", ProvenanceClass.DERIVED,
                                    DATA_DIR / "preview_dem.png", "internal-generated",
                                    acquired_at=ISSUE_TIME))
    manifest.add_asset("preview_rain", DATA_DIR / "preview_rain.png",
                       make_lineage("preview_rain", "v1", "UFNS preview", ProvenanceClass.DERIVED,
                                    DATA_DIR / "preview_rain.png", "internal-generated",
                                    acquired_at=ISSUE_TIME))

    # -- Manifest + fingerprint -------------------------------------------------
    manifest_path = manifest.write(
        DATA_DIR / "manifest.json",
        extra={
            "simulation_grid": grid.model_dump(mode="json"),
            "issue_time": iso_utc(ISSUE_TIME),
            "provisional_notes": [
                "Synthetic terrain fixture; NOT real topography.",
                "Rainfall intensities PROVISIONAL (D-016 review before M5).",
            ],
        },
        created_at=ISSUE_TIME,  # deterministic bundle: no wall-clock timestamps
    )
    fingerprint = scenarios[0].fingerprint(extra={"grid_id": grid.grid_id})
    print(f"demo bundle written to {DATA_DIR}")
    print(f"manifest: {manifest_path}")
    print(f"scenario fingerprint (normal): {fingerprint}")
    print(f"dem sha256: {dem_lineage.content_sha256}")
    print(f"rain sha256: {rain_lineage.content_sha256}")


if __name__ == "__main__":
    main()
