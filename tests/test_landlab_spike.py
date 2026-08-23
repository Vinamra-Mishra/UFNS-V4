"""M2 spike — Landlab OverlandFlow adapter verification (IMPLEMENTATION_SPEC M2).

Mandated tests: zero rainfall, uniform rainfall, spatial rainfall, losses,
timestep halving, mass conservation, reproducibility. Failing any of these
means STOP AND REVIEW (spec §25) — the tests must never be weakened to pass.

Accounting model (documented in services/hydrology/surface.py):
- boundary outflow is the exact residual identity V(post-rain, pre-step) - V(post-step);
- the h_init thin film creates a one-time mass bias ~ n_core * h_init * A,
  which the closed-bowl test verifies against the measured film_volume_m3.
"""

import time
from datetime import datetime, timezone

import numpy as np
import pytest

from services.hydrology.surface import HortonLoss, SurfaceModel
from services.simulation.ledger import MassLedger

CELL = 10.0  # small spike grid: 60 x 60 cells @ 10 m
T0 = datetime(2026, 8, 21, tzinfo=timezone.utc)
T1 = datetime(2026, 8, 21, 3, 0, tzinfo=timezone.utc)


def _bowl(n: int = 60) -> np.ndarray:
    """Parabolic closed bowl: drains toward centre, rim 2 m above centre."""
    y, x = np.mgrid[0:n, 0:n] / (n - 1) - 0.5
    return 10.0 + 2.0 * (x**2 + y**2) * 4.0


def _plane(n: int = 60, slope: float = 0.01) -> np.ndarray:
    """Planar slope falling toward the east edge."""
    y, x = np.mgrid[0:n, 0:n]
    return 10.0 - slope * CELL * x


def _run(
    model: SurfaceModel,
    rain_mmh,
    duration_s: float,
    dt_s=None,
    horton: HortonLoss | None = None,
) -> MassLedger:
    """Run a scenario with the adapter using adaptive dt; returns closed ledger."""
    led = MassLedger()
    wet = np.zeros(model.shape)
    t = 0.0
    r_ms = (
        rain_mmh / (1000 * 3600)
        if not isinstance(rain_mmh, np.ndarray)
        else rain_mmh
    )
    r_arr = np.broadcast_to(np.asarray(r_ms, dtype=np.float64), model.shape)
    while t < duration_s - 1e-9:
        dt = dt_s if dt_s is not None else model.calc_dt()
        dt = min(dt, duration_s - t)
        wet += dt * (r_arr > 0)
        led.add_rainfall(model.apply_rainfall(r_arr, dt))
        if horton is not None:
            led.add_infiltration(model.apply_infiltration(horton.capacity(wet), dt))
        model.step(dt)
        t += dt
    led.surface_storage_initial_m3 = 0.0
    led.surface_storage_final_m3 = model.surface_storage_m3()
    led.add_surface_boundary_outflow(model.boundary_outflow_m3)
    return led.close(T0, T1)


# ---------------------------------------------------------------------------


def test_zero_rain_stays_dry():
    """No rainfall-driven water: only the h_init boundary film redistributes
    (film-scale storage/outflow, documented artifact — the film volume is
    n_core * h_init * A, reported as model.film_volume_m3)."""
    m = SurfaceModel(_plane(), cell_size_m=CELL, closed_boundaries=True)
    _run(m, 0.0, duration_s=1800)
    assert m.surface_storage_m3() <= m.film_volume_m3 * 1.5
    assert m.boundary_outflow_m3 == pytest.approx(0.0, abs=1e-9)  # closed: nothing leaves
    assert m.depth.max() < 1e-5  # film scale only


def test_uniform_rain_closed_bowl_conserves():
    """10 mm/h for 1 h on a closed bowl -> storage == rainfall (film-tight)."""
    m = SurfaceModel(_bowl(), cell_size_m=CELL, closed_boundaries=True)
    mb = _run(m, 10.0, duration_s=3600)
    expected = (10.0 / 1000.0) * m.cell_area_m2 * np.count_nonzero(m.core)
    assert mb.status == "pass", f"mass balance failed: {mb}"
    assert m.boundary_outflow_m3 == pytest.approx(0.0, abs=1e-6)  # closed: nothing leaves
    # storage must equal rainfall within the documented film bias
    assert m.surface_storage_m3() == pytest.approx(expected, rel=1e-3, abs=m.film_volume_m3)
    d = m.depth
    assert d[d.shape[0] // 2, d.shape[1] // 2] > d[0, 0] * 2  # ponds in the bowl centre


def test_spatial_rainfall_mapping():
    """Rain applied only in a western sub-block must appear only there (mapping)."""
    m = SurfaceModel(_plane(), cell_size_m=CELL, closed_boundaries=True)
    field = np.zeros(m.shape)
    field[:, :12] = 20.0 / (1000 * 3600)  # mm/h -> m/s
    _run(m, field, duration_s=600)
    d = m.depth
    assert np.any(d[:, :12] > 0)
    # untouched half must stay essentially dry: only film-scale creep allowed
    # (the h_init film propagates ~2e-6 m into dry cells — documented artifact)
    assert np.all(d[:, 24:] < 1e-5)
    # rain applies to CORE cells only: count core cells inside the wet block
    n_core_wet = int(np.count_nonzero(m.core.reshape(m.shape)[:, :12]))
    expected = (20.0 / 1000.0) * (600 / 3600) * m.cell_area_m2 * n_core_wet
    assert m.surface_storage_m3() == pytest.approx(expected, rel=1e-3, abs=m.film_volume_m3)


def test_horton_losses_removed_and_accounted():
    m = SurfaceModel(_bowl(), cell_size_m=CELL, closed_boundaries=True)
    h = HortonLoss(f0_ms=30e-3 / 3600, fmin_ms=3e-3 / 3600, k_s1=1 / 900)
    mb = _run(m, 10.0, duration_s=1800, horton=h)
    assert mb.status == "pass"
    assert mb.infiltration_loss_m3 > 0
    # losses never exceed available water: storage + infiltration == rainfall (+film bias)
    rain_vol = mb.rainfall_input_m3
    assert mb.final_surface_storage_m3 + mb.infiltration_loss_m3 == pytest.approx(
        rain_vol, rel=1e-3, abs=m.film_volume_m3
    )


def test_timestep_halving_convergence():
    m1 = SurfaceModel(_bowl(), cell_size_m=CELL, closed_boundaries=True)
    _run(m1, 20.0, duration_s=600, dt_s=2.0)
    m2 = SurfaceModel(_bowl(), cell_size_m=CELL, closed_boundaries=True)
    _run(m2, 20.0, duration_s=600, dt_s=1.0)
    # documented tolerance: 2% on total volume, 5e-4 m on depth field
    # (wetting-front trajectory differs between dt at the film scale)
    assert m1.surface_storage_m3() == pytest.approx(m2.surface_storage_m3(), rel=0.02)
    assert np.max(np.abs(m1.depth - m2.depth)) < 5e-4


def test_open_boundary_outflow_occurs_and_closes():
    """Planar slope, open edges: water leaves; ledger closes to the film bound."""
    m = SurfaceModel(_plane(), cell_size_m=CELL, closed_boundaries=False)
    mb = _run(m, 30.0, duration_s=1800)
    assert m.boundary_outflow_m3 > 0
    assert m.surface_storage_m3() < mb.rainfall_input_m3
    # the h_init film is a bounded virtual-water source ~ film_volume per run
    # (documented in surface.py); the ledger residual must stay within that
    # bound and the mass gate must pass.
    residual = mb.rainfall_input_m3 - mb.surface_boundary_outflow_m3 - mb.final_surface_storage_m3
    assert abs(residual) <= 1.5 * m.film_volume_m3
    assert mb.status == "pass"
    assert np.all(np.isfinite(m.depth)) and m.depth.min() >= -1e-12


def test_reproducibility_bitwise():
    m1 = SurfaceModel(_bowl(), cell_size_m=CELL, closed_boundaries=False)
    _run(m1, 25.0, duration_s=900, dt_s=2.0)
    m2 = SurfaceModel(_bowl(), cell_size_m=CELL, closed_boundaries=False)
    _run(m2, 25.0, duration_s=900, dt_s=2.0)
    assert np.array_equal(m1.depth, m2.depth)


def test_material_negative_depth_fails_fast():
    m = SurfaceModel(_plane(), cell_size_m=CELL, closed_boundaries=True)
    m.grid.at_node["surface_water__depth"][np.argwhere(m.core)[0]] = -0.5
    with pytest.raises(RuntimeError):
        m.step(1.0)


def test_fixture_scale_runtime():
    """134x134 @ 30 m, 3 h heavy fixture event: measure wall time (informative)."""
    from services.ingestion.dem import CELL_SIZE_M, GRID_CELLS, synthetic_dem

    dem = synthetic_dem()
    m = SurfaceModel(dem, cell_size_m=CELL_SIZE_M, closed_boundaries=False)
    from services.rainfall.scenarios import build_profile

    profile = build_profile("heavy", 45.0)
    rates = np.array(profile.intensities_mmh, dtype=np.float64) / (1000 * 3600)
    led = MassLedger()
    t0 = time.time()
    dt = 5.0
    interval_s = 15 * 60
    for i in range(12):  # 15-min forcing intervals
        r_ms = np.full(m.shape, rates[i])
        for _ in range(interval_s // int(dt)):
            led.add_rainfall(m.apply_rainfall(r_ms, dt))
            m.step(dt)
    wall = time.time() - t0
    print(f"\nfixture-scale spike: 134x134 @30m, 3h heavy event, {m.total_steps} steps in {wall:.1f}s")
    assert wall < 1800, "must run faster than the simulated 3-hour horizon"
    assert np.all(np.isfinite(m.depth))
