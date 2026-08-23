"""M3 spike — SWMM↔surface coupling test matrix (IMPLEMENTATION_SPEC M3).

Tests M3-01..M3-15 as mandated. Acceptance gate: every primary test passes;
any failure means STOP AND REVIEW (spec §25) — tests must never be weakened
to pass.

PRE-DOCUMENTED TOLERANCES (set before results were known, per M3-08):
  - Ledger closure: project gate — pass <= 1% relative, warning <= 5%, fail > 5%.
  - Timestep halving: final surface storage within 5%; cumulative exchange
    volume within 20%. Justification: the coupling is explicit and first-order
    in dt_c (capture/return rates held over each coupling stride); the
    physically meaningful state (storage/heads) converges much tighter than
    the control-flow exchange rate. Not a relaxation of the mass gates.
"""

import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from services.hydraulics.coupling import (
    CoupledSpike,
    CouplingError,
    build_spike_surface,
    orifice_exchange_rate,
)
from services.hydraulics.fixture import (
    AO_ORIFICE,
    CD_ORIFICE,
    G,
    C1_BLOCKED_CAPACITY,
    C1_CAPACITY,
    C1_DIAMETER,
    C1_MANNING,
    C1_SLOPE,
    full_bore_capacity,
    write_fixtures,
)

INLET = (3, 3)
VENT = (3, 4)


@pytest.fixture(scope="module")
def fixtures(tmp_path_factory) -> dict[str, Path]:
    d = tmp_path_factory.mktemp("swmm_fixtures")
    return write_fixtures(d)


def _run(inp, minutes, rain=0.0, ext=0.0, dt=5, ao=AO_ORIFICE):
    s = build_spike_surface()
    c = CoupledSpike(s, inp, INLET, VENT, dt_c=dt, ao=ao)
    c.run(minutes=minutes, rain_mmh=rain, external_inflow_m3s=ext)
    return c


# ---------------------------------------------------------------------------
# M3-01 — SWMM standalone smoke test
# ---------------------------------------------------------------------------

def test_m3_01_swmm_standalone_smoke(fixtures):
    from pyswmm import Links, Nodes, Simulation

    with Simulation(str(fixtures["clean"])) as sim:
        sim.step_advance(5)
        st1 = Nodes(sim)["ST1"]
        v1 = Nodes(sim)["V1"]
        o1 = Nodes(sim)["O1"]
        c1 = Links(sim)["C1"]
        for i, _ in enumerate(sim):
            if i >= 60:  # 5 min of 50 L/s
                break
            st1.generated_inflow(0.05)
        # physically interpretable state
        assert st1.depth > 0
        assert st1.head == pytest.approx(st1.invert_elevation + st1.depth, abs=1e-9)
        assert c1.flow > 0
        assert o1.total_inflow > 0
        assert v1.depth >= 0
        assert sim.flow_routing_error == 0.0
    # analytical capacity cross-check (independent plain-math computation)
    a = math.pi * C1_DIAMETER**2 / 4.0
    r = C1_DIAMETER / 4.0
    q_full = (1.0 / C1_MANNING) * a * r ** (2.0 / 3.0) * math.sqrt(C1_SLOPE)
    assert q_full == pytest.approx(C1_CAPACITY, rel=1e-12)
    assert C1_CAPACITY == pytest.approx(0.0968, abs=0.0002)
    assert C1_BLOCKED_CAPACITY == pytest.approx(C1_CAPACITY * 0.5 ** (8.0 / 3.0), rel=1e-12)


# ---------------------------------------------------------------------------
# M3-02 — zero exchange
# ---------------------------------------------------------------------------

def test_m3_02_zero_exchange(fixtures):
    c = _run(fixtures["clean"], minutes=10)
    led = c.ledger
    assert led.S2D_m3 == 0.0
    assert led.D2S_m3 == 0.0
    assert led.outfall_m3 == pytest.approx(0.0, abs=1e-12)
    assert led.flood_export_m3 == pytest.approx(0.0, abs=1e-12)
    # surface stays at film scale only (no invented water)
    assert led.S_s1 - led.S_s0 <= 1.5 * c.surface.film_volume_m3
    assert led.status() == "pass"


# ---------------------------------------------------------------------------
# M3-03 — surface -> drainage
# ---------------------------------------------------------------------------

def test_m3_03_surface_to_drainage(fixtures):
    c = _run(fixtures["clean"], minutes=15, rain=60.0)
    led = c.ledger
    assert led.S2D_m3 > 0, "capture must occur"
    assert led.outfall_m3 > 0, "captured water must reach the outfall"
    assert all(x.S2D_vol >= 0 for x in c.exchange)
    # drainage removed water from the surface: storage < rainfall
    assert led.S_s1 - led.S_s0 < led.rain_m3
    # capture happened only when surface head exceeded drainage head
    cap_steps = [x for x in c.exchange if x.S2D_vol > 0]
    assert cap_steps, "no capture steps recorded"
    assert all(x.eta_s > x.H_d for x in cap_steps)
    assert led.status() == "pass"
    assert abs(led.residual_surface) < 1e-6


# ---------------------------------------------------------------------------
# M3-04 — drainage -> surface (reverse exchange)
# ---------------------------------------------------------------------------

def test_m3_04_drainage_to_surface(fixtures):
    c = _run(fixtures["blocked"], minutes=12, ext=0.06)
    led = c.ledger
    assert led.D2S_m3 > 0, "reverse exchange must occur"
    assert led.S2D_m3 == 0.0, "no capture expected in a dry-surface reverse test"
    # surface gains exactly the returned volume (closed bowl, no losses)
    assert led.S_s1 - led.S_s0 == pytest.approx(led.D2S_m3, rel=1e-6)
    # return happened only when drainage head exceeded vent surface
    ret_steps = [x for x in c.exchange if x.D2S_vol > 0]
    assert ret_steps and all(x.H_d > x.eta_v for x in ret_steps)
    assert led.status() == "pass"


# ---------------------------------------------------------------------------
# M3-05 — surcharge (engine flooding demonstration)
# ---------------------------------------------------------------------------

def test_m3_05_surcharge(fixtures):
    from pyswmm import Nodes, Simulation

    # the coupling run exports flooding to the surface
    c = _run(fixtures["flood"], minutes=15, ext=0.5)
    led = c.ledger
    assert led.flood_export_m3 > 0, "SWMM flooding must be exported to the surface"
    assert led.D2S_m3 > 0

    # engine-level surcharge evidence: head >= rim, flooding > 0
    with Simulation(str(fixtures["flood"])) as sim:
        sim.step_advance(5)
        st1 = Nodes(sim)["ST1"]
        j1 = Nodes(sim)["J1"]
        for i, _ in enumerate(sim):
            if i >= 180:
                break
            st1.generated_inflow(0.5)
        rim = j1.invert_elevation + 0.01  # fixture MaxDepth
        assert j1.head > rim, f"junction not surcharged: head {j1.head} <= rim {rim}"
        assert j1.flooding > 0, "flooding rate must be positive at surcharge"
    # no mass-gate claim for the flooding demo (documented: point-sampled
    # flooding rates make the export approximate); the head/flooding state is
    # the demonstrated evidence.


# ---------------------------------------------------------------------------
# M3-06 — blockage
# ---------------------------------------------------------------------------

def test_m3_06_blockage(fixtures):
    cc = _run(fixtures["clean"], minutes=15, ext=0.15)
    cb = _run(fixtures["blocked"], minutes=15, ext=0.15)
    # identical forcing; observed differences (not pre-invented magnitudes):
    assert cb.ledger.D2S_m3 > cc.ledger.D2S_m3, (
        f"blockage must increase surcharge return: {cb.ledger.D2S_m3:.2f} vs {cc.ledger.D2S_m3:.2f}"
    )
    assert cb.ledger.outfall_m3 < cc.ledger.outfall_m3, (
        f"blockage must reduce outfall discharge: {cb.ledger.outfall_m3:.2f} vs {cc.ledger.outfall_m3:.2f}"
    )
    assert cc.ledger.status() == "pass"
    assert cb.ledger.status() == "pass"


# ---------------------------------------------------------------------------
# M3-07 — no-drainage control
# ---------------------------------------------------------------------------

def test_m3_07_no_drainage_control(fixtures):
    coupled = _run(fixtures["clean"], minutes=15, rain=60.0)
    control = _run(fixtures["clean"], minutes=15, rain=60.0, ao=0.0)  # capture disabled
    # drainage coupling must change the surface solution: less water retained
    assert coupled.ledger.S_s1 < control.ledger.S_s1
    assert coupled.ledger.outfall_m3 > 0
    assert control.ledger.outfall_m3 == pytest.approx(0.0, abs=1e-12)


# ---------------------------------------------------------------------------
# M3-08 — timestep halving (pre-documented tolerances)
# ---------------------------------------------------------------------------

def test_m3_08_timestep_halving(fixtures):
    # Scenario chosen to exercise BOTH exchange directions substantially
    # (blocked fixture: capture + strong surcharge return, D2S ~ 96 m3).
    h10 = _run(fixtures["blocked"], minutes=20, rain=45.0, ext=0.1, dt=10)
    h5 = _run(fixtures["blocked"], minutes=20, rain=45.0, ext=0.1, dt=5)
    # PRE-DOCUMENTED tolerances (see module docstring):
    dS_10 = h10.ledger.S_s1 - h10.ledger.S_s0
    dS_5 = h5.ledger.S_s1 - h5.ledger.S_s0
    assert abs(dS_10 - dS_5) / max(dS_5, 1e-9) <= 0.05, f"storage halving drift: {abs(dS_10-dS_5)/max(dS_5,1e-9):.4f}"
    ex_10 = h10.ledger.S2D_m3 + h10.ledger.D2S_m3
    ex_5 = h5.ledger.S2D_m3 + h5.ledger.D2S_m3
    assert ex_5 > 10.0, "scenario must produce meaningful exchange volume for the convergence test"
    assert abs(ex_10 - ex_5) / max(ex_5, 1e-9) <= 0.20, f"exchange halving drift: {abs(ex_10-ex_5)/max(ex_5,1e-9):.4f}"
    assert h10.ledger.status() == "pass"
    assert h5.ledger.status() == "pass"


# ---------------------------------------------------------------------------
# M3-09 — mass conservation (primary acceptance)
# ---------------------------------------------------------------------------

def test_m3_09_mass_conservation(fixtures):
    c = _run(fixtures["clean"], minutes=20, rain=45.0, ext=0.1)
    led = c.ledger
    # full ledger report (not rounded for the calculation)
    print("\n=== M3-09 mass ledger (rain + ext inflow, two-way coupling) ===")
    print(f"rainfall input          = {led.rain_m3:.6f} m3")
    print(f"external inflow         = {led.ext_in_m3:.6f} m3")
    print(f"losses                  = {led.losses_m3:.6f} m3")
    print(f"surface boundary out    = {led.surf_out_m3:.6f} m3")
    print(f"surface storage change  = {led.S_s1 - led.S_s0:.6f} m3")
    print(f"drainage storage change = {led.S_d1 - led.S_d0:.6f} m3 (engine identity)")
    print(f"drainage storage readback= {led.S_d1_readback - led.S_d0:.6f} m3 (diagnostic)")
    print(f"readback discrepancy    = {led.readback_discrepancy:.6f} m3 (documented SWMM quirk)")
    print(f"S2D (surface->drainage) = {led.S2D_m3:.6f} m3")
    print(f"D2S (drainage->surface) = {led.D2S_m3:.6f} m3")
    print(f"flooding export         = {led.flood_export_m3:.6f} m3")
    print(f"drainage outfall        = {led.outfall_m3:.6f} m3")
    print(f"surface residual        = {led.residual_surface:.6e} m3")
    print(f"combined residual       = {led.residual_total:.6e} m3")
    print(f"relative residual       = {led.relative_total():.6e}")
    print(f"SWMM flow routing error = {led.flow_routing_error_pct} %")
    print(f"gate (pass<=1%)         = {led.status()}")
    # acceptance: combined ledger closes within the approved 1% gate
    assert led.status() == "pass"
    assert led.relative_total() <= 0.01
    # exchange is internal: it must cancel in the combined ledger
    assert led.residual_total == pytest.approx(led.residual_surface, abs=0.01)


# ---------------------------------------------------------------------------
# M3-10 — reproducibility
# ---------------------------------------------------------------------------

def test_m3_10_reproducibility(fixtures):
    a = _run(fixtures["clean"], minutes=12, rain=45.0, ext=0.1)
    b = _run(fixtures["clean"], minutes=12, rain=45.0, ext=0.1)
    assert len(a.exchange) == len(b.exchange)
    for xa, xb in zip(a.exchange, b.exchange):
        assert xa.S2D_vol == xb.S2D_vol
        assert xa.D2S_vol == xb.D2S_vol
        assert xa.flood_export_vol == xb.flood_export_vol
    assert np.array_equal(a.surface.depth, b.surface.depth)
    assert a.ledger.residual_total == b.ledger.residual_total


# ---------------------------------------------------------------------------
# M3-11 — coupling failure handling
# ---------------------------------------------------------------------------

def test_m3_11_failure_handling(fixtures, tmp_path):
    # invalid timestep
    with pytest.raises(CouplingError):
        CoupledSpike(build_spike_surface(), fixtures["clean"], INLET, VENT, dt_c=0)
    with pytest.raises(CouplingError):
        CoupledSpike(build_spike_surface(), fixtures["clean"], INLET, VENT, dt_c=-5)
    with pytest.raises(CouplingError):
        CoupledSpike(build_spike_surface(), fixtures["clean"], INLET, VENT, dt_c=2.5)
    # boundary cell as exchange location
    with pytest.raises(CouplingError):
        CoupledSpike(build_spike_surface(), fixtures["clean"], (0, 0), VENT, dt_c=5)
    # negative external inflow
    with pytest.raises(CouplingError):
        _run(fixtures["clean"], minutes=1, ext=-0.1)
    # missing node in INP
    bad = tmp_path / "bad.inp"
    bad.write_text(fixtures["clean"].read_text().replace("ST1", "XX1"))
    with pytest.raises(CouplingError):
        _run(bad, minutes=1)
    # impossible extraction (more than available)
    s = build_spike_surface()
    c = CoupledSpike(s, fixtures["clean"], INLET, VENT, dt_c=5)
    with pytest.raises(CouplingError):
        c._remove_depth(INLET, 10.0)


# ---------------------------------------------------------------------------
# M3-12 — unit consistency
# ---------------------------------------------------------------------------

def test_m3_12_unit_consistency():
    # orifice rate spot value, computed with plain math (independent)
    eta, H = 11.0, 10.0
    expected = CD_ORIFICE * AO_ORIFICE * math.sqrt(2.0 * G * (eta - H))
    assert orifice_exchange_rate(eta, H) == pytest.approx(expected, rel=1e-15)
    assert orifice_exchange_rate(H, eta) == pytest.approx(-expected, rel=1e-15)
    assert orifice_exchange_rate(eta, eta) == 0.0
    # dimension audit: rate [m3/s] * dt [s] = volume [m3]
    assert orifice_exchange_rate(eta, H) * 5.0 > 0
    # rainfall unit conversion: 3.6 mm/h == 1e-6 m/s (exact)
    assert 3.6 / 3600000.0 == pytest.approx(1e-6, abs=1e-18)


# ---------------------------------------------------------------------------
# M3-13 — timestamp / causality
# ---------------------------------------------------------------------------

def test_m3_13_causality(fixtures):
    from pyswmm import Nodes, Simulation

    # empirical regression of the PySWMM stride semantics established in M3:
    # generated_inflow set at iteration i affects the NEXT stride only, so the
    # state read at iteration i never reflects the value being set now.
    with Simulation(str(fixtures["clean"])) as sim:
        sim.step_advance(5)
        st1 = Nodes(sim)["ST1"]
        for i, _ in enumerate(sim):
            st1.generated_inflow(0.05 if i == 0 else 0.0)
            if i == 0:
                assert st1.total_inflow == 0.0, "state at i must not see inflow set at i"
            if i == 1:
                assert st1.total_inflow == 0.05, "inflow set at i applies during stride i->i+1"
            if i >= 1:
                break
    # driver-level: exchange records are strictly time-ordered and causal
    c = _run(fixtures["clean"], minutes=5, rain=30.0)
    ts = [x.t_s for x in c.exchange]
    assert ts == sorted(ts)
    assert all(x.t_s > 0 for x in c.exchange)


# ---------------------------------------------------------------------------
# M3-14 — exchange sign test (regression)
# ---------------------------------------------------------------------------

def test_m3_14_exchange_signs(fixtures):
    cap = _run(fixtures["clean"], minutes=15, rain=60.0)      # surface->drainage
    ret = _run(fixtures["blocked"], minutes=12, ext=0.06)     # drainage->surface
    assert all(x.S2D_vol >= 0 for x in cap.exchange) and cap.ledger.S2D_m3 > 0
    assert cap.ledger.D2S_m3 == 0.0
    assert all(x.D2S_vol >= 0 for x in ret.exchange) and ret.ledger.D2S_m3 > 0
    assert ret.ledger.S2D_m3 == 0.0


# ---------------------------------------------------------------------------
# M3-15 — extreme but valid state
# ---------------------------------------------------------------------------

def test_m3_15_extreme_state(fixtures):
    c = _run(fixtures["blocked"], minutes=15, rain=120.0, ext=0.5)
    led = c.ledger
    # stability: finite everywhere, no exception, physically bounded state
    assert np.all(np.isfinite(c.surface.depth))
    assert np.all(c.surface.depth >= -1e-12)
    assert led.flow_routing_error_pct == 0.0
    assert led.status() in ("pass", "warning")
    # the system responded: drainage return and/or flooding occurred
    assert led.D2S_m3 + led.flood_export_m3 > 0
    print(f"\nM3-15 extreme: max surface depth={c.surface.depth.max():.4f} m, "
          f"max exchange step={max(x.D2S_vol + x.S2D_vol for x in c.exchange):.4f} m3, "
          f"relative residual={led.relative_total():.6f}, status={led.status()}")
