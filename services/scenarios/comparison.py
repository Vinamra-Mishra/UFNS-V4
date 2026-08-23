"""M5 cross-scenario comparison (M5 spec §10, §12).

Produces a deterministic comparison artifact with:
  - Per-scenario summary metrics (S1-S4)
  - S3/S4 paired blockage comparison (difference metrics + interpretation)

Comparability is enforced by construction: S3 and S4 share identical
rainfall, DEM, surface parameters, initial state, duration, coupling
timestep, snapshot cadence and model versions; the only difference is
the drainage INP file (C1 diameter 0.30 vs 0.12 m).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from services.scenarios import MODEL_VERSION
from services.scenarios.profiles import D016_STATUS
from services.scenarios.registry import M5_SCENARIOS
from services.scenarios.runner import ScenarioResult


@dataclass
class ScenarioComparison:
    """Deterministic comparison artifact (M5 §10)."""

    generated_at: str
    model_version: str
    scenarios: list[dict[str, Any]]
    s3s4_comparison: dict[str, Any]
    comparability_controls: dict[str, Any]
    labels: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "model_version": self.model_version,
            "d016_status": D016_STATUS,
            "scenarios": self.scenarios,
            "s3s4_blockage_comparison": self.s3s4_comparison,
            "comparability_controls": self.comparability_controls,
            "labels": self.labels,
        }

    def write_json(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True, default=str))
        return path


def _row(r: ScenarioResult) -> dict[str, Any]:
    s = r.scenario
    led = r.m4_result.ledger
    return {
        "scenario_id": s.scenario_id,
        "display_name": s.display_name,
        "rainfall_total_mm": s.rainfall_profile.total_depth_mm,
        "rainfall_status": s.rainfall_profile.review_status.value,
        "drainage_condition": s.drainage_condition.status.value,
        "drainage_fingerprint": s.drainage_condition.inp_fingerprint,
        "peak_depth_m": round(r.peak_depth_m, 6),
        "max_flooded_area_m2": round(r.max_flooded_area_m2, 4),
        "time_to_peak_min": r.time_to_peak_min,
        "max_surcharge_m": round(r.max_drainage_surcharge_m, 6),
        "surface_to_drainage_m3": round(led.S2D_m3, 4),
        "drainage_to_surface_m3": round(led.D2S_m3, 4),
        "outfall_m3": round(led.outfall_m3, 4),
        "surface_storage_change_m3": round(led.S_s1 - led.S_s0, 4),
        "rainfall_input_m3": round(led.rain_m3, 4),
        "combined_mass_residual_m3": round(led.residual_total, 6),
        "relative_residual": round(led.relative_total() or 0.0, 8),
        "mass_gate": r.mass_ledger["gate"],
        "runtime_s": round(r.wall_seconds, 3),
        "acceptance": r.acceptance["overall"],
        "run_fingerprint": r.run_fingerprint,
    }


def _s3s4_comparison(s3: ScenarioResult, s4: ScenarioResult) -> dict[str, Any]:
    """Paired S3 (clean) vs S4 (blocked) comparison (M5 §10).

    Reports observed values only; no required magnitude of change is
    preselected (M5 spec §10: "State observed values only").
    """
    r3, r4 = s3.m4_result, s4.m4_result
    l3, l4 = r3.ledger, r4.ledger

    d_peak = r4.peak_depth_m - r3.peak_depth_m
    d_area = r4.max_flooded_area_m2 - r3.max_flooded_area_m2
    d_surf_storage = (l4.S_s1 - l4.S_s0) - (l3.S_s1 - l3.S_s0)
    d_surcharge = s4.max_drainage_surcharge_m - s3.max_drainage_surcharge_m
    d_capture = l3.S2D_m3 - l4.S2D_m3        # positive = clean captures more
    d_return = l4.D2S_m3 - l3.D2S_m3          # positive = blocked spills more
    d_outfall = l3.outfall_m3 - l4.outfall_m3  # positive = clean outfalls more

    # Physical interpretation (observation-based, not predictive)
    if l4.D2S_m3 > l3.D2S_m3 and l4.outfall_m3 < l3.outfall_m3 and r4.peak_depth_m >= r3.peak_depth_m:
        interp = (
            "Blockage produces a physically consistent response: reduced conduit capacity "
            "(C1 0.30 → 0.12 m) raises ST1 head above vent ground level, the return orifice "
            "activates and spills water onto the vent cell, inlet capture is throttled by "
            "backwater, outfall discharge is reduced, and more water remains on the surface "
            "(higher peak depth and flooded area relative to clean drainage). The observed "
            "differences are hydraulically interpretable as surcharge-driven return flow."
        )
        interp_status = "PHYSICALLY CONSISTENT"
    elif l4.D2S_m3 == 0 and l3.D2S_m3 == 0:
        interp = (
            "Neither scenario surcharged; the extreme rainfall magnitude may not be "
            "sufficient to pressurize the blocked network on this fixture, or the vent "
            "ground mapping requires review (M5 STOP AND REVIEW per spec §12)."
        )
        interp_status = "NO SURCHARGE — REVIEW"
    else:
        interp = (
            "Blockage response differs from expectation; review required. Observed values "
            "are recorded but physical interpretation is unclear."
        )
        interp_status = "REVIEW REQUIRED"

    return {
        "baseline": "S3 (extreme, clean drainage)",
        "scenario": "S4 (extreme, blocked drainage)",
        "only_difference": "C1 conduit diameter (clean 0.30 m vs blocked 0.12 m); all other inputs identical",
        "differences": {
            "delta_peak_depth_m": round(d_peak, 6),
            "delta_flooded_area_m2": round(d_area, 4),
            "delta_surface_storage_change_m3": round(d_surf_storage, 4),
            "delta_max_surcharge_m": round(d_surcharge, 6),
            "capture_reduction_m3": round(d_capture, 4),   # S2D clean minus S2D blocked
            "additional_spill_m3": round(d_return, 4),     # D2S blocked minus D2S clean
            "outfall_reduction_m3": round(d_outfall, 4),   # outfall clean minus outfall blocked
        },
        "observed": {
            "S3_peak_depth_m": round(r3.peak_depth_m, 6),
            "S4_peak_depth_m": round(r4.peak_depth_m, 6),
            "S3_flooded_area_m2": round(r3.max_flooded_area_m2, 4),
            "S4_flooded_area_m2": round(r4.max_flooded_area_m2, 4),
            "S3_S2D_m3": round(l3.S2D_m3, 4),
            "S4_S2D_m3": round(l4.S2D_m3, 4),
            "S3_D2S_m3": round(l3.D2S_m3, 4),
            "S4_D2S_m3": round(l4.D2S_m3, 4),
            "S3_outfall_m3": round(l3.outfall_m3, 4),
            "S4_outfall_m3": round(l4.outfall_m3, 4),
            "S3_max_st1_head_m": round(r3.max_st1_head_m, 6),
            "S4_max_st1_head_m": round(r4.max_st1_head_m, 6),
        },
        "physical_interpretation": interp,
        "interpretation_status": interp_status,
    }


def _comparability_controls(results: dict[str, ScenarioResult]) -> dict[str, Any]:
    """Verify that non-scenario variables are held fixed across the suite."""
    rows = [results[sid] for sid in ("S1", "S2", "S3", "S4")]
    def _tuplify(v):
        return tuple(v) if isinstance(v, list) else v
    fps = {
        "surface_config": sorted({r.scenario.surface_config_fingerprint for r in rows}),
        "dem_shape": sorted({tuple(r.input_manifest["dem_shape"]) for r in rows}),
        "dt_c_s": sorted({r.scenario.coupling_timestep_s for r in rows}),
        "duration_minutes": sorted({r.scenario.duration_minutes for r in rows}),
        "snapshot_interval_minutes": sorted({r.scenario.snapshot_interval_minutes for r in rows}),
        "cell_size_m": sorted({r.input_manifest["cell_size_m"] for r in rows}),
        "crs": sorted({r.input_manifest["crs"] for r in rows}),
        "seed": sorted({r.scenario.seed for r in rows}),
        "manning_n": sorted({r.scenario.manning_n for r in rows}),
        "extent_threshold_m": sorted({r.scenario.extent_threshold_m for r in rows}),
    }
    s3, s4 = results["S3"], results["S4"]
    s3s4_match = {
        "identical_rainfall": (
            s3.scenario.rainfall_profile.profile_id == s4.scenario.rainfall_profile.profile_id
            and s3.scenario.rainfall_profile.fingerprint == s4.scenario.rainfall_profile.fingerprint
        ),
        "identical_duration": s3.scenario.duration_minutes == s4.scenario.duration_minutes,
        "identical_timestep": s3.scenario.coupling_timestep_s == s4.scenario.coupling_timestep_s,
        "identical_snapshot_cadence": s3.scenario.snapshot_interval_minutes == s4.scenario.snapshot_interval_minutes,
        "identical_surface_params": (
            s3.scenario.surface_config_fingerprint == s4.scenario.surface_config_fingerprint
        ),
        "identical_seed": s3.scenario.seed == s4.scenario.seed,
        "identical_extent_threshold": s3.scenario.extent_threshold_m == s4.scenario.extent_threshold_m,
        "only_drainage_differs": (
            s3.scenario.drainage_condition.condition_id == "D_NORMAL"
            and s4.scenario.drainage_condition.condition_id == "D_BLOCKED"
        ),
    }
    all_controlled = all(s3s4_match.values())
    return {
        "suite_wide": {k: v if len(v) > 1 else v[0] for k, v in fps.items()},
        "S3_S4_pairwise_controls": s3s4_match,
        "S3_S4_pairwise_controlled": all_controlled,
    }


def compare(results: dict[str, ScenarioResult]) -> ScenarioComparison:
    """Build the deterministic comparison artifact from executed results."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    rows = [_row(results[sid]) for sid in ("S1", "S2", "S3", "S4")]
    s3s4 = _s3s4_comparison(results["S3"], results["S4"])
    ctrls = _comparability_controls(results)
    return ScenarioComparison(
        generated_at=now,
        model_version=MODEL_VERSION,
        scenarios=rows,
        s3s4_comparison=s3s4,
        comparability_controls=ctrls,
        labels=["SYNTHETIC", "SIMULATED", "PROVISIONAL"],
    )
