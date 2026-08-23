"""M7-A — Road flood-depth sampling + time-dependent road impact.

Road impact is derived ONLY from the simulated flood-depth fields (the M5
depth GeoTIFFs). Roads are never coloured by mere overlap with a flood-extent
polygon: for every road segment we (1) rasterize its geometry onto the
simulation grid, (2) sample the depth field at those cells, (3) compute
depth statistics, (4) compute the impacted fraction/length, (5) classify the
road and (6) determine passability — all against the centralized, versioned
B13-DEMO-V1 policy (services/routing/policy.py).

Sampling method (documented; see docs/M7_ROAD_IMPACT_ROUTING.md §6):
  - A road segment is a straight line between two intersection cells on the
    same row or column of the 30 m grid. The segment is rasterized to the
    ordered list of grid cells it passes through (Bresenham, inclusive).
  - Each rasterized cell contributes its simulated depth once. Because each
    Bresenham step advances one cell along the dominant axis, cells are
    ~equally spaced along the segment, so the unweighted mean depth
    approximates the length-weighted mean depth (no sub-cell interpolation is
    implied — the model itself is 30 m resolution).
  - max_depth = max of sampled depths; mean_depth = mean of sampled depths;
    impacted_fraction = (cells with depth > impacted threshold) / n_cells;
    impacted_length_m = impacted_fraction * length_m.

The result is deterministic: identical depth fields -> identical impacts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

import numpy as np

from services.routing.policy import POLICY, PassabilityPolicy, classify, passability
from services.routing.roads import RoadNetwork, RoadSegment


@dataclass(frozen=True)
class RoadImpact:
    """Typed road-impact contract (M7 §3)."""

    road_id: str
    scenario_id: str
    snapshot_time: str                 # valid_time (RFC 3339)
    lead_minutes: int
    max_depth_m: float
    mean_depth_m: float
    impacted_fraction: float
    impacted_length_m: float
    classification: str
    passability: str
    reason: str
    policy_version: str
    policy_fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "road_id": self.road_id,
            "scenario_id": self.scenario_id,
            "snapshot_time": self.snapshot_time,
            "lead_minutes": self.lead_minutes,
            "max_depth_m": round(self.max_depth_m, 4),
            "mean_depth_m": round(self.mean_depth_m, 4),
            "impacted_fraction": round(self.impacted_fraction, 4),
            "impacted_length_m": round(self.impacted_length_m, 3),
            "classification": self.classification,
            "passability": self.passability,
            "reason": self.reason,
            "policy_version": self.policy_version,
            "policy_fingerprint": self.policy_fingerprint,
        }


# ---------------------------------------------------------------------------
# Deterministic line rasterization (Bresenham, inclusive)
# ---------------------------------------------------------------------------

def rasterize_line(r1: int, c1: int, r2: int, c2: int) -> list[tuple[int, int]]:
    """Rasterize a grid line from (r1,c1) to (r2,c2) inclusive.

    Standard integer Bresenham; deterministic for any input. For grid-aligned
    road segments this yields exactly the cells the segment passes through.
    """
    cells: list[tuple[int, int]] = []
    dr = abs(r2 - r1)
    dc = abs(c2 - c1)
    sr = 1 if r1 < r2 else -1
    sc = 1 if c1 < c2 else -1
    err = dr - dc
    r, c = r1, c1
    while True:
        cells.append((r, c))
        if r == r2 and c == c2:
            break
        e2 = 2 * err
        if e2 > -dc:
            err -= dc
            r += sr
        if e2 < dr:
            err += dr
            c += sc
    return cells


# ---------------------------------------------------------------------------
# Depth sampling + impact
# ---------------------------------------------------------------------------

def sample_depths(depth_grid: np.ndarray, cells: Iterable[tuple[int, int]]) -> np.ndarray:
    """Gather the simulated depths (m) at the rasterized cells of a segment."""
    vals = []
    h, w = depth_grid.shape
    for r, c in cells:
        if not (0 <= r < h and 0 <= c < w):
            # Segment endpoints are validated to lie inside the grid; this is a
            # defensive guard, never a silent clamp.
            raise ValueError(f"road cell {(r, c)} outside depth grid {depth_grid.shape}")
        vals.append(float(depth_grid[r, c]))
    return np.asarray(vals, dtype=np.float64)


def compute_road_impact(
    segment: RoadSegment,
    depth_grid: np.ndarray,
    scenario_id: str,
    lead_minutes: int,
    snapshot_time: str,
    policy: PassabilityPolicy = POLICY,
) -> RoadImpact:
    """Compute the RoadImpact for one segment against one flood snapshot."""
    cells = rasterize_line(*segment.start_cell, *segment.end_cell)
    depths = sample_depths(depth_grid, cells)
    n = len(depths)
    max_d = float(depths.max())
    mean_d = float(depths.mean())
    impacted = int(np.count_nonzero(depths > policy.impacted_depth_threshold_m))
    impacted_fraction = impacted / n if n else 0.0
    impacted_length_m = impacted_fraction * segment.length_m
    cls = classify(max_d, policy)
    pas = passability(cls)
    reason = _reason(cls, max_d, policy)
    return RoadImpact(
        road_id=segment.road_id,
        scenario_id=scenario_id,
        snapshot_time=snapshot_time,
        lead_minutes=lead_minutes,
        max_depth_m=max_d,
        mean_depth_m=mean_d,
        impacted_fraction=impacted_fraction,
        impacted_length_m=impacted_length_m,
        classification=cls,
        passability=pas,
        reason=reason,
        policy_version=policy.policy_id,
        policy_fingerprint=policy.fingerprint,
    )


def _reason(cls: str, max_d: float, policy: PassabilityPolicy) -> str:
    t = policy.thresholds
    if cls == "DRY":
        return f"max depth {max_d:.3f} m is at or below the dry threshold {t['dry_m']:.2f} m"
    if cls == "LOW_IMPACT":
        return (f"max depth {max_d:.3f} m is low impact "
                f"({t['dry_m']:.2f}–{t['low_m']:.2f} m)")
    if cls == "CAUTION":
        return (f"max depth {max_d:.3f} m warrants caution "
                f"({t['low_m']:.2f}–{t['caution_m']:.2f} m)")
    if cls == "HIGH_IMPACT":
        return (f"max depth {max_d:.3f} m is high impact "
                f"({t['caution_m']:.2f}–{t['impassable_m']:.2f} m)")
    return (f"max depth {max_d:.3f} m exceeds the impassable threshold "
            f"{t['impassable_m']:.2f} m")


# ---------------------------------------------------------------------------
# Time-dependent index
# ---------------------------------------------------------------------------

def build_index(
    network: RoadNetwork,
    depth_grids: dict[int, np.ndarray],
    scenario_id: str,
    valid_times: dict[int, str],
    policy: PassabilityPolicy = POLICY,
) -> dict[int, dict[str, RoadImpact]]:
    """Compute RoadImpact for every segment at every available lead.

    Returns {lead_minutes: {road_id: RoadImpact}}. Deterministic.
    """
    index: dict[int, dict[str, RoadImpact]] = {}
    for lead in sorted(depth_grids):
        grid = depth_grids[lead]
        t = valid_times.get(lead, "")
        index[lead] = {
            seg.road_id: compute_road_impact(seg, grid, scenario_id, lead, t, policy)
            for seg in network.segments
        }
    return index


# ---------------------------------------------------------------------------
# Scenario-level metrics
# ---------------------------------------------------------------------------

def metrics_at_lead(network: RoadNetwork, impacts: dict[str, RoadImpact]) -> dict[str, Any]:
    """Scenario-level road metrics at one snapshot (M7 §8)."""
    total = len(network.segments)
    impacted = sum(1 for i in impacts.values() if i.classification != "DRY")
    high = sum(1 for i in impacts.values()
               if i.classification in ("HIGH_IMPACT", "IMPASSABLE"))
    impassable = sum(1 for i in impacts.values() if i.classification == "IMPASSABLE")
    affected_length = sum(i.impacted_length_m for i in impacts.values())
    max_road_depth = max((i.max_depth_m for i in impacts.values()), default=0.0)
    return {
        "total_segments": total,
        "impacted_segments": impacted,
        "high_impact_segments": high,
        "impassable_segments": impassable,
        "affected_road_length_m": round(affected_length, 3),
        "max_road_depth_m": round(max_road_depth, 4),
    }


def time_aggregates(
    network: RoadNetwork, index: dict[int, dict[str, RoadImpact]]
) -> dict[str, Any]:
    """Scenario-wide road-impact time aggregates (first/peak impact time)."""
    first_impact = None
    peak_impact = None
    peak_count = -1
    for lead in sorted(index):
        impacts = index[lead]
        n_impacted = sum(1 for i in impacts.values() if i.classification != "DRY")
        n_impas = sum(1 for i in impacts.values() if i.classification == "IMPASSABLE")
        if n_impacted > 0 and first_impact is None:
            first_impact = lead
        if n_impas > peak_count:
            peak_count = n_impas
            peak_impact = lead
    return {
        "first_impact_lead_minutes": first_impact,
        "peak_impassable_lead_minutes": peak_impact,
        "peak_impassable_segments": peak_count if peak_count >= 0 else 0,
    }
