"""M7 API layer — road network, road impact, and routing (cached; no re-run).

Wraps the deterministic M7 services (services/routing/*) over the precomputed
M5 depth GeoTIFFs. The hydraulic simulation is NEVER re-run to serve a
request; road impacts are derived deterministically from the stored depth
fields and cached in memory.

Performance (M7 §38): depth rasters are read once per (scenario, lead) and
cached; the per-scenario road-impact index is computed once and cached; the
road graph and network are module singletons. Timeline scrubbing therefore
does no simulation work — it reads the cached depth grid and precomputed
impact index.
"""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Any

import numpy as np

from apps.api import store
from apps.api.render import read_depth_tif
from services.ingestion.dem import CELL_SIZE_M, DOMAIN_M, GRID_CELLS, ORIGIN_X, ORIGIN_Y
from services.rainfall.fields import render_interval
from services.routing.graph import build_graph
from services.routing.impact import (
    build_index,
    metrics_at_lead,
    time_aggregates,
)
from services.routing.policy import POLICY
from services.routing.roads import NETWORK, cell_to_projected
from services.routing.router import compute_route
from services.scenarios.registry import M5_SCENARIOS

LEADS = tuple(range(0, 181, 5))


# ---------------------------------------------------------------------------
# Grid metadata
# ---------------------------------------------------------------------------

def grid_metadata() -> dict[str, Any]:
    """Grid bounds/affine so the frontend can map pixels <-> metres <-> cells."""
    return {
        "width": GRID_CELLS,
        "height": GRID_CELLS,
        "cell_size_m": CELL_SIZE_M,
        "crs": "EPSG:32645",
        "origin_x": ORIGIN_X,
        "origin_y": ORIGIN_Y,
        "domain_m": DOMAIN_M,
        "bounds": [ORIGIN_X, ORIGIN_Y, ORIGIN_X + DOMAIN_M, ORIGIN_Y + DOMAIN_M],
    }


# ---------------------------------------------------------------------------
# Road network / policy
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def road_network() -> dict[str, Any]:
    return NETWORK.to_dict()


def policy() -> dict[str, Any]:
    return POLICY.to_dict()


# ---------------------------------------------------------------------------
# Depth grids + impact index (cached)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=512)
def depth_grid(sid: str, lead: int) -> np.ndarray:
    """Cached float64 depth grid (m) for one scenario snapshot."""
    path = store.artifact_tif_path(sid, lead)
    return read_depth_tif(str(path))


def _valid_times(sid: str) -> dict[int, str]:
    result = store.scenario_result(sid)
    out: dict[int, str] = {}
    for snap in result.get("snapshot_inventory", []):
        out[snap["lead_minutes"]] = snap["valid_time"]
    return out


@lru_cache(maxsize=4)
def impact_index(sid: str) -> dict[int, dict[str, Any]]:
    """Full per-scenario road-impact index (lead -> {road_id -> RoadImpact})."""
    grids = {lead: depth_grid(sid, lead) for lead in LEADS}
    idx = build_index(NETWORK, grids, sid, _valid_times(sid))
    # Return raw RoadImpact objects (callers dict-ify as needed).
    return idx


def impacts_at(sid: str, lead: int) -> dict[str, Any]:
    return impact_index(sid)[lead]


def road_metrics(sid: str, lead: int) -> dict[str, Any]:
    idx = impact_index(sid)
    m = metrics_at_lead(NETWORK, idx[lead])
    m.update(time_aggregates(NETWORK, idx))
    return m


def road_impact_timeline(sid: str, road_id: str) -> dict[str, Any]:
    idx = impact_index(sid)
    seg = NETWORK.by_id().get(road_id)
    if seg is None:
        raise KeyError(road_id)
    series = [idx[lead][road_id].to_dict() for lead in sorted(idx)]
    # Derived "first impacted / impassable" lead, only if the data supports it.
    first_impacted = next(
        (s["lead_minutes"] for s in series if s["classification"] != "DRY"), None)
    first_impassable = next(
        (s["lead_minutes"] for s in series if s["classification"] == "IMPASSABLE"), None)
    return {
        "road_id": road_id,
        "scenario_id": sid,
        "road_class": seg.road_class,
        "length_m": round(seg.length_m, 3),
        "baseline_speed_kmh": seg.baseline_speed_kmh,
        "geometry": [[round(x, 3), round(y, 3)] for x, y in seg.geometry],
        "series": series,
        "first_impacted_lead_minutes": first_impacted,
        "first_impassable_lead_minutes": first_impassable,
        "source": seg.source,
        "status": seg.status,
        "policy_version": POLICY.policy_id,
        "policy_fingerprint": POLICY.fingerprint,
    }


# ---------------------------------------------------------------------------
# Frame (single efficient timeline payload for the map)
# ---------------------------------------------------------------------------

def frame(sid: str, lead: int) -> dict[str, Any]:
    """Everything the map needs for one (scenario, lead) — one round-trip."""
    grid = depth_grid(sid, lead)
    impacts = impacts_at(sid, lead)
    result = store.scenario_result(sid)
    meta = store.scenario_metadata(sid)
    snap = next((s for s in result.get("snapshot_inventory", [])
                 if s["lead_minutes"] == lead), {})

    depth_flat = [round(float(v), 4) for v in grid.reshape(-1)]
    rain = rainfall_summary(sid, lead)

    return {
        "scenario_id": sid,
        "lead_minutes": lead,
        "valid_time": snap.get("valid_time"),
        "extent_threshold_m": meta.get("extent_threshold_m", 0.05),
        "grid": grid_metadata(),
        "depth": depth_flat,
        "depth_units": "m",
        "drainage": {
            "st1_head_m": snap.get("st1_head_m"),
            "surcharged": snap.get("surcharged"),
            "outfall_cum_m3": snap.get("outfall_cum_m3"),
            "S2D_cum_m3": snap.get("S2D_cum_m3"),
            "D2S_cum_m3": snap.get("D2S_cum_m3"),
            "surface_storage_m3": snap.get("surface_storage_m3"),
        },
        "rainfall": rain,
        "road_impacts": [
            {
                "road_id": i.road_id,
                "classification": i.classification,
                "passability": i.passability,
                "max_depth_m": round(i.max_depth_m, 4),
                "impacted_fraction": round(i.impacted_fraction, 4),
            }
            for i in impacts.values()
        ],
        "road_metrics": road_metrics(sid, lead),
        "policy": POLICY.to_dict(),
        "labels": ["SYNTHETIC", "SIMULATED", "PROVISIONAL", "NOT FOR OPERATIONAL USE"],
    }


def rainfall_summary(sid: str, lead: int) -> dict[str, Any]:
    sc = M5_SCENARIOS[sid]
    prof = sc.rainfall_profile
    interval_min = prof.temporal_resolution_minutes
    idx = min(lead // interval_min, len(prof.intensities_mmh) - 1)
    rate = prof.intensities_mmh[idx]
    return {
        "total_mm": prof.total_depth_mm,
        "current_intensity_mmh": round(float(rate), 3),
        "interval_index": idx,
        "status": "PROVISIONAL",
        "d016_status": prof.d016_review_status,
    }


@lru_cache(maxsize=512)
def rainfall_grid(sid: str, lead: int) -> dict[str, Any]:
    """Deterministic rainfall forcing field (mm/h) for one scenario/lead."""
    sc = M5_SCENARIOS[sid]
    prof = sc.rainfall_profile
    interval_min = prof.temporal_resolution_minutes
    idx = min(lead // interval_min, len(prof.intensities_mmh) - 1)
    rate = prof.intensities_mmh[idx]
    field = render_interval((GRID_CELLS, GRID_CELLS), sc.spatial_pattern, rate, idx, sc.seed)
    return {
        "scenario_id": sid,
        "lead_minutes": lead,
        "interval_index": idx,
        "intensity_mmh": round(float(rate), 3),
        "grid": grid_metadata(),
        "values": [round(float(v), 3) for v in field.reshape(-1)],
        "units": "mm/h",
        "status": "PROVISIONAL",
        "labels": ["SYNTHETIC", "SIMULATED", "PROVISIONAL"],
    }


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def compute_route_request(
    sid: str,
    lead: int,
    origin: list[float],
    destination: list[float],
    mode: str,
) -> dict[str, Any]:
    """Compute baseline + flood-aware routes for a validated request."""
    impacts = impacts_at(sid, lead)
    result = store.scenario_result(sid)
    snap = next((s for s in result.get("snapshot_inventory", [])
                 if s["lead_minutes"] == lead), {})
    r = compute_route(
        NETWORK,
        impacts,
        (float(origin[0]), float(origin[1])),
        (float(destination[0]), float(destination[1])),
        mode,
        sid,
        lead,
        snap.get("valid_time", ""),
    )
    return r.to_dict()


def network_nodes_xy() -> dict[str, list[float]]:
    """node_id -> [x, y] for the frontend (used to hint selectable endpoints)."""
    return {
        nid: [round(x, 3), round(y, 3)]
        for nid, (r, c) in NETWORK.nodes.items()
        for x, y in [cell_to_projected(r, c)]
    }


@lru_cache(maxsize=1)
def drainage_points() -> dict[str, Any]:
    """Inlet + vent cells (projected coords) for the drainage map layer."""
    from services.ingestion.dem import synthetic_dem
    from services.simulation.engine import FIXTURE_VENT_CELL, fixture_inlet_cells

    dem = synthetic_dem()
    inlets = fixture_inlet_cells(dem)
    vent_xy = cell_to_projected(*FIXTURE_VENT_CELL)
    return {
        "inlets": [[round(x, 3), round(y, 3)]
                   for r, c in inlets for x, y in [cell_to_projected(r, c)]],
        "vent": [round(vent_xy[0], 3), round(vent_xy[1], 3)],
        "vent_cell": list(FIXTURE_VENT_CELL),
        "labels": ["SYNTHETIC", "ASSUMED", "NOT REAL DRAINAGE"],
    }
