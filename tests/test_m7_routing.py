"""M7-B — Flood-aware routing test matrix (M7-09 … M7-15).

Covers baseline routing, flood-aware routing, impassable-road avoidance,
route comparison, no-safe-route handling, routing determinism, and the
B13 policy fingerprint. Unit cases use in-memory depth grids; integration
cases read the precomputed S4 depth fields.
"""

from __future__ import annotations

import numpy as np

from services.routing.graph import build_graph, snap_to_node
from services.routing.impact import build_index
from services.routing.policy import POLICY
from services.routing.roads import NETWORK, cell_to_projected
from services.routing.router import compute_route

N = 134


def _grid(value: float) -> np.ndarray:
    return np.full((N, N), value, dtype=np.float64)


def _read_s4_depth(lead: int) -> np.ndarray:
    import rasterio

    with rasterio.open(f"data/demo/m5/s4/depth_t{lead:03d}.tif") as src:
        return src.read(1).astype(np.float64)


def _s4_index():
    leads = list(range(0, 181, 5))
    grids = {l: _read_s4_depth(l) for l in leads}
    valid = {l: f"2026-08-21T00:{l:02d}:00+00:00" for l in leads}
    return build_index(NETWORK, grids, "S4", valid)


NW = cell_to_projected(20, 20)      # north-west corner
SE = cell_to_projected(113, 113)    # south-east corner


# ---------------------------------------------------------------------------
# M7-09 — baseline route
# ---------------------------------------------------------------------------

def test_m7_09_baseline_route():
    graph = build_graph(NETWORK)
    idx = _s4_index()
    r = compute_route(NETWORK, idx[0], NW, SE, "flood_aware", "S4", 0, "t0")
    assert r.status == "OK"
    assert r.baseline is not None
    assert r.baseline.distance_m > 0
    assert r.baseline.estimated_time_s > 0
    assert len(r.baseline.road_ids) > 0
    # snap maps the corners onto the network
    assert snap_to_node(graph, *NW) == "N_20_20"
    assert snap_to_node(graph, *SE) == "N_113_113"


# ---------------------------------------------------------------------------
# M7-10 — flood-aware route (uses actual impact info)
# ---------------------------------------------------------------------------

def test_m7_10_flood_aware_route():
    idx = _s4_index()
    r = compute_route(NETWORK, idx[110], NW, SE, "flood_aware", "S4", 110, "t110")
    assert r.status == "OK"
    assert r.flood_aware is not None
    # at the flood peak the flood-aware route is no faster than baseline
    assert r.flood_aware.estimated_time_s >= r.baseline.estimated_time_s


# ---------------------------------------------------------------------------
# M7-11 — impassable-road avoidance
# ---------------------------------------------------------------------------

def test_m7_11_impassable_road_avoidance():
    # Force the central diagonal impassable: flood every cell on R-051/R-052.
    grid = _grid(0.0)
    for rid in ("R-051", "R-052"):
        seg = NETWORK.by_id()[rid]
        from services.routing.impact import rasterize_line

        for (r, c) in rasterize_line(*seg.start_cell, *seg.end_cell):
            grid[r, c] = 0.7
    from services.routing.impact import compute_road_impact

    impacts = {s.road_id: compute_road_impact(s, grid, "S_T", 0, "t0") for s in NETWORK.segments}
    r = compute_route(NETWORK, impacts, NW, SE, "flood_aware", "S_T", 0, "t0")
    assert r.status == "OK"
    # the diagonal shortcut is flooded, so the flood-aware route avoids it
    assert "R-051" not in r.flood_aware.road_ids
    assert "R-052" not in r.flood_aware.road_ids
    assert "R-051" in r.baseline.road_ids or "R-052" in r.baseline.road_ids
    # the avoided roads are reported as flooded
    assert set(r.difference["flooded_roads_avoided"]) & {"R-051", "R-052"}


# ---------------------------------------------------------------------------
# M7-12 — route comparison
# ---------------------------------------------------------------------------

def test_m7_12_route_comparison():
    idx = _s4_index()
    r = compute_route(NETWORK, idx[110], NW, SE, "flood_aware", "S4", 110, "t110")
    assert r.status == "OK"
    d = r.difference
    assert d["additional_time_s"] >= 0
    assert d["additional_distance_m"] >= 0
    assert "avoided_roads" in d
    assert "flooded_roads_avoided" in d
    # explanation is data-grounded, not empty
    assert r.explanation["summary"]
    assert r.policy_version == "B13-DEMO-V1"
    assert r.policy_fingerprint == POLICY.fingerprint


# ---------------------------------------------------------------------------
# M7-13 — no-safe-route handling
# ---------------------------------------------------------------------------

def test_m7_13_no_safe_route_handling():
    # Flood every road -> no passable route exists.
    grid = _grid(0.7)
    from services.routing.impact import compute_road_impact

    impacts = {s.road_id: compute_road_impact(s, grid, "S_T", 0, "t0") for s in NETWORK.segments}
    r = compute_route(NETWORK, impacts, NW, SE, "flood_aware", "S_T", 0, "t0")
    assert r.status == "NO_SAFE_ROUTE"
    assert r.flood_aware is None
    assert "No route satisfies" in r.explanation["summary"] or "No route" in r.explanation["summary"]
    # never silently falls back: the result is explicit about the failure
    assert r.to_dict()["status"] == "NO_SAFE_ROUTE"


# ---------------------------------------------------------------------------
# M7-14 — routing determinism
# ---------------------------------------------------------------------------

def test_m7_14_routing_determinism():
    idx = _s4_index()
    a = compute_route(NETWORK, idx[110], NW, SE, "flood_aware", "S4", 110, "t110")
    b = compute_route(NETWORK, idx[110], NW, SE, "flood_aware", "S4", 110, "t110")
    assert a.to_dict() == b.to_dict()
    # modes are deterministic and distinct in semantics
    c = compute_route(NETWORK, idx[110], NW, SE, "avoid_impassable", "S4", 110, "t110")
    assert c.to_dict() == compute_route(
        NETWORK, idx[110], NW, SE, "avoid_impassable", "S4", 110, "t110").to_dict()


# ---------------------------------------------------------------------------
# M7-15 — policy fingerprint
# ---------------------------------------------------------------------------

def test_m7_15_policy_fingerprint():
    p = POLICY.to_dict()
    assert p["policy_id"] == "B13-DEMO-V1"
    assert p["status"] == "PROVISIONAL_DEMONSTRATION"
    assert p["approved"] is False
    assert p["version"] == 1
    assert set(p["thresholds"].keys()) == {"dry_m", "low_m", "caution_m", "impassable_m"}
    assert p["thresholds"]["impassable_m"] > p["thresholds"]["caution_m"] > p["thresholds"]["low_m"] > p["thresholds"]["dry_m"]
    assert len(p["fingerprint"]) == 64
    assert "Not an operational safety recommendation" in p["disclaimer"]
