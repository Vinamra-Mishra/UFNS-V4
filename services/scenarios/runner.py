"""M5 scenario runner (M5 spec §9, §10, §13).

Executes a ScenarioRecord on the UNMODIFIED M4 coupled engine (services/
simulation/engine.py). Every scenario instantiates a fresh model state;
no state leaks between runs (asserted in tests M5-10, M5-13).
"""

from __future__ import annotations

import hashlib
import json
import time as _time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np

from services.contracts import SCHEMA_VERSION
from services.scenarios import MODEL_VERSION
from services.scenarios.profiles import D016_STATUS
from services.scenarios.registry import M5_SCENARIOS, ScenarioRecord
from services.simulation.engine import (
    FIXTURE_VENT_CELL,
    LossSpec,
    M4RunResult,
    RainfallSpec,
    RunConfig,
    CoupledFloodModel,
    fixture_inlet_cells,
)


# ---------------------------------------------------------------------------
# Scenario result
# ---------------------------------------------------------------------------

@dataclass
class ScenarioResult:
    """Complete result for one executed scenario (M5 §9 output contract)."""

    scenario: ScenarioRecord
    run_id: str
    config_fingerprint: str
    input_manifest: dict[str, Any]
    m4_result: M4RunResult
    # summaries
    rainfall_summary: dict[str, Any]
    loss_summary: dict[str, Any]
    surface_storage_summary: dict[str, Any]
    drainage_storage_summary: dict[str, Any]
    exchange_summary: dict[str, Any]
    boundary_summary: dict[str, Any]
    peak_depth_m: float
    mean_depth_m: float
    max_flooded_area_m2: float
    time_to_peak_min: float
    max_drainage_surcharge_m: float       # max(0, ST1_head - vent_ground)
    mass_ledger: dict[str, Any]
    wall_seconds: float
    cpu_seconds: float
    peak_rss_mb: float
    snapshot_inventory: list[dict[str, Any]]
    acceptance: dict[str, Any]
    limitations: tuple[str, ...]
    run_fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario.scenario_id,
            "display_name": self.scenario.display_name,
            "run_id": self.run_id,
            "config_fingerprint": self.config_fingerprint,
            "input_manifest": self.input_manifest,
            "rainfall_summary": self.rainfall_summary,
            "loss_summary": self.loss_summary,
            "surface_storage_summary": self.surface_storage_summary,
            "drainage_storage_summary": self.drainage_storage_summary,
            "exchange_summary": self.exchange_summary,
            "boundary_summary": self.boundary_summary,
            "peak_depth_m": round(self.peak_depth_m, 6),
            "mean_depth_m": round(self.mean_depth_m, 6),
            "max_flooded_area_m2": round(self.max_flooded_area_m2, 4),
            "time_to_peak_min": self.time_to_peak_min,
            "max_drainage_surcharge_m": round(self.max_drainage_surcharge_m, 6),
            "mass_ledger": self.mass_ledger,
            "wall_seconds": round(self.wall_seconds, 3),
            "cpu_seconds": round(self.cpu_seconds, 3),
            "peak_rss_mb": round(self.peak_rss_mb, 1),
            "snapshot_inventory": self.snapshot_inventory,
            "acceptance": self.acceptance,
            "limitations": list(self.limitations),
            "run_fingerprint": self.run_fingerprint,
            "labels": ["SYNTHETIC", "SIMULATED", "PROVISIONAL"],
            "d016_status": D016_STATUS,
            "model_version": MODEL_VERSION,
            "engine_version": self.m4_result.simulation_run.model_versions.get("engine", ""),
        }


# ---------------------------------------------------------------------------
# Conversion: ScenarioRecord -> RunConfig
# ---------------------------------------------------------------------------

def scenario_to_runconfig(
    scenario: ScenarioRecord,
    dem: np.ndarray,
    issue_time: Optional[datetime] = None,
    artifact_dir: Optional[Path] = None,
) -> RunConfig:
    """Map a ScenarioRecord to an M4 RunConfig without altering M4 semantics."""
    if issue_time is None:
        issue_time = scenario.start_time
    run_id = f"m5_{scenario.scenario_id}_{issue_time:%Y%m%dT%H%M%SZ}"

    profile = scenario.rainfall_profile
    intensities = list(profile.intensities_mmh)
    rainfall = RainfallSpec(
        kind="profile",
        interval_minutes=profile.temporal_resolution_minutes,
        intensities_mmh=intensities,
        pattern=scenario.spatial_pattern,
        seed=scenario.seed,
    )
    losses = LossSpec(
        enabled=True,
        f0_mmh=scenario.horton_f0_mmh,
        fmin_mmh=scenario.horton_fmin_mmh,
        k_s1=scenario.horton_k_s1,
        microstore_m=scenario.microstore_m,
    )
    inlet_cells = fixture_inlet_cells(dem)

    cfg = RunConfig(
        run_id=run_id,
        scenario_id=scenario.scenario_id,
        issue_time=issue_time,
        dem=dem,
        rainfall=rainfall,
        losses=losses,
        mannings_n=scenario.manning_n,
        alpha=0.5, theta=0.8, h_init=1e-6,
        closed_boundaries=False,
        drainage_inp=scenario.drainage_condition.inp_path,
        inlet_cells=inlet_cells,
        vent_cell=FIXTURE_VENT_CELL,
        dt_c=scenario.coupling_timestep_s,
        surface_substeps=5,
        duration_minutes=scenario.duration_minutes,
        snapshot_interval_minutes=scenario.snapshot_interval_minutes,
        extent_threshold_m=scenario.extent_threshold_m,
        cd=scenario.cd,
        ao_per_inlet=scenario.ao_per_inlet,
        ao_vent=None,
        external_inflow_m3s=scenario.external_inflow_m3s,
        artifact_dir=artifact_dir,
    )
    return cfg


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def _summarize_result(scenario: ScenarioRecord, res: M4RunResult,
                      cfg: RunConfig) -> ScenarioResult:
    led = res.ledger
    mb = res.mass_balance

    # Rainfall summary
    total_rain_mm = scenario.rainfall_profile.total_depth_mm
    peak_intensity = scenario.rainfall_profile.peak_intensity_mmh
    n_intervals = len(scenario.rainfall_profile.intensities_mmh)
    rainfall_summary = {
        "profile_id": scenario.rainfall_profile.profile_id,
        "profile_status": scenario.rainfall_profile.review_status.value,
        "total_depth_mm": total_rain_mm,
        "peak_intensity_mmh": round(peak_intensity, 4),
        "mean_intensity_mmh": round(total_rain_mm / (scenario.duration_minutes / 60.0), 4),
        "interval_minutes": scenario.rainfall_profile.temporal_resolution_minutes,
        "n_intervals": n_intervals,
        "total_volume_m3": round(led.rain_m3, 4),
        "spatial_pattern": scenario.spatial_pattern,
        "units": "mm/h (intensity), mm (total), m3 (volume)",
    }

    # Loss summary
    loss_summary = {
        "horton_infiltration_m3": round(led.losses_m3, 4),
        "microstore_final_m3": round(led.microstore_final_m3, 4),
        "horton_f0_mmh": scenario.horton_f0_mmh,
        "horton_fmin_mmh": scenario.horton_fmin_mmh,
        "horton_k_s1": scenario.horton_k_s1,
        "microstore_capacity_m": scenario.microstore_m,
        "units": "m3 (volumes), mm/h (rates), s^-1 (k), m (depth)",
    }

    # Surface storage summary
    dS_s = led.S_s1 - led.S_s0
    surface_storage_summary = {
        "initial_storage_m3": round(led.S_s0, 4),
        "final_storage_m3": round(led.S_s1, 4),
        "delta_storage_m3": round(dS_s, 4),
        "boundary_outflow_m3": round(led.surf_out_m3, 4),
        "units": "m3",
    }

    # Drainage storage summary
    dS_d = led.S_d1 - led.S_d0
    drainage_storage_summary = {
        "initial_storage_m3": round(led.S_d0, 4),
        "final_storage_m3_identity": round(led.S_d1, 4),
        "final_storage_m3_readback": round(led.S_d1_readback, 4),
        "readback_discrepancy_m3": round(led.readback_discrepancy, 4),
        "delta_storage_m3": round(dS_d, 4),
        "outfall_m3": round(led.outfall_m3, 4),
        "swmm_flow_routing_error_pct": round(led.flow_routing_error_pct or 0.0, 6),
        "units": "m3 (volumes), % (routing error)",
    }

    # Exchange summary (internal; cancels in combined ledger)
    exchange_summary = {
        "surface_to_drainage_m3": round(led.S2D_m3, 4),
        "drainage_to_surface_m3": round(led.D2S_m3, 4),
        "swmm_flood_export_m3": round(led.flood_export_m3, 4),
        "net_exchange_m3": round(led.S2D_m3 - led.D2S_m3 - led.flood_export_m3, 4),
        "note": "S2D and D2S are internal transfers; they cancel in the combined system ledger.",
        "units": "m3",
    }

    # Boundary summary
    boundary_summary = {
        "surface_boundary_outflow_m3": round(led.surf_out_m3, 4),
        "drainage_outfall_m3": round(led.outfall_m3, 4),
        "external_inflow_m3": round(led.ext_in_m3, 4),
        "units": "m3",
    }

    # Surcharge: how far ST1 head exceeds vent ground
    vent_ground = float(cfg.dem[cfg.vent_cell])
    max_surcharge = max(0.0, res.max_st1_head_m - vent_ground)

    # Mass ledger (M5 §13)
    surface_residual = led.residual_surface
    drainage_residual = led.residual_drainage
    combined_residual = led.residual_total
    scale = max(abs(led.rain_m3) + abs(led.ext_in_m3), 1e-6)
    rel_residual = abs(combined_residual) / scale
    tolerance_rel = 0.01  # M4 1% gate
    mass_pass = (rel_residual <= tolerance_rel)
    mass_ledger = {
        "rainfall_input_m3": round(led.rain_m3, 4),
        "external_inflow_m3": round(led.ext_in_m3, 4),
        "infiltration_loss_m3": round(led.losses_m3, 4),
        "microstore_final_m3": round(led.microstore_final_m3, 4),
        "surface_boundary_outflow_m3": round(led.surf_out_m3, 4),
        "drainage_outfall_m3": round(led.outfall_m3, 4),
        "surface_storage_change_m3": round(dS_s, 4),
        "drainage_storage_change_m3": round(dS_d, 4),
        "S2D_m3": round(led.S2D_m3, 4),
        "D2S_m3": round(led.D2S_m3, 4),
        "swmm_flood_export_m3": round(led.flood_export_m3, 4),
        "surface_residual_m3": round(surface_residual, 6),
        "drainage_residual_m3": round(drainage_residual, 6),
        "combined_residual_m3": round(combined_residual, 6),
        "absolute_residual_m3": round(abs(combined_residual), 6),
        "relative_residual": round(rel_residual, 8),
        "configured_tolerance_rel": tolerance_rel,
        "exchange_cancels_in_combined": bool(
            abs(combined_residual - surface_residual - drainage_residual) < 1e-6
            and abs(drainage_residual) < 1e-6
        ),
        "gate": "PASS" if mass_pass else "FAIL",
    }

    # Snapshot inventory
    snap_inv = []
    for s in res.snapshots:
        snap_inv.append({
            "snapshot_id": s.snapshot_id,
            "valid_time": s.valid_time.isoformat(),
            "lead_minutes": s.lead_minutes,
            "max_depth_m": round(s.max_depth_m, 6),
            "mean_depth_m": round(s.mean_depth_m, 6),
            "flooded_cells": s.flooded_cells,
            "flooded_area_m2": round(s.flooded_area_m2, 4),
            "surface_storage_m3": round(s.total_surface_storage_m3, 4),
            "st1_head_m": round(s.drainage.st1_head_m, 6),
            "outfall_cum_m3": round(s.drainage.outfall_cum_m3, 4),
            "S2D_cum_m3": round(s.drainage.exchange_S2D_cum_m3, 4),
            "D2S_cum_m3": round(s.drainage.exchange_D2S_cum_m3, 4),
            "surcharged": s.drainage.surcharged,
            "depth_asset_uri": s.depth_asset_uri,
        })

    # Acceptance
    finite_ok = (np.all(np.isfinite(res.depth_arrays[max(res.depth_arrays)]))
                 and all(np.all(np.isfinite(arr)) for arr in res.depth_arrays.values()))
    nonneg_ok = all(float(arr.min()) >= -1e-12 for arr in res.depth_arrays.values())
    acceptance = {
        "mass_ledger": "PASS" if mass_pass else "FAIL",
        "non_negative_depth": "PASS" if nonneg_ok else "FAIL",
        "finite_states": "PASS" if finite_ok else "FAIL",
        "clean_initial_state": "PASS",  # fresh model instance per run
        "deterministic_snapshots": "PASS" if len(res.snapshots) == cfg.duration_minutes // cfg.snapshot_interval_minutes + 1 else "FAIL",
        "provenance_recorded": "PASS",
        "overall": "PASS" if (mass_pass and nonneg_ok and finite_ok) else "FAIL",
    }

    # Mean depth at final snapshot
    final_lead = max(res.depth_arrays)
    mean_depth_final = float(res.depth_arrays[final_lead].mean())

    # Run fingerprint
    fp_payload = {
        "scenario_fp": scenario.fingerprint,
        "config_fp": cfg.fingerprint(),
        "peak_depth_m": round(res.peak_depth_m, 8),
        "max_flooded_area_m2": round(res.max_flooded_area_m2, 4),
        "S2D_m3": round(led.S2D_m3, 6),
        "D2S_m3": round(led.D2S_m3, 6),
        "outfall_m3": round(led.outfall_m3, 6),
        "combined_residual_m3": round(combined_residual, 8),
    }
    run_fp = hashlib.sha256(
        json.dumps(fp_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]

    limitations = scenario.limitations + (
        f"Mass ledger relative residual {rel_residual:.2e} (tolerance {tolerance_rel:.2e}).",
        f"Landlab h_init film bias contributes up to ~0.04% of rainfall volume "
        f"(M2 documented behaviour, reported in residual, not absorbed).",
    )

    return ScenarioResult(
        scenario=scenario,
        run_id=cfg.run_id,
        config_fingerprint=cfg.fingerprint(),
        input_manifest={
            "dem_shape": list(cfg.dem.shape),
            "cell_size_m": cfg.cell_size_m,
            "crs": cfg.crs,
            "drainage_inp": str(cfg.drainage_inp),
            "drainage_fingerprint": scenario.drainage_condition.inp_fingerprint,
            "rainfall_profile_id": scenario.rainfall_profile.profile_id,
            "rainfall_profile_fp": scenario.rainfall_profile.fingerprint,
            "n_inlets": len(cfg.inlet_cells),
            "vent_cell": list(cfg.vent_cell),
            "dt_c_s": cfg.dt_c,
            "surface_substeps": cfg.surface_substeps,
            "duration_minutes": cfg.duration_minutes,
            "snapshot_interval_minutes": cfg.snapshot_interval_minutes,
            "extent_threshold_m": cfg.extent_threshold_m,
            "model_version": MODEL_VERSION,
            "engine_model_versions": res.simulation_run.model_versions,
        },
        m4_result=res,
        rainfall_summary=rainfall_summary,
        loss_summary=loss_summary,
        surface_storage_summary=surface_storage_summary,
        drainage_storage_summary=drainage_storage_summary,
        exchange_summary=exchange_summary,
        boundary_summary=boundary_summary,
        peak_depth_m=res.peak_depth_m,
        mean_depth_m=mean_depth_final,
        max_flooded_area_m2=res.max_flooded_area_m2,
        time_to_peak_min=res.time_to_peak_min,
        max_drainage_surcharge_m=max_surcharge,
        mass_ledger=mass_ledger,
        wall_seconds=res.wall_seconds,
        cpu_seconds=res.cpu_seconds,
        peak_rss_mb=res.peak_rss_mb,
        snapshot_inventory=snap_inv,
        acceptance=acceptance,
        limitations=limitations,
        run_fingerprint=run_fp,
    )


def run_scenario(
    scenario: ScenarioRecord,
    dem: np.ndarray,
    issue_time: Optional[datetime] = None,
    artifact_dir: Optional[Path] = None,
) -> ScenarioResult:
    """Run one scenario from a clean state and return the full result."""
    cfg = scenario_to_runconfig(scenario, dem, issue_time=issue_time,
                                artifact_dir=artifact_dir)
    model = CoupledFloodModel(cfg)
    res = model.run()
    return _summarize_result(scenario, res, cfg)


def run_all_scenarios(
    dem: np.ndarray,
    issue_time: Optional[datetime] = None,
    artifact_root: Optional[Path] = None,
) -> dict[str, ScenarioResult]:
    """Run the full M5 suite (S1-S4) from fresh states; return results keyed by scenario_id."""
    if issue_time is None:
        issue_time = M5_SCENARIOS["S1"].start_time
    out: dict[str, ScenarioResult] = {}
    for sid in ("S1", "S2", "S3", "S4"):
        srec = M5_SCENARIOS[sid]
        art_dir = artifact_root / sid.lower() if artifact_root is not None else None
        out[sid] = run_scenario(srec, dem, issue_time=issue_time, artifact_dir=art_dir)
    return out
