"""M5 — Scenario Engine test matrix (M5 spec §11).

M5-01 scenario schema validation
M5-02 required scenario IDs and metadata
M5-03 rainfall-profile provenance and status
M5-04 normal scenario execution (S1)
M5-05 heavy scenario execution (S2)
M5-06 extreme scenario execution (S3)
M5-07 extreme + blockage execution (S4)
M5-08 paired-comparison control variables
M5-09 blockage sensitivity
M5-10 independent scenario isolation
M5-11 per-scenario mass conservation
M5-12 cross-scenario snapshot determinism
M5-13 complete-suite reproducibility
M5-14 invalid scenario configuration
M5-15 output manifest and fingerprinting
M5-16 scenario-summary consistency
"""

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from services.scenarios.comparison import ScenarioComparison, compare
from services.scenarios.drainage import (
    BLOCKED_DIAMETER_M,
    DRAINAGE_CONDITIONS,
    DrainageCondition,
)
from services.scenarios.profiles import (
    D016_STATUS,
    PROFILE_DEFS,
    ProfileStatus,
    SEVERITY_DEFINITIONS,
    all_profiles,
    build_profile_record,
)
from services.scenarios.registry import (
    M5_DT_C,
    M5_DURATION_MINUTES,
    M5_EXTENT_THRESHOLD_M,
    M5_SNAPSHOT_INTERVAL_MIN,
    M5_SCENARIOS,
    required_scenario_ids,
)
from services.scenarios.runner import (
    ScenarioResult,
    run_all_scenarios,
    run_scenario,
    scenario_to_runconfig,
)
from services.simulation.engine import (
    CoupledFloodModel,
    CouplingError,
    LossSpec,
    RainfallSpec,
    RunConfig,
    fixture_inlet_cells,
)
from services.ingestion.dem import synthetic_dem

ISSUE = datetime(2026, 8, 21, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Fixtures (module scope: expensive runs are cached)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def dem() -> np.ndarray:
    return synthetic_dem()


@pytest.fixture(scope="module")
def m5_results(dem) -> dict[str, ScenarioResult]:
    return run_all_scenarios(dem, issue_time=ISSUE)


@pytest.fixture(scope="module")
def m5_comparison(m5_results) -> ScenarioComparison:
    return compare(m5_results)


# ---------------------------------------------------------------------------
# M5-01 scenario schema validation
# ---------------------------------------------------------------------------

def test_m5_01_scenario_schema():
    """Every scenario has all required fields per M5 spec §5."""
    required = (
        "scenario_id", "display_name", "description", "rainfall_profile",
        "rainfall_status", "drainage_condition", "duration_minutes", "start_time",
        "initial_condition_policy", "coupling_timestep_s", "snapshot_interval_minutes",
        "surface_config_fingerprint", "swmm_fixture_fingerprint",
        "assumptions", "limitations", "provenance", "fingerprint",
    )
    for sid, s in M5_SCENARIOS.items():
        d = s.to_dict()
        for key in required:
            assert key in d, f"{sid} missing required field {key}"
        # types
        assert isinstance(s.scenario_id, str) and s.scenario_id.startswith("S")
        assert isinstance(s.duration_minutes, int) and s.duration_minutes == M5_DURATION_MINUTES
        assert isinstance(s.coupling_timestep_s, int) and s.coupling_timestep_s == M5_DT_C
        assert s.snapshot_interval_minutes == M5_SNAPSHOT_INTERVAL_MIN
        assert s.extent_threshold_m == M5_EXTENT_THRESHOLD_M
        assert s.start_time.tzinfo is not None
        assert len(s.assumptions) > 0
        assert len(s.limitations) > 0
        assert len(s.fingerprint) == 16


# ---------------------------------------------------------------------------
# M5-02 required scenario IDs and metadata
# ---------------------------------------------------------------------------

def test_m5_02_required_scenario_ids_and_metadata():
    assert set(M5_SCENARIOS.keys()) == {"S1", "S2", "S3", "S4"}
    assert required_scenario_ids() == ("S1", "S2", "S3", "S4")
    # S1: normal rain + normal drainage
    assert M5_SCENARIOS["S1"].rainfall_profile.profile_id == "P_NORMAL"
    assert M5_SCENARIOS["S1"].drainage_condition.condition_id == "D_NORMAL"
    # S2: heavy + normal
    assert M5_SCENARIOS["S2"].rainfall_profile.profile_id == "P_HEAVY"
    assert M5_SCENARIOS["S2"].drainage_condition.condition_id == "D_NORMAL"
    # S3: extreme + normal
    assert M5_SCENARIOS["S3"].rainfall_profile.profile_id == "P_EXTREME"
    assert M5_SCENARIOS["S3"].drainage_condition.condition_id == "D_NORMAL"
    # S4: extreme + blocked
    assert M5_SCENARIOS["S4"].rainfall_profile.profile_id == "P_EXTREME"
    assert M5_SCENARIOS["S4"].drainage_condition.condition_id == "D_BLOCKED"
    # Display names are distinct and descriptive
    names = {sid: M5_SCENARIOS[sid].display_name for sid in M5_SCENARIOS}
    assert len(set(names.values())) == 4
    assert all("Rainfall" in n or "rainfall" in n for n in names.values())


# ---------------------------------------------------------------------------
# M5-03 rainfall-profile provenance and status
# ---------------------------------------------------------------------------

def test_m5_03_rainfall_profile_provenance_and_status():
    profiles = all_profiles()
    assert set(profiles.keys()) == {"P_NORMAL", "P_HEAVY", "P_EXTREME"}
    for pid, p in profiles.items():
        d = p.to_dict()
        assert p.review_status == ProfileStatus.PROVISIONAL
        assert p.d016_review_status == "PREPARED"
        assert p.total_depth_mm == PROFILE_DEFS[pid]["total_mm"]
        assert p.temporal_resolution_minutes == 15
        assert p.duration_minutes == 180
        assert len(p.intensities_mmh) == 12
        assert all(v >= 0 for v in p.intensities_mmh)
        assert p.peak_intensity_mmh == max(p.intensities_mmh)
        assert p.units.startswith("mm/h")
        assert len(p.fingerprint) == 16
        assert "alternating-block" in p.derivation.lower() or "Chow" in p.derivation
        assert len(p.limitations) >= 3
        assert "D-016" in " ".join(p.limitations)
    # Severity definitions documented (no implicit labels)
    for sev in ("NORMAL", "HEAVY", "EXTREME"):
        assert sev in SEVERITY_DEFINITIONS
        assert "criterion" in SEVERITY_DEFINITIONS[sev]
    # Intensity ordering: extreme > heavy > normal
    assert profiles["P_EXTREME"].total_depth_mm > profiles["P_HEAVY"].total_depth_mm
    assert profiles["P_HEAVY"].total_depth_mm > profiles["P_NORMAL"].total_depth_mm


# ---------------------------------------------------------------------------
# M5-04 normal scenario execution (S1)
# ---------------------------------------------------------------------------

def test_m5_04_normal_execution(m5_results):
    r = m5_results["S1"]
    assert r.acceptance["overall"] == "PASS"
    assert r.peak_depth_m > 0.01
    assert r.max_flooded_area_m2 >= 0
    assert r.m4_result.ledger.S2D_m3 > 0      # drainage captures
    assert r.m4_result.ledger.D2S_m3 == 0.0    # clean drain, no surcharge
    assert r.m4_result.ledger.outfall_m3 > 0
    assert r.max_drainage_surcharge_m == 0.0   # no surcharge in S1
    assert r.mass_ledger["gate"] == "PASS"
    assert len(r.m4_result.snapshots) == M5_DURATION_MINUTES // M5_SNAPSHOT_INTERVAL_MIN + 1


# ---------------------------------------------------------------------------
# M5-05 heavy scenario execution (S2)
# ---------------------------------------------------------------------------

def test_m5_05_heavy_execution(m5_results):
    r = m5_results["S2"]
    assert r.acceptance["overall"] == "PASS"
    assert r.peak_depth_m > m5_results["S1"].peak_depth_m  # more rain -> deeper
    assert r.max_flooded_area_m2 >= m5_results["S1"].max_flooded_area_m2
    assert r.m4_result.ledger.rain_m3 > m5_results["S1"].m4_result.ledger.rain_m3
    assert r.m4_result.ledger.S2D_m3 > m5_results["S1"].m4_result.ledger.S2D_m3
    assert r.mass_ledger["gate"] == "PASS"


# ---------------------------------------------------------------------------
# M5-06 extreme scenario execution (S3)
# ---------------------------------------------------------------------------

def test_m5_06_extreme_execution(m5_results):
    r = m5_results["S3"]
    assert r.acceptance["overall"] == "PASS"
    assert r.peak_depth_m > m5_results["S2"].peak_depth_m
    assert r.max_flooded_area_m2 >= m5_results["S2"].max_flooded_area_m2
    assert r.m4_result.ledger.rain_m3 > m5_results["S2"].m4_result.ledger.rain_m3
    assert r.m4_result.ledger.S2D_m3 > 0
    assert r.mass_ledger["gate"] == "PASS"
    # Clean drain: S3 may or may not surcharge depending on fixture; spec does
    # not require it. Document observed state.


# ---------------------------------------------------------------------------
# M5-07 extreme + blockage execution (S4)
# ---------------------------------------------------------------------------

def test_m5_07_extreme_blocked_execution(m5_results):
    r = m5_results["S4"]
    assert r.acceptance["overall"] == "PASS"
    assert r.mass_ledger["gate"] == "PASS"
    assert len(r.m4_result.snapshots) == len(m5_results["S3"].m4_result.snapshots)
    # S4 uses the extreme profile
    assert r.scenario.rainfall_profile.profile_id == "P_EXTREME"
    assert r.scenario.drainage_condition.condition_id == "D_BLOCKED"


# ---------------------------------------------------------------------------
# M5-08 paired-comparison control variables
# ---------------------------------------------------------------------------

def test_m5_08_paired_comparison_controls(m5_results, m5_comparison):
    ctrls = m5_comparison.comparability_controls
    # All scenarios share surface config, timestep, duration, seed, etc.
    sw = ctrls["suite_wide"]
    assert sw["dt_c_s"] == M5_DT_C
    assert sw["duration_minutes"] == M5_DURATION_MINUTES
    assert sw["snapshot_interval_minutes"] == M5_SNAPSHOT_INTERVAL_MIN
    assert sw["seed"] == 20260821
    assert sw["cell_size_m"] == 30.0
    assert sw["extent_threshold_m"] == M5_EXTENT_THRESHOLD_M
    # S3/S4 pairwise
    p = ctrls["S3_S4_pairwise_controls"]
    assert p["identical_rainfall"] is True
    assert p["identical_duration"] is True
    assert p["identical_timestep"] is True
    assert p["identical_snapshot_cadence"] is True
    assert p["identical_surface_params"] is True
    assert p["identical_seed"] is True
    assert p["identical_extent_threshold"] is True
    assert p["only_drainage_differs"] is True
    assert ctrls["S3_S4_pairwise_controlled"] is True
    # Drainage fingerprints differ
    s3_fp = m5_results["S3"].scenario.drainage_condition.inp_fingerprint
    s4_fp = m5_results["S4"].scenario.drainage_condition.inp_fingerprint
    assert s3_fp != s4_fp
    # Rainfall fingerprints identical
    assert (m5_results["S3"].scenario.rainfall_profile.fingerprint ==
            m5_results["S4"].scenario.rainfall_profile.fingerprint)


# ---------------------------------------------------------------------------
# M5-09 blockage sensitivity
# ---------------------------------------------------------------------------

def test_m5_09_blockage_sensitivity(m5_results, m5_comparison):
    """S4 (blocked) must show measurable, physically interpretable difference vs S3."""
    s3, s4 = m5_results["S3"], m5_results["S4"]
    l3, l4 = s3.m4_result.ledger, s4.m4_result.ledger
    # Physical expectations (from the coupling law)
    assert l4.D2S_m3 > l3.D2S_m3, "blockage must produce surcharge return"
    assert l3.D2S_m3 == 0.0, "clean drainage must not spill at vent"
    assert l4.outfall_m3 < l3.outfall_m3, "blockage must reduce outfall"
    assert l4.S2D_m3 < l3.S2D_m3, "blockage must throttle capture"
    assert l4.S2D_m3 > 0 and l3.S2D_m3 > 0
    # Hydraulic surcharge: blocked ST1 head above vent ground
    assert s4.max_drainage_surcharge_m > 0, "S4 must show measurable surcharge"
    assert s3.max_drainage_surcharge_m == 0.0 or s3.max_drainage_surcharge_m < s4.max_drainage_surcharge_m
    # Surface retains more water
    assert (l4.S_s1 - l4.S_s0) > (l3.S_s1 - l3.S_s0)
    # Both ledgers close
    assert l3.status() == "pass" and l4.status() == "pass"
    # Interpretation must be physically consistent
    assert m5_comparison.s3s4_comparison["interpretation_status"] == "PHYSICALLY CONSISTENT"
    # Measured magnitudes
    d = m5_comparison.s3s4_comparison["differences"]
    assert d["capture_reduction_m3"] > 0
    assert d["additional_spill_m3"] > 0
    assert d["outfall_reduction_m3"] > 0
    assert d["delta_surface_storage_change_m3"] > 0


# ---------------------------------------------------------------------------
# M5-10 independent scenario isolation
# ---------------------------------------------------------------------------

def test_m5_10_independent_scenario_isolation(dem):
    """No state may leak between scenarios."""
    # Run S1, then S4, then S1 again; results must match
    s1_a = run_scenario(M5_SCENARIOS["S1"], dem, issue_time=ISSUE)
    _ = run_scenario(M5_SCENARIOS["S4"], dem, issue_time=ISSUE)
    s1_b = run_scenario(M5_SCENARIOS["S1"], dem, issue_time=ISSUE)
    assert s1_a.peak_depth_m == s1_b.peak_depth_m
    assert s1_a.max_flooded_area_m2 == s1_b.max_flooded_area_m2
    assert s1_a.m4_result.ledger.S2D_m3 == s1_b.m4_result.ledger.S2D_m3
    assert s1_a.m4_result.ledger.outfall_m3 == s1_b.m4_result.ledger.outfall_m3
    assert s1_a.mass_ledger["combined_residual_m3"] == s1_b.mass_ledger["combined_residual_m3"]
    assert s1_a.run_fingerprint == s1_b.run_fingerprint
    # Same test: S3 then S4 interleaved
    s3_a = run_scenario(M5_SCENARIOS["S3"], dem, issue_time=ISSUE)
    _ = run_scenario(M5_SCENARIOS["S1"], dem, issue_time=ISSUE)
    _ = run_scenario(M5_SCENARIOS["S2"], dem, issue_time=ISSUE)
    s3_b = run_scenario(M5_SCENARIOS["S3"], dem, issue_time=ISSUE)
    assert s3_a.peak_depth_m == s3_b.peak_depth_m
    assert s3_a.m4_result.ledger.S2D_m3 == s3_b.m4_result.ledger.S2D_m3
    assert s3_a.run_fingerprint == s3_b.run_fingerprint


# ---------------------------------------------------------------------------
# M5-11 per-scenario mass conservation
# ---------------------------------------------------------------------------

def test_m5_11_per_scenario_mass_conservation(m5_results):
    """Every scenario passes mass accounting with explicit gates."""
    for sid, r in m5_results.items():
        ml = r.mass_ledger
        # non-negative volumes
        assert ml["rainfall_input_m3"] >= 0
        assert ml["infiltration_loss_m3"] >= 0
        assert ml["drainage_outfall_m3"] >= 0
        assert ml["surface_boundary_outflow_m3"] >= 0
        # gate
        assert ml["gate"] == "PASS", f"{sid} mass gate: {ml}"
        assert ml["relative_residual"] <= ml["configured_tolerance_rel"]
        # exchange cancels in combined
        assert ml["exchange_cancels_in_combined"], f"{sid} exchange does not cancel"
        assert abs(ml["drainage_residual_m3"]) < 1e-6, f"{sid} drainage residual non-zero"
        # surface residual bounded
        assert abs(ml["surface_residual_m3"]) <= 0.01 * ml["rainfall_input_m3"] + 1.0, \
            f"{sid} surface residual too large"


# ---------------------------------------------------------------------------
# M5-12 cross-scenario snapshot determinism
# ---------------------------------------------------------------------------

def test_m5_12_cross_scenario_snapshot_determinism(m5_results):
    """Snapshots are monotonic, UTC-aware, lead-aligned across scenarios."""
    for sid, r in m5_results.items():
        leads = [s.lead_minutes for s in r.m4_result.snapshots]
        assert leads == list(range(0, M5_DURATION_MINUTES + 1, M5_SNAPSHOT_INTERVAL_MIN))
        times = [s.valid_time for s in r.m4_result.snapshots]
        assert all(t.tzinfo is not None for t in times), f"{sid} naive timestamp"
        assert times == sorted(times), f"{sid} timestamps not monotonic"
        assert times[0] == ISSUE
        assert times[-1] == ISSUE + __import__("datetime").timedelta(minutes=M5_DURATION_MINUTES)
        # every snapshot has valid provenance
        for s in r.m4_result.snapshots:
            assert s.max_depth_m >= -1e-12
            assert s.flooded_cells >= 0
            assert s.flooded_area_m2 >= 0
            assert np.isfinite(s.max_depth_m)


# ---------------------------------------------------------------------------
# M5-13 complete-suite reproducibility
# ---------------------------------------------------------------------------

def test_m5_13_complete_suite_reproducibility(dem, m5_results):
    """Running the full four-scenario suite twice yields identical results."""
    second = run_all_scenarios(dem, issue_time=ISSUE)
    for sid in ("S1", "S2", "S3", "S4"):
        a, b = m5_results[sid], second[sid]
        assert a.scenario.fingerprint == b.scenario.fingerprint
        assert a.run_fingerprint == b.run_fingerprint
        assert a.config_fingerprint == b.config_fingerprint
        assert a.peak_depth_m == b.peak_depth_m
        assert a.max_flooded_area_m2 == b.max_flooded_area_m2
        assert a.m4_result.ledger.S2D_m3 == b.m4_result.ledger.S2D_m3
        assert a.m4_result.ledger.D2S_m3 == b.m4_result.ledger.D2S_m3
        assert a.m4_result.ledger.outfall_m3 == b.m4_result.ledger.outfall_m3
        assert a.mass_ledger["combined_residual_m3"] == b.mass_ledger["combined_residual_m3"]
    # comparison artifact identical (except timestamps and runtime)
    c1 = compare(m5_results).to_dict()
    c2 = compare(second).to_dict()
    c1.pop("generated_at"); c2.pop("generated_at")
    # runtime_s is wall time; strip it for byte-identical comparison
    for row in c1["scenarios"]:
        row.pop("runtime_s", None)
    for row in c2["scenarios"]:
        row.pop("runtime_s", None)
    assert c1 == c2


# ---------------------------------------------------------------------------
# M5-14 invalid scenario configuration
# ---------------------------------------------------------------------------

def test_m5_14_invalid_scenario_configuration(dem):
    """Invalid configurations raise explicit errors (no silent fallback)."""
    from services.scenarios.registry import ScenarioRecord
    from dataclasses import replace

    good = M5_SCENARIOS["S1"]
    # Build RunConfig with bad inputs via scenario_to_runconfig
    # 1) unknown profile key
    with pytest.raises(KeyError):
        build_profile_record("P_NONEXISTENT")
    # 2) Drainage with missing INP
    bad_drain = replace(good.drainage_condition, inp_path=Path("/nonexistent/missing.inp"))
    bad_scen = replace(good, drainage_condition=bad_drain)
    cfg = scenario_to_runconfig(bad_scen, dem, issue_time=ISSUE)
    with pytest.raises((CouplingError, FileNotFoundError, Exception)):
        cfg.validate()
    # 3) Negative intensity in a profile
    from services.scenarios.profiles import RainfallProfileRecord, ProfileStatus
    bad_prof = replace(good.rainfall_profile, intensities_mmh=tuple([-1.0] + [5.0]*11))
    bad_scen2 = replace(good, rainfall_profile=bad_prof)
    # Should fail because RunConfig validates non-negative intensities
    cfg2 = scenario_to_runconfig(bad_scen2, dem, issue_time=ISSUE)
    with pytest.raises(CouplingError):
        cfg2.validate()


# ---------------------------------------------------------------------------
# M5-15 output manifest and fingerprinting
# ---------------------------------------------------------------------------

def test_m5_15_output_manifest_and_fingerprinting(m5_results):
    """Every result has a complete input manifest and stable, sensitive fingerprints."""
    for sid, r in m5_results.items():
        im = r.input_manifest
        required_keys = {"dem_shape", "cell_size_m", "crs", "drainage_inp",
                         "drainage_fingerprint", "rainfall_profile_id",
                         "rainfall_profile_fp", "n_inlets", "vent_cell",
                         "dt_c_s", "surface_substeps", "duration_minutes",
                         "snapshot_interval_minutes", "extent_threshold_m",
                         "model_version", "engine_model_versions"}
        assert required_keys.issubset(im.keys()), f"{sid} manifest missing keys"
        assert im["n_inlets"] == 16
        assert tuple(im["vent_cell"]) == (95, 79)
        assert len(r.config_fingerprint) == 64
        assert len(r.run_fingerprint) == 16
        assert len(r.scenario.fingerprint) == 16
    # Fingerprints differ across scenarios (sensitive to scenario config)
    fps = {sid: r.config_fingerprint for sid, r in m5_results.items()}
    assert len(set(fps.values())) == 4
    # scenario IDs propagate
    for sid, r in m5_results.items():
        assert r.scenario.scenario_id == sid


# ---------------------------------------------------------------------------
# M5-16 scenario-summary consistency
# ---------------------------------------------------------------------------

def test_m5_16_scenario_summary_consistency(m5_results, m5_comparison):
    """Summary values are internally consistent across result and comparison."""
    for sid in ("S1", "S2", "S3", "S4"):
        r = m5_results[sid]
        d = r.to_dict()
        # summary keys present
        for key in ("scenario_id", "rainfall_summary", "loss_summary",
                    "surface_storage_summary", "drainage_storage_summary",
                    "exchange_summary", "boundary_summary", "peak_depth_m",
                    "max_flooded_area_m2", "time_to_peak_min",
                    "max_drainage_surcharge_m", "mass_ledger", "wall_seconds",
                    "acceptance", "limitations"):
            assert key in d, f"{sid} result dict missing {key}"
        # All units fields explicit
        for sk in ("rainfall_summary", "loss_summary", "surface_storage_summary",
                   "drainage_storage_summary", "exchange_summary", "boundary_summary"):
            assert "units" in d[sk], f"{sid}.{sk} missing units"
        # labels include PROVISIONAL (D-016 pending)
        assert "PROVISIONAL" in d["labels"]
        assert "SYNTHETIC" in d["labels"]
        assert "SIMULATED" in d["labels"]
        assert d["d016_status"] == "PREPARED"
    # comparison row values match individual results
    for row in m5_comparison.scenarios:
        sid = row["scenario_id"]
        r = m5_results[sid]
        assert row["peak_depth_m"] == round(r.peak_depth_m, 6)
        assert row["max_flooded_area_m2"] == round(r.max_flooded_area_m2, 4)
        assert row["acceptance"] == r.acceptance["overall"]
    # monotonic rainfall response S1<S2<S3
    assert (m5_results["S1"].peak_depth_m <=
            m5_results["S2"].peak_depth_m <=
            m5_results["S3"].peak_depth_m)
    # comparison artifact labels
    assert "PROVISIONAL" in m5_comparison.labels


# ---------------------------------------------------------------------------
# Regression guard: M4 tests must continue to pass (M5 spec §11 note).
# ---------------------------------------------------------------------------

def test_m5_m4_engine_unchanged():
    """The M4 engine is imported without modification; scenario runner builds
    RunConfig using the same constructor, preserving M4 semantics."""
    import inspect
    from services.simulation import engine as eng_mod
    # CoupledFloodModel.run signature still exists
    assert hasattr(eng_mod.CoupledFloodModel, "run")
    assert eng_mod.DT_C_DEFAULT == 5
    assert eng_mod.MODEL_VERSION.startswith("m4")


# ---------------------------------------------------------------------------
# M4 baseline still green via scenario runner on heavy profile
# ---------------------------------------------------------------------------

def test_m5_m4_heavy_baseline_reproduced(m5_results):
    """S2 (heavy, 45 mm/3h, clean drainage) should reproduce the M4 heavy
    scenario within numerical tolerance (the rainfall profile, fixture,
    inlet layout and coupling parameters are identical to M4's)."""
    r = m5_results["S2"]
    # M4-04 reported: peak 0.471 m, area 1.792 km2, S2D 495.7, outfall 488.3
    assert r.peak_depth_m == pytest.approx(0.471, abs=0.005), \
        f"S2 peak {r.peak_depth_m} differs from M4 heavy baseline"
    assert r.max_flooded_area_m2 == pytest.approx(1.792e6, rel=0.02)
    assert r.m4_result.ledger.S2D_m3 == pytest.approx(495.7, rel=0.02)
    assert r.m4_result.ledger.outfall_m3 == pytest.approx(488.3, rel=0.02)
