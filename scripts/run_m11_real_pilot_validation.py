"""M11 — Real-pilot integration validation runner (Section 16 experiments).

Runs the deterministic M11 experiments M11-01 .. M11-12 against the real
Bagjola/Kolkata artifacts in data/raw/ and writes the gate matrix + inspection
artifacts to data/demo/m11/.

Usage:
    python scripts/run_m11_real_pilot_validation.py

Every gate requires EXECUTION EVIDENCE (Section 18). No gate PASSes merely
because code executes.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.ingestion.dem import (
    GRID_CELLS,
    ORIGIN_X,
    ORIGIN_Y,
    synthetic_dem,
)
from services.pilot import (
    DEFAULT_MODEB_DURATION_MIN,
    DEFAULT_N_INLETS,
    DEFAULT_ROI_OFFSET,
    DEFAULT_ROI_WINDOW,
    M11SimulationAdapter,
    RealDrainageAdapter,
    RealTerrainAdapter,
    authoritative_pilot_grid,
    build_real_drainage_contract,
    build_synthetic_fixture_contract,
    drainage_mapping_stats,
    gridspec_fingerprint,
)

RAW_DEM = REPO_ROOT / "data" / "raw" / "bagjola_kolkata_glo30_dem.tif"
RAW_DRAINS = REPO_ROOT / "data" / "raw" / "WB_AMRUT_Stormwater_drains.parquet"
RAW_VENTS = REPO_ROOT / "data" / "raw" / "WB_AMRUT_Stormwater_vents.parquet"
OUT_DIR = REPO_ROOT / "data" / "demo" / "m11"


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_artifacts() -> None:
    missing = [p for p in (RAW_DEM, RAW_DRAINS, RAW_VENTS) if not p.exists()]
    if missing:
        sys.exit(f"REQUIRED real artifacts missing: {missing}")


def run_experiments() -> dict[str, Any]:
    _require_artifacts()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    gates: dict[str, dict[str, Any]] = {}
    evidence: dict[str, Any] = {}
    t0 = time.perf_counter()

    # ------------------------------------------------------------------ #
    # M11-01 Real DEM ingestion -> normalized GridSpec
    # ------------------------------------------------------------------ #
    terrain = RealTerrainAdapter(RAW_DEM).load()
    pilot = authoritative_pilot_grid()
    answers = terrain.provenance_answers()
    m11_01_ok = (
        terrain.normalization_status == "NORMALIZED"
        and terrain.grid == pilot
        and terrain.elevation.shape == (pilot.height, pilot.width)
        and len(terrain.processing_fingerprint) == 64
        and terrain.raw_dem_sha256 != ""
        and terrain.nodata_present  # real DEM carries nodata, preserved not filled
    )
    gates["M11-01"] = {
        "name": "Real DEM model-ready",
        "status": "PASS" if m11_01_ok else "FAIL",
        "evidence": {
            "normalization_status": terrain.normalization_status,
            "grid_id": terrain.grid.grid_id,
            "shape": list(terrain.elevation.shape),
            "processing_fingerprint": terrain.processing_fingerprint,
            "nodata_cells": terrain.nodata_cells,
            "provenance_answers": answers,
        },
    }
    evidence["terrain"] = terrain.to_dict()

    # ------------------------------------------------------------------ #
    # M11-02 Real drainage ingestion -> reprojection/alignment
    # ------------------------------------------------------------------ #
    drain = RealDrainageAdapter(RAW_DRAINS).map_and_align(pilot)
    stats = drainage_mapping_stats(drain.mapping_result)
    sample = drain.entities_reprojected[0] if drain.entities_reprojected else {}
    # reprojection evidence: coordinates are in metres (EPSG:32645), not degrees
    reproj_ok = (
        drain.modelling_crs == "EPSG:32645"
        and drain.crs_source.provenance_status == "AUTHORITATIVE_EXTERNAL_PROVENANCE"
        and drain.crs_source.embedded_crs == "ABSENT"
        and len(drain.entities_reprojected) == stats["mapped"] + stats["unresolved_type"]
        and "MULTILINESTRING" in sample.get("geometry_wkt_model_crs", "")
        and abs(_first_coord_x(sample.get("geometry_wkt_model_crs", ""))) > 1000.0  # metres, not deg
    )
    gates["M11-02"] = {
        "name": "Real drainage spatially aligned",
        "status": "PASS" if reproj_ok else "FAIL",
        "evidence": {
            "source_crs": drain.source_crs,
            "modelling_crs": drain.modelling_crs,
            "crs_source": drain.crs_source.to_dict(),
            "entities_reprojected": len(drain.entities_reprojected),
            "processing_fingerprint": drain.processing_fingerprint,
        },
    }
    evidence["drainage"] = {k: v for k, v in drain.to_dict().items() if k != "entities_reprojected"}
    evidence["drainage"]["sample_entity_reprojected"] = sample
    evidence["drainage_stats"] = stats

    # ------------------------------------------------------------------ #
    # M11-03 Real drainage entity provenance
    # ------------------------------------------------------------------ #
    total = stats["total_source_features"]
    accounted = stats["mapped"] + stats["unresolved_type"] + stats["rejected"]
    prov_ok = (
        total == 90395
        and accounted == total  # every feature accounted for
        and all("source_id" in e for e in drain.entities_reprojected[:10])
        and all("mapping_status" in e for e in drain.entities_reprojected[:10])
    )
    gates["M11-03"] = {
        "name": "Entity provenance complete",
        "status": "PASS" if prov_ok else "FAIL",
        "evidence": {
            "total_source_features": total,
            "accounted_for": accounted,
            "mapping_stats": {k: stats[k] for k in ("mapped", "unresolved_type", "rejected")},
            "rejection_breakdown": stats["rejection_breakdown"],
            "traceable_fields": ["feature_id", "source_id", "source_type", "mapping_status"],
        },
    }

    # ------------------------------------------------------------------ #
    # M11-04 Hydraulic readiness contract
    # ------------------------------------------------------------------ #
    contract = build_real_drainage_contract("WB_AMRUT_Stormwater_drains")
    m11_04_ok = (
        contract.hydraulic_network_ready is False
        and set(contract.missing_attributes) == {
            "diameter_m", "invert_upstream_m", "invert_downstream_m", "manning_n", "capacity_m3s"
        }
        and all(
            contract.attributes[name].availability.value == "MISSING"
            for name in contract.missing_attributes
        )
    )
    gates["M11-04"] = {
        "name": "Hydraulic readiness explicitly governed",
        "status": "PASS" if m11_04_ok else "FAIL",
        "evidence": contract.to_dict(),
    }
    evidence["hydraulic_contract_real"] = contract.to_dict()

    # ------------------------------------------------------------------ #
    # M11-05 Real/synthetic separation
    # ------------------------------------------------------------------ #
    syn_contract = build_synthetic_fixture_contract("M4_synthetic_exact_exchange_fixture")
    labels_mode_b = [
        "REAL_TERRAIN",
        "SYNTHETIC_HYDRAULICS",
        "REAL_TERRAIN_SYNTHETIC_HYDRAULICS",
    ]
    sep_ok = (
        "REAL_DATA" not in syn_contract.assumed_attributes  # fixture values not REAL_DATA
        and syn_contract.real_hydraulic_network_ready is False
        and syn_contract.synthetic_fixture_labelled is True
        and "REAL_TERRAIN_SYNTHETIC_HYDRAULICS" in labels_mode_b
        and "SYNTHETIC" not in terrain.to_dict()["labels"]  # real terrain never SYNTHETIC
    )
    gates["M11-05"] = {
        "name": "Real/synthetic separation",
        "status": "PASS" if sep_ok else "FAIL",
        "evidence": {
            "terrain_labels": terrain.to_dict()["labels"],
            "mode_b_content_label": "REAL_TERRAIN_SYNTHETIC_HYDRAULICS",
            "synthetic_contract": syn_contract.to_dict(),
        },
    }
    evidence["hydraulic_contract_synthetic"] = syn_contract.to_dict()

    # ------------------------------------------------------------------ #
    # M11-06 Real terrain + synthetic hydraulic fixture integration
    # ------------------------------------------------------------------ #
    adapter = M11SimulationAdapter(terrain)
    mode_b = adapter.mode_b_real_terrain_synthetic_hydraulics(
        duration_minutes=DEFAULT_MODEB_DURATION_MIN,
        window=DEFAULT_ROI_WINDOW,
        offset=DEFAULT_ROI_OFFSET,
        n_inlets=DEFAULT_N_INLETS,
        rainfall_mmh=80.0,
        synthetic_contract=syn_contract,
    )
    mb = mode_b.mass_balance
    depths_finite = all(np.all(np.isfinite(a)) for a in mode_b.m4_result.depth_arrays.values())
    m11_06_ok = (
        mode_b.content_label == "REAL_TERRAIN_SYNTHETIC_HYDRAULICS"
        and mode_b.capability_state.hydraulic_network_ready is False
        and mode_b.m4_result.simulation_run.status == "succeeded"
        and mode_b.roi.raw_dem_sha256 == terrain.raw_dem_sha256
        and depths_finite
        and mode_b.mass_ledger["S2D_m3"] > 0.0  # real exchange occurred through real terrain
    )
    gates["M11-06"] = {
        "name": "Real-pilot simulation path",
        "status": "PASS" if m11_06_ok else "FAIL",
        "evidence": {
            "run_id": mode_b.m4_result.simulation_run.run_id,
            "content_label": mode_b.content_label,
            "roi": mode_b.roi.to_dict(),
            "config_fingerprint": mode_b.m4_result.simulation_run.configuration_fingerprint,
            "S2D_m3": mode_b.mass_ledger["S2D_m3"],
            "outfall_m3": mode_b.mass_ledger["drainage_outfall_m3"],
        },
    }

    # ------------------------------------------------------------------ #
    # M11-07 Mass conservation on the integrated model
    # ------------------------------------------------------------------ #
    rel = mode_b.mass_ledger["relative_residual"]
    m11_07_ok = (
        mode_b.mass_ledger["status"] == "pass"
        and rel is not None and rel <= 0.01
        and mode_b.mass_ledger["combined_residual_m3"] is not None
    )
    gates["M11-07"] = {
        "name": "Mass conservation",
        "status": "PASS" if m11_07_ok else "FAIL",
        "evidence": {
            "status": mode_b.mass_ledger["status"],
            "relative_residual": rel,
            "tolerance_rel": 0.01,
            "combined_residual_m3": mode_b.mass_ledger["combined_residual_m3"],
            "mass_balance": mb.model_dump(mode="json"),
            "swmm_flow_routing_error_pct": mode_b.mass_ledger["swmm_flow_routing_error_pct"],
        },
    }

    # ------------------------------------------------------------------ #
    # M11-08 Deterministic repeatability
    # ------------------------------------------------------------------ #
    mode_b2 = adapter.mode_b_real_terrain_synthetic_hydraulics(
        duration_minutes=DEFAULT_MODEB_DURATION_MIN,
        window=DEFAULT_ROI_WINDOW,
        offset=DEFAULT_ROI_OFFSET,
        n_inlets=DEFAULT_N_INLETS,
        rainfall_mmh=80.0,
        synthetic_contract=syn_contract,
    )
    fp1 = mode_b.m4_result.simulation_run.configuration_fingerprint
    fp2 = mode_b2.m4_result.simulation_run.configuration_fingerprint
    same_depths = all(
        np.array_equal(mode_b.m4_result.depth_arrays[k], mode_b2.m4_result.depth_arrays[k])
        for k in mode_b.m4_result.depth_arrays
    )
    m11_08_ok = fp1 == fp2 and same_depths and fp1 != ""
    gates["M11-08"] = {
        "name": "Determinism",
        "status": "PASS" if m11_08_ok else "FAIL",
        "evidence": {
            "config_fingerprint_run1": fp1,
            "config_fingerprint_run2": fp2,
            "depth_arrays_bit_identical": same_depths,
            "processing_fingerprint": mode_b.provenance.normalized_dem_fingerprint,
        },
    }

    # ------------------------------------------------------------------ #
    # M11-09 Complete provenance validation
    # ------------------------------------------------------------------ #
    p = mode_b.provenance
    grid_fp = gridspec_fingerprint(mode_b.roi.grid.model_dump(mode="json"))
    pilot_fp = gridspec_fingerprint(pilot.model_dump(mode="json"))
    m11_09_ok = (
        p.raw_dem_sha256 == terrain.raw_dem_sha256
        and p.raw_dem_sha256 != ""
        and p.normalized_dem_fingerprint == terrain.processing_fingerprint
        and p.gridspec_fingerprint == grid_fp
        and p.model_config_fingerprint == fp1
        and p.model_mode == "MODE_B_REAL_TERRAIN_SYNTHETIC_HYDRAULICS"
        and p.extra.get("pilot_gridspec_fingerprint") == pilot_fp
        and len(p.status_labels) > 0
    )
    gates["M11-09"] = {
        "name": "Provenance completeness",
        "status": "PASS" if m11_09_ok else "FAIL",
        "evidence": p.to_dict(),
    }

    # ------------------------------------------------------------------ #
    # M11-10 M1-M9 regression protection
    # ------------------------------------------------------------------ #
    legacy = synthetic_dem()
    m11_10_ok = (
        legacy.shape == (GRID_CELLS, GRID_CELLS)
        and ORIGIN_X == 300000.0 and ORIGIN_Y == 2500000.0
        and pilot.grid_id == "ufns_pilot_grid_real"
        and pilot.bounds != [ORIGIN_X, ORIGIN_Y, ORIGIN_X + GRID_CELLS * 30.0, ORIGIN_Y + GRID_CELLS * 30.0]
        and (REPO_ROOT / "data" / "demo" / "drainage_synthetic_m4.inp").exists()
    )
    gates["M11-10"] = {
        "name": "M1-M9 regression",
        "status": "PASS" if m11_10_ok else "FAIL",
        "evidence": {
            "synthetic_dem_shape": list(legacy.shape),
            "synthetic_origin": [ORIGIN_X, ORIGIN_Y],
            "pilot_grid_id": pilot.grid_id,
            "synthetic_inp_present": (REPO_ROOT / "data" / "demo" / "drainage_synthetic_m4.inp").exists(),
        },
    }

    # ------------------------------------------------------------------ #
    # M11-11 Missing hydraulic attribute rejection / no-fabrication
    # ------------------------------------------------------------------ #
    no_fab = (
        all(e.get("diameter_m") is None or "diameter_m" not in e for e in drain.entities_reprojected)
        and all("manning_n" not in e for e in drain.entities_reprojected)
        and all("capacity_m3s" not in e for e in drain.entities_reprojected)
        and set(contract.missing_attributes) == {
            "diameter_m", "invert_upstream_m", "invert_downstream_m", "manning_n", "capacity_m3s"
        }
    )
    gates["M11-11"] = {
        "name": "No fabricated hydraulic values",
        "status": "PASS" if no_fab else "FAIL",
        "evidence": {
            "missing_attributes": list(contract.missing_attributes),
            "entity_hydraulic_fields_present": sorted(
                {k for e in drain.entities_reprojected for k in e if k.endswith(("_m", "_m3s", "_n"))}
            ),
        },
    }

    # ------------------------------------------------------------------ #
    # M11-12 Real pilot model capability/status reporting
    # ------------------------------------------------------------------ #
    cap = mode_b.capability_state
    m11_12_ok = (
        cap.real_terrain_available is True
        and cap.real_geometry_available is True
        and cap.hydraulic_parameters_present is False
        and cap.hydraulic_network_ready is False
        and "NOT_REAL_TIME" in mode_b.to_dict()["labels"]
        and "NOT_VALIDATED_FORECAST" in mode_b.to_dict()["labels"]
    )
    gates["M11-12"] = {
        "name": "API/dashboard truthfulness",
        "status": "PASS" if m11_12_ok else "FAIL",
        "evidence": {
            "capability_state": cap.to_dict(),
            "result_labels": mode_b.to_dict()["labels"],
            "rainfall_status": mode_b.rainfall_status,
        },
    }

    # ------------------------------------------------------------------ #
    # Aggregate
    # ------------------------------------------------------------------ #
    all_pass = all(g["status"] == "PASS" for g in gates.values())
    gate_matrix = {
        "generated_at": _ts(),
        "overall": "PASS" if all_pass else "FAIL",
        "gates": gates,
        "wall_seconds": round(time.perf_counter() - t0, 2),
    }

    # Write artifacts
    (OUT_DIR / "gate_matrix.json").write_text(json.dumps(gate_matrix, indent=2, sort_keys=True, default=str))
    (OUT_DIR / "mode_b_result.json").write_text(
        json.dumps(mode_b.to_dict(), indent=2, sort_keys=True, default=str)
    )
    # Lightweight inspection artifact for the API (no heavy recompute on requests)
    inspection = _build_inspection(terrain, drain, contract, mode_b, gate_matrix)
    (OUT_DIR / "pilot_inspection.json").write_text(
        json.dumps(inspection, indent=2, sort_keys=True, default=str)
    )

    return gate_matrix


def _first_coord_x(wkt: str) -> float:
    """Extract the first x coordinate from a WKT geometry string."""
    try:
        inner = wkt.split("(", 2)[-1]
        token = inner.strip().split()[0]
        return float(token)
    except Exception:  # noqa: BLE001
        return 0.0


def _build_inspection(
    terrain, drain, contract, mode_b, gate_matrix
) -> dict[str, Any]:
    pilot = authoritative_pilot_grid()
    return {
        "generated_at": _ts(),
        "overall_gate": gate_matrix["overall"],
        "dem_provenance": {
            "raw_dem_path": str(terrain.raw_dem_path),
            "raw_dem_sha256": terrain.raw_dem_sha256,
            "source_crs": terrain.source_crs,
            "modelling_crs": terrain.modelling_crs,
            "normalization_status": terrain.normalization_status,
            "processing_fingerprint": terrain.processing_fingerprint,
            "vertical_reference": terrain.vertical_reference,
            "nodata_cells": terrain.nodata_cells,
            "total_cells": terrain.total_cells,
        },
        "gridspec": pilot.model_dump(mode="json"),
        "gridspec_fingerprint": gridspec_fingerprint(pilot.model_dump(mode="json")),
        "drainage_coverage": {
            "raw_drains_path": str(RAW_DRAINS),
            "source_crs": drain.source_crs,
            "modelling_crs": drain.modelling_crs,
            "embedded_crs": "ABSENT",
            "crs_provenance": drain.crs_source.to_dict(),
            "mapped_count": drain.mapped_count,
            "unresolved_count": drain.unresolved_count,
            "rejected_count": drain.rejected_count,
            "rejection_breakdown": drain.rejection_breakdown,
            "total_source_features": drain.mapped_count + drain.unresolved_count + drain.rejected_count,
        },
        "hydraulic_readiness": contract.to_dict(),
        "model_modes": {
            "MODE_A": "REAL_TERRAIN / REAL_DRAINAGE_GEOMETRY (no hydraulic sim; geometry only)",
            "MODE_B": "REAL_TERRAIN / SYNTHETIC_HYDRAULICS (executable; ran for inspection)",
            "MODE_C": "SYNTHETIC_BASELINE (M1-M9 regression path)",
        },
        "rainfall_status": mode_b.rainfall_status,
        "model_mode_executed": mode_b.model_mode.value,
        "simulation_availability": {
            "mode_b_executed": True,
            "mode_b_run_id": mode_b.m4_result.simulation_run.run_id,
            "hydraulic_network_ready": False,
            "mass_status": mode_b.mass_ledger["status"],
            "mass_relative_residual": mode_b.mass_ledger["relative_residual"],
        },
        "labels": [
            "REAL_PILOT",
            "REAL_TERRAIN",
            "SYNTHETIC_HYDRAULICS",
            "PROVISIONAL",
            "MISSING_HYDRAULICS",
            "NOT_REAL_TIME",
            "NOT_VALIDATED_FORECAST",
        ],
        "not_for_operational_use": True,
    }


def main() -> int:
    print("=" * 70)
    print("UFNS M11 — Real-pilot integration validation")
    print("=" * 70)
    matrix = run_experiments()
    for gid, g in matrix["gates"].items():
        print(f"  [{g['status']}] {gid}: {g['name']}")
    print("-" * 70)
    print(f"OVERALL: M11 = {matrix['overall']}  ({matrix['wall_seconds']}s)")
    print(f"Artifacts written to: {OUT_DIR}")
    return 0 if matrix["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
