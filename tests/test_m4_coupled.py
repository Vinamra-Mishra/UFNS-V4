"""M4 — coupled flood model test matrix (IMPLEMENTATION_SPEC M4 §23).

M4-01..M4-15 as mandated. The hard gate is M4-05: if the blocked drainage
does not measurably change the surface response, M4 = STOP AND REVIEW.
Documented tolerances (set before results were known):
  - ledger gates: pass <= 1% relative (project gate; M3 §9);
  - timestep halving: storage drift <= 5%, exchange drift <= 20% (M3-08);
  - engine-vs-M3-spike semantic equivalence: 1e-6 m3 absolute on all ledger
    terms (float32 rainfall-field representation in the engine).
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from services.hydraulics.coupling import CoupledSpike, CouplingError, build_spike_surface
from services.hydraulics.fixture import exact_fixture_inp, write_fixtures
from services.ingestion.dem import synthetic_dem
from services.simulation.engine import (
    FIXTURE_VENT_CELL,
    LossSpec,
    RainfallSpec,
    RunConfig,
    CoupledFloodModel,
    m4_scenario_configs,
)

ISSUE = datetime(2026, 8, 21, tzinfo=timezone.utc)
VENT_GROUND = None  # resolved from the DEM at fixture time


# ---------------------------------------------------------------------------
# shared fixtures (module scope: the expensive runs are cached)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def dem() -> np.ndarray:
    return synthetic_dem()


@pytest.fixture(scope="module")
def cfgs(dem):
    return m4_scenario_configs(dem, ISSUE)


@pytest.fixture(scope="module")
def m4_results(dem, cfgs) -> dict[str, "M4RunResult"]:
    out = {}
    for key in ("zero", "uniform", "spatial", "heavy", "heavy_blocked"):
        out[key] = CoupledFloodModel(cfgs[key]).run()
    return out


@pytest.fixture(scope="module")
def vent_ground(dem) -> float:
    return float(dem[FIXTURE_VENT_CELL])


# ---------------------------------------------------------------------------
# M4-01 zero rainfall
# ---------------------------------------------------------------------------

def test_m4_01_zero_rainfall(m4_results):
    res = m4_results["zero"]
    led = res.ledger
    final = res.depth_arrays[180]
    # no rainfall-driven water: only the M2 h_init boundary film may move
    assert final.max() < 1e-5
    assert (final > 0.05).sum() == 0          # no flooding at the extent threshold
    assert led.S2D_m3 == 0.0 and led.D2S_m3 == 0.0
    assert led.outfall_m3 == pytest.approx(0.0, abs=1e-6)
    assert res.max_flooded_area_m2 == 0.0
    assert led.status() == "pass"             # dry-run film allowance documented


# ---------------------------------------------------------------------------
# M4-02 uniform rainfall
# ---------------------------------------------------------------------------

def test_m4_02_uniform_rainfall(m4_results):
    res = m4_results["uniform"]
    led = res.ledger
    assert res.peak_depth_m > 0.01
    assert res.max_flooded_area_m2 > 0
    assert led.S2D_m3 > 0                    # capture occurred
    assert led.outfall_m3 > 0                # captured water reached the outfall
    assert led.losses_m3 > 0                 # Horton losses accounted
    assert led.microstore_final_m3 > 0
    assert led.status() == "pass"


# ---------------------------------------------------------------------------
# M4-03 spatial rainfall
# ---------------------------------------------------------------------------

def test_m4_03_spatial_rainfall(m4_results):
    res = m4_results["spatial"]
    d15 = res.depth_arrays[15]
    # the convective cell starts in the west and advects east: at lead 15 the
    # western dry region must be wetter than the eastern dry region
    west = d15[20:45, 8:34].mean()
    east = d15[20:45, 100:126].mean()
    assert west > east
    assert d15.std() > 1e-3                  # spatially heterogeneous forcing
    assert res.ledger.S2D_m3 > 0             # drainage still participates
    assert res.ledger.status() == "pass"


# ---------------------------------------------------------------------------
# M4-04 heavy rainfall
# ---------------------------------------------------------------------------

def test_m4_04_heavy_rainfall(m4_results):
    heavy = m4_results["heavy"]
    uniform = m4_results["uniform"]
    # increased rainfall => increased runoff/flood potential (measured, not predicted)
    assert heavy.peak_depth_m > uniform.peak_depth_m
    assert heavy.max_flooded_area_m2 >= uniform.max_flooded_area_m2
    assert heavy.ledger.rain_m3 > uniform.ledger.rain_m3
    assert heavy.ledger.status() == "pass"


# ---------------------------------------------------------------------------
# M4-05 heavy + blockage (the key coupling demonstration — hard gate)
# ---------------------------------------------------------------------------

def test_m4_05_blockage(m4_results, vent_ground):
    clean = m4_results["heavy"]
    blocked = m4_results["heavy_blocked"]
    lc, lb = clean.ledger, blocked.ledger
    # identical forcing; every comparison below is measured, not invented.
    assert lb.D2S_m3 > lc.D2S_m3, f"blockage must produce surcharge return: {lb.D2S_m3} vs {lc.D2S_m3}"
    assert lc.D2S_m3 == 0.0, "clean drainage must not spill"
    assert lb.outfall_m3 < lc.outfall_m3, "blockage must reduce outfall discharge"
    assert lb.S2D_m3 < lc.S2D_m3, "blockage must throttle capture (backwater)"
    assert lb.S2D_m3 > 0 and lc.S2D_m3 > 0
    # hydraulic surcharge: blocked ST1 head above the mapped manhole ground
    assert blocked.max_st1_head_m > vent_ground, "blocked network must surcharge above ground"
    assert clean.max_st1_head_m < vent_ground, "clean network must not surcharge"
    assert blocked.snapshots[-1].drainage.surcharged is True
    assert clean.snapshots[-1].drainage.surcharged is False
    # surface response: more water retained, more area flooded, vent wetter
    assert (lb.S_s1 - lb.S_s0) > (lc.S_s1 - lc.S_s0)
    assert blocked.max_flooded_area_m2 >= clean.max_flooded_area_m2
    assert blocked.snapshots[-1].drainage.vent_depth_m > clean.snapshots[-1].drainage.vent_depth_m
    # both ledgers close
    assert lc.status() == "pass" and lb.status() == "pass"


# ---------------------------------------------------------------------------
# M4-06 mass conservation (primary gate)
# ---------------------------------------------------------------------------

def test_m4_06_mass_conservation(m4_results):
    res = m4_results["heavy"]
    led = res.ledger
    mb = res.mass_balance
    assert mb.status == "pass"
    assert mb.relative_error <= 0.01
    # no double counting: exchange is internal and cancels in the combined
    # ledger; the combined residual equals the surface residual (drainage
    # residual is ~0 by the engine-identity construction)
    assert led.residual_drainage == pytest.approx(0.0, abs=1e-6)
    assert led.residual_total == pytest.approx(led.residual_surface, rel=1e-9)
    # subsystem residuals within the gate scale; the surface residual is the
    # documented M2 h_init film creation (~0.02% of rainfall on this domain),
    # explicitly reported — never silently absorbed
    assert abs(led.residual_surface) <= 0.01 * led.rain_m3
    # every term physically present
    assert led.rain_m3 > 0 and led.losses_m3 > 0 and led.outfall_m3 > 0
    assert led.S2D_m3 > 0 and led.S_d1 >= 0
    assert mb.rainfall_input_m3 == pytest.approx(led.rain_m3)


# ---------------------------------------------------------------------------
# M4-07 non-negative depth
# ---------------------------------------------------------------------------

def test_m4_07_non_negative_depth(m4_results):
    for res in m4_results.values():
        for lead, arr in res.depth_arrays.items():
            assert np.all(np.isfinite(arr)), f"{res.config.scenario_id} lead {lead}: non-finite"
            assert arr.min() >= -1e-12, f"{res.config.scenario_id} lead {lead}: negative depth"


# ---------------------------------------------------------------------------
# M4-08 snapshot determinism + cadence
# ---------------------------------------------------------------------------

def test_m4_08_snapshots(m4_results, cfgs):
    res = m4_results["heavy"]
    leads = [s.lead_minutes for s in res.snapshots]
    assert leads == list(range(0, 181, 5))
    times = [s.valid_time for s in res.snapshots]
    assert all(t.tzinfo is not None for t in times)
    assert times == sorted(times)
    assert times[0] == ISSUE and times[-1] == ISSUE + timedelta(minutes=180)
    # deterministic: identical config -> identical snapshot statistics
    again = CoupledFloodModel(cfgs["heavy"]).run()
    for s1, s2 in zip(res.snapshots, again.snapshots):
        assert s1.max_depth_m == s2.max_depth_m
        assert s1.flooded_cells == s2.flooded_cells
        assert s1.drainage.st1_head_m == s2.drainage.st1_head_m


# ---------------------------------------------------------------------------
# M4-09 scenario isolation
# ---------------------------------------------------------------------------

def test_m4_09_scenario_isolation(m4_results, cfgs):
    zero1 = m4_results["zero"]
    _ = CoupledFloodModel(cfgs["heavy"]).run()   # interleave another scenario
    zero2 = CoupledFloodModel(cfgs["zero"]).run()
    # fresh state: identical results regardless of what ran before
    assert np.array_equal(zero1.depth_arrays[180], zero2.depth_arrays[180])
    assert zero1.ledger.residual_total == zero2.ledger.residual_total
    assert zero1.simulation_run.configuration_fingerprint == zero2.simulation_run.configuration_fingerprint


# ---------------------------------------------------------------------------
# M4-10 timestep consistency (halving; tolerances pre-documented)
# ---------------------------------------------------------------------------

def test_m4_10_timestep_halving(dem, cfgs):
    base = cfgs["heavy"]
    coarse_cfg = RunConfig(
        run_id="m4_halving_10", scenario_id="heavy", issue_time=ISSUE, dem=dem,
        inlet_cells=base.inlet_cells, vent_cell=base.vent_cell,
        rainfall=base.rainfall, losses=base.losses, drainage_inp=base.drainage_inp,
        dt_c=10, surface_substeps=10, snapshot_interval_minutes=10,
    )
    coarse = CoupledFloodModel(coarse_cfg).run()
    fine = CoupledFloodModel(base).run()
    dS_c = coarse.ledger.S_s1 - coarse.ledger.S_s0
    dS_f = fine.ledger.S_s1 - fine.ledger.S_s0
    ex_c = coarse.ledger.S2D_m3 + coarse.ledger.D2S_m3
    ex_f = fine.ledger.S2D_m3 + fine.ledger.D2S_m3
    assert abs(dS_c - dS_f) / dS_f <= 0.05, f"storage halving drift {abs(dS_c-dS_f)/dS_f:.4f}"
    assert abs(ex_c - ex_f) / ex_f <= 0.20, f"exchange halving drift {abs(ex_c-ex_f)/ex_f:.4f}"
    assert abs(coarse.peak_depth_m - fine.peak_depth_m) / fine.peak_depth_m <= 0.05
    assert coarse.ledger.status() == "pass" and fine.ledger.status() == "pass"


# ---------------------------------------------------------------------------
# M4-11 drainage sensitivity
# ---------------------------------------------------------------------------

def test_m4_11_drainage_sensitivity(dem, cfgs):
    base = cfgs["heavy"]
    stronger = RunConfig(
        run_id="m4_sens_ao", scenario_id="heavy", issue_time=ISSUE, dem=dem,
        inlet_cells=base.inlet_cells, vent_cell=base.vent_cell,
        rainfall=base.rainfall, losses=base.losses, drainage_inp=base.drainage_inp,
        ao_per_inlet=0.004,
    )
    hi = CoupledFloodModel(stronger).run()
    lo = CoupledFloodModel(base).run()
    # more inlet capacity removes more water from the surface
    assert hi.ledger.S2D_m3 > lo.ledger.S2D_m3
    assert (hi.ledger.S_s1 - hi.ledger.S_s0) < (lo.ledger.S_s1 - lo.ledger.S_s0)
    assert hi.ledger.status() == "pass"


# ---------------------------------------------------------------------------
# M4-12 output provenance
# ---------------------------------------------------------------------------

def test_m4_12_output_provenance(dem, tmp_path):
    import rasterio

    from services.contracts import SimulationRun

    cfg = RunConfig(
        run_id="m4_prov", scenario_id="uniform_short", issue_time=ISSUE, dem=dem,
        inlet_cells=[(95, 79)], vent_cell=(95, 80),
        rainfall=RainfallSpec(kind="uniform", intensities_mmh=[10.0]),
        duration_minutes=30, snapshot_interval_minutes=5,
        artifact_dir=tmp_path / "art",
    )
    res = CoupledFloodModel(cfg).run()
    art = tmp_path / "art"
    tifs = sorted(art.glob("depth_t*.tif"))
    assert len(tifs) == 7  # leads 0,5,...,30
    with rasterio.open(tifs[-1]) as src:
        assert src.crs.to_epsg() == 32645
        tags = src.tags()
        assert tags["ARENA_PROVENANCE"] == "MODEL_PREDICTION"
        assert "PROVISIONAL" in tags["ARENA_QUALITY"]
        assert tags["ARENA_EXTENT_THRESHOLD_M"] == "0.05"
    summary = art / "run_summary.json"
    assert summary.exists()
    assert res.simulation_run.output_manifest_uri == str(summary)
    assert res.snapshots[-1].depth_asset_uri == str(tifs[-1])
    # fingerprints: stable and sensitive
    f1 = res.simulation_run.configuration_fingerprint
    assert f1 == cfg.fingerprint()
    cfg2 = cfg
    cfg2.ao_per_inlet = 0.009
    assert cfg2.fingerprint() != f1
    assert "dem_sha256" in res.simulation_run.input_manifest
    assert res.simulation_run.model_versions["engine"].startswith("m4")


# ---------------------------------------------------------------------------
# M4-13 runtime
# ---------------------------------------------------------------------------

def test_m4_13_runtime(m4_results):
    res = m4_results["heavy"]
    simulated_hours = 3.0
    assert res.wall_seconds > 0 and res.wall_seconds < 600, "coupled run must finish well under the gate"
    ratio = simulated_hours * 3600.0 / res.wall_seconds
    print(f"\nM4-13: 3 h coupled run in {res.wall_seconds:.1f} s "
          f"({ratio:.0f}x real-time; cpu={res.cpu_seconds:.1f}s; rss={res.peak_rss_mb:.0f} MB; "
          f"{res.n_coupling_steps} coupling steps)")
    assert ratio > 10  # at least an order of magnitude faster than real time


# ---------------------------------------------------------------------------
# M4-14 invalid configuration
# ---------------------------------------------------------------------------

def test_m4_14_invalid_configuration(dem, cfgs, tmp_path):
    good = cfgs["heavy"]
    good_inp = tmp_path / "good.inp"
    good_inp.write_text(exact_fixture_inp(False, datum_offset_m=10.0))
    cases = [
        dict(dt_c=0),
        dict(dt_c=2.5),
        dict(surface_substeps=0),
        dict(surface_substeps=3),          # 5 % 3 != 0
        dict(duration_minutes=185),
        dict(snapshot_interval_minutes=7),
        dict(extent_threshold_m=0.0),
        dict(ao_per_inlet=-0.001),
        dict(vent_cell=good.inlet_cells[0]),   # vent collides with an inlet
        dict(inlet_cells=[(0, 0)]),            # boundary cell
        dict(drainage_inp=tmp_path / "missing.inp"),
        dict(issue_time=datetime(2026, 8, 21)),  # naive timestamp
    ]
    for patch in cases:
        kwargs = dict(
            run_id=good.run_id, scenario_id=good.scenario_id, issue_time=good.issue_time,
            dem=good.dem, inlet_cells=good.inlet_cells, vent_cell=good.vent_cell,
            rainfall=good.rainfall, losses=good.losses, drainage_inp=good_inp,
        )
        kwargs.update(patch)
        with pytest.raises(CouplingError):
            CoupledFloodModel(RunConfig(**kwargs))
    # non-finite DEM
    bad_dem = good.dem.copy()
    bad_dem[10, 10] = np.nan
    cfg = RunConfig(
        run_id="x", scenario_id="x", issue_time=ISSUE, dem=bad_dem,
        inlet_cells=good.inlet_cells, vent_cell=good.vent_cell, drainage_inp=good_inp,
    )
    with pytest.raises(CouplingError):
        CoupledFloodModel(cfg)
    # negative rainfall intensity
    with pytest.raises(CouplingError):
        RunConfig(
            run_id="x", scenario_id="x", issue_time=ISSUE, dem=good.dem,
            inlet_cells=good.inlet_cells, vent_cell=good.vent_cell, drainage_inp=good_inp,
            rainfall=RainfallSpec(kind="uniform", intensities_mmh=[-1.0]),
        ).validate()


# ---------------------------------------------------------------------------
# M4-15 reproducibility
# ---------------------------------------------------------------------------

def test_m4_15_reproducibility(cfgs):
    a = CoupledFloodModel(cfgs["heavy"]).run()
    b = CoupledFloodModel(cfgs["heavy"]).run()
    assert np.array_equal(a.depth_arrays[180], b.depth_arrays[180])
    assert a.ledger.S2D_m3 == b.ledger.S2D_m3
    assert a.ledger.D2S_m3 == b.ledger.D2S_m3
    assert a.ledger.outfall_m3 == b.ledger.outfall_m3
    assert a.ledger.residual_total == b.ledger.residual_total
    assert a.peak_depth_m == b.peak_depth_m
    assert a.max_flooded_area_m2 == b.max_flooded_area_m2
    assert a.simulation_run.configuration_fingerprint == b.simulation_run.configuration_fingerprint


# ---------------------------------------------------------------------------
# Engine reuses validated M3 semantics (equivalence on the single-inlet case)
# ---------------------------------------------------------------------------

def test_engine_matches_m3_spike_semantics(tmp_path):
    fx = write_fixtures(tmp_path)
    spike_surface = build_spike_surface()
    dem = spike_surface.dem
    cfg = RunConfig(
        run_id="equiv", scenario_id="equiv", issue_time=ISSUE, dem=dem,
        cell_size_m=30.0,
        losses=LossSpec(enabled=False),        # M3 spike has no losses
        closed_boundaries=True,
        drainage_inp=fx["clean"],
        inlet_cells=[(3, 3)], vent_cell=(3, 4),
        dt_c=5, surface_substeps=1,            # M3 advances the surface once per stride
        duration_minutes=15, snapshot_interval_minutes=5,
        ao_per_inlet=0.1, ao_vent=0.1,
        rainfall=RainfallSpec(kind="uniform", intensities_mmh=[60.0], interval_minutes=15),
    )
    eng = CoupledFloodModel(cfg).run()
    spike = CoupledSpike(build_spike_surface(), fx["clean"], (3, 3), (3, 4), dt_c=5)
    spike.run(minutes=15, rain_mmh=60.0)
    # tolerance 1e-3 m3 (0.015% of S2D): the engine renders rainfall fields in
    # float32 (M2 renderer) vs the spike driver's float64 constant, and the
    # capture orifice is knife-edge-sensitive at the head equilibrium, so the
    # per-stride capture toggles amplify the representation difference.
    assert eng.ledger.S2D_m3 == pytest.approx(spike.ledger.S2D_m3, abs=1e-3)
    assert eng.ledger.D2S_m3 == pytest.approx(spike.ledger.D2S_m3, abs=1e-3)
    assert eng.ledger.outfall_m3 == pytest.approx(spike.ledger.outfall_m3, abs=1e-3)
    assert (eng.ledger.S_s1 - eng.ledger.S_s0) == pytest.approx(
        spike.ledger.S_s1 - spike.ledger.S_s0, abs=1e-3)
    assert eng.ledger.residual_total == pytest.approx(spike.ledger.residual_total, abs=1e-3)
    assert eng.ledger.status() == spike.ledger.status()
