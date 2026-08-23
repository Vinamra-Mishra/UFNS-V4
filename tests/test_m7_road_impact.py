"""M7-A — Road impact test matrix (M7-01 … M7-08).

Covers the deterministic SYNTHETIC road network, geometry validity, dry /
flooded / partial-flood classification, threshold boundaries, impact
reproducibility, and time-dependent impact against the real precomputed S4
depth fields. No simulation is re-run: impacts are derived from stored depth
raster data (or synthetic in-memory grids for the unit cases).
"""

from __future__ import annotations

import numpy as np
import pytest

from services.routing.impact import (
    build_index,
    compute_road_impact,
    metrics_at_lead,
    rasterize_line,
    time_aggregates,
)
from services.routing.policy import POLICY, classify, passability, speed_factor
from services.routing.roads import (
    NETWORK,
    DOMAIN_M,
    ORIGIN_X,
    ORIGIN_Y,
    build_synthetic_network,
)

N = 134


def _grid(value: float) -> np.ndarray:
    return np.full((N, N), value, dtype=np.float64)


def _read_s4_depth(lead: int) -> np.ndarray:
    import rasterio

    with rasterio.open(f"data/demo/m5/s4/depth_t{lead:03d}.tif") as src:
        return src.read(1).astype(np.float64)


# ---------------------------------------------------------------------------
# M7-01 — road fixture deterministic
# ---------------------------------------------------------------------------

def test_m7_01_road_fixture_deterministic():
    a = build_synthetic_network()
    b = build_synthetic_network()
    assert a.fingerprint == b.fingerprint
    assert a.n_segments == b.n_segments == NETWORK.n_segments
    assert [s.road_id for s in a.segments] == [s.road_id for s in b.segments]
    for sa, sb in zip(a.segments, b.segments):
        assert sa.to_dict() == sb.to_dict()


# ---------------------------------------------------------------------------
# M7-02 — road geometry valid
# ---------------------------------------------------------------------------

def test_m7_02_road_geometry_valid():
    net = NETWORK
    assert net.crs == "EPSG:32645"
    assert net.cell_size_m == 30.0
    ids = [s.road_id for s in net.segments]
    assert len(ids) == len(set(ids)), "road ids must be unique"
    for seg in net.segments:
        # endpoints exist as nodes
        assert seg.start_node in net.nodes
        assert seg.end_node in net.nodes
        # geometry has >= 2 vertices, all within the domain
        assert len(seg.geometry) >= 2
        for x, y in seg.geometry:
            assert ORIGIN_X <= x <= ORIGIN_X + DOMAIN_M
            assert ORIGIN_Y <= y <= ORIGIN_Y + DOMAIN_M
        # length matches the euclidean vertex length
        (x1, y1), (x2, y2) = seg.geometry[0], seg.geometry[-1]
        expect = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        assert abs(seg.length_m - expect) < 1e-6
        # source/status labels are honest
        assert seg.source == "SYNTHETIC_DEMO"
        assert "NOT REAL ROAD GEOMETRY" in seg.status
        assert len(seg.fingerprint) == 16


# ---------------------------------------------------------------------------
# M7-03 — dry-road classification
# ---------------------------------------------------------------------------

def test_m7_03_dry_road_classification():
    grid = _grid(0.0)
    for seg in NETWORK.segments:
        imp = compute_road_impact(seg, grid, "S_TEST", 0, "t0")
        assert imp.classification == "DRY"
        assert imp.passability == "PASSABLE"
        assert imp.max_depth_m == 0.0
        assert imp.impacted_fraction == 0.0


# ---------------------------------------------------------------------------
# M7-04 — flooded-road classification
# ---------------------------------------------------------------------------

def test_m7_04_flooded_road_classification():
    grid = _grid(0.7)
    for seg in NETWORK.segments:
        imp = compute_road_impact(seg, grid, "S_TEST", 0, "t0")
        assert imp.classification == "IMPASSABLE"
        assert imp.passability == "IMPASSABLE"
        assert imp.max_depth_m == pytest.approx(0.7)
        assert imp.impacted_fraction == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# M7-05 — partial-road flooding
# ---------------------------------------------------------------------------

def test_m7_05_partial_road_flooding():
    seg = NETWORK.by_id()["R-001"]
    cells = rasterize_line(*seg.start_cell, *seg.end_cell)
    grid = _grid(0.0)
    # flood the first half of the cells
    half = len(cells) // 2
    for r, c in cells[:half]:
        grid[r, c] = 0.7
    imp = compute_road_impact(seg, grid, "S_TEST", 0, "t0")
    assert 0.0 < imp.impacted_fraction < 1.0
    assert imp.classification == "IMPASSABLE"  # max depth is still 0.7
    assert imp.impacted_length_m == pytest.approx(imp.impacted_fraction * seg.length_m)


# ---------------------------------------------------------------------------
# M7-06 — threshold boundary
# ---------------------------------------------------------------------------

def test_m7_06_threshold_boundary():
    # Exact boundaries are deterministic and documented in policy.py.
    assert classify(0.05) == "DRY"
    assert classify(0.050001) == "LOW_IMPACT"
    assert classify(0.15) == "LOW_IMPACT"
    assert classify(0.150001) == "CAUTION"
    assert classify(0.30) == "CAUTION"
    assert classify(0.300001) == "HIGH_IMPACT"
    assert classify(0.50) == "HIGH_IMPACT"
    assert classify(0.500001) == "IMPASSABLE"
    # passability only IMPASSABLE when class is IMPASSABLE
    assert passability("DRY") == "PASSABLE"
    assert passability("IMPASSABLE") == "IMPASSABLE"
    # speed factors exist for every non-impassable class
    for cls in ("DRY", "LOW_IMPACT", "CAUTION", "HIGH_IMPACT"):
        assert speed_factor(cls) > 0.0
    assert POLICY.fingerprint == POLICY.fingerprint
    assert len(POLICY.fingerprint) == 64


# ---------------------------------------------------------------------------
# M7-07 — road-impact reproducibility
# ---------------------------------------------------------------------------

def test_m7_07_road_impact_reproducible():
    grid = _read_s4_depth(110)
    seg = NETWORK.by_id()["R-011"]
    a = compute_road_impact(seg, grid, "S4", 110, "2026-08-21T01:50:00+00:00")
    b = compute_road_impact(seg, grid, "S4", 110, "2026-08-21T01:50:00+00:00")
    assert a.to_dict() == b.to_dict()


# ---------------------------------------------------------------------------
# M7-08 — time-dependent impact (real S4 fields)
# ---------------------------------------------------------------------------

def test_m7_08_time_dependent_impact():
    leads = list(range(0, 181, 5))
    grids = {l: _read_s4_depth(l) for l in leads}
    valid = {l: f"2026-08-21T00:{l:02d}:00+00:00" for l in leads}
    idx = build_index(NETWORK, grids, "S4", valid)

    # t=0 is dry everywhere
    assert all(i.classification == "DRY" for i in idx[0].values())

    # road impact increases over time (peak impassable count > 0)
    ta = time_aggregates(NETWORK, idx)
    assert ta["first_impact_lead_minutes"] is not None
    assert ta["first_impact_lead_minutes"] > 0
    assert ta["peak_impassable_segments"] > 0
    assert ta["peak_impassable_lead_minutes"] is not None

    # a specific central road becomes impassable at some lead, after first impact
    series = [idx[l]["R-011"] for l in leads]
    first_impact = next(i.lead_minutes for i in series if i.classification != "DRY")
    first_impas = next(i.lead_minutes for i in series if i.classification == "IMPASSABLE")
    assert first_impact < first_impas
    # metrics at peak lead report impassable segments
    m = metrics_at_lead(NETWORK, idx[ta["peak_impassable_lead_minutes"]])
    assert m["impassable_segments"] > 0
    assert m["total_segments"] == NETWORK.n_segments
