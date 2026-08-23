"""M7-A — Road network contract + deterministic SYNTHETIC road network.

The repository contains NO real road geometry (verified: `data/` holds only the
synthetic DEM, rainfall fields, drainage INPs and M5 flood GeoTIFFs; no OSM or
other road source is present). Per the M7 requirement, this module therefore
defines a deterministic SYNTHETIC ROAD NETWORK built from the existing
synthetic fixture. It is clearly labelled:

    SYNTHETIC / DEMO DATA / NOT REAL ROAD GEOMETRY

No road is ever presented as real infrastructure (IMPLEMENTATION_SPEC §3,
B02). The network is a regular street grid aligned with the synthetic DEM's
lowered street corridors (the W->E band near row 67 and the N->S band near
column 67) so that the simulated flood field actually intersects road
geometry — which is what makes road-impact and flood-aware routing meaningful
on this fixture.

Coordinate system: the network lives in the same grid as the simulation
(134 x 134 cells @ 30 m, EPSG:32645, origin (300000, 2500000)). Nodes are
intersections placed on grid-cell centres; road segments are straight grid
lines between adjacent intersections. This keeps depth sampling exact (cell
rasterization) and the geometry honest (no sub-grid precision implied).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from services.ingestion.dem import CELL_SIZE_M, DOMAIN_M, GRID_CELLS, ORIGIN_X, ORIGIN_Y
from services.ingestion.crs import WB_PROJECTED_CRS
from services.routing.policy import BASELINE_SPEED_KMH

ROAD_SOURCE = "SYNTHETIC_DEMO"
ROAD_STATUS = "SYNTHETIC / DEMO DATA / NOT REAL ROAD GEOMETRY"

# Street grid: rows (north->south) and columns (west->east) of intersections.
# Row 67 is the DEM's lowered W->E street corridor; column 67 the N->S cross
# corridor. Row 96 crosses the depression basin; the remaining rows/columns
# form a regular grid that stays relatively dry and provides detour capacity.
ROAD_ROWS = (20, 47, 67, 87, 96, 113)
ROAD_COLS = (20, 47, 67, 87, 113)

# Primary corridors (matching the DEM street corridors), everything else
# secondary. Speeds are SYNTHETIC/ASSUMED (see policy.BASELINE_SPEED_KMH).
PRIMARY_ROWS = (67,)
PRIMARY_COLS = (67,)

# Diagonal arterial segments (SYNTHETIC). Endpoints are existing grid nodes;
# each diagonal passes through the centre of the domain (the flood hotspot at
# the street-corridor intersection), so the baseline route has a genuine
# distance shortcut that becomes unavailable when the centre floods. This is
# what produces a real (not contrived) additional-distance detour.
DIAGONAL_SEGMENTS: tuple[tuple[tuple[int, int], tuple[int, int]], ...] = (
    ((20, 20), (47, 47)), ((47, 47), (67, 67)), ((67, 67), (87, 87)), ((87, 87), (113, 113)),
    ((20, 113), (47, 87)), ((47, 87), (67, 67)), ((67, 67), (87, 47)), ((87, 47), (113, 20)),
)


# ---------------------------------------------------------------------------
# Grid <-> projected coordinates (pixel-is-area, matching services/ingestion/dem.py)
# ---------------------------------------------------------------------------

def cell_to_projected(row: float, col: float) -> tuple[float, float]:
    """Grid (row, col) -> projected EPSG:32645 (x, y) at the cell centre."""
    x = ORIGIN_X + (col + 0.5) * CELL_SIZE_M
    y = ORIGIN_Y + DOMAIN_M - (row + 0.5) * CELL_SIZE_M
    return x, y


def projected_to_cell(x: float, y: float) -> tuple[float, float]:
    """Projected (x, y) -> fractional grid (row, col)."""
    col = (x - ORIGIN_X) / CELL_SIZE_M
    row = (ORIGIN_Y + DOMAIN_M - y) / CELL_SIZE_M
    return row, col


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RoadSegment:
    """Typed road contract (M7 §3).

    geometry is a list of [x, y] projected vertices (EPSG:32645, metres).
    grid_cells is the deterministic rasterization (row, col) used for depth
    sampling; it is derived, not stored as primary geometry.
    """

    road_id: str
    geometry: tuple[tuple[float, float], ...]
    road_class: str                       # primary | secondary | local
    length_m: float
    baseline_speed_kmh: float
    source: str
    status: str
    fingerprint: str
    start_node: str
    end_node: str
    start_cell: tuple[int, int]
    end_cell: tuple[int, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "road_id": self.road_id,
            "geometry": [[round(x, 3), round(y, 3)] for x, y in self.geometry],
            "road_class": self.road_class,
            "length_m": round(self.length_m, 3),
            "baseline_speed_kmh": self.baseline_speed_kmh,
            "source": self.source,
            "status": self.status,
            "fingerprint": self.fingerprint,
            "start_node": self.start_node,
            "end_node": self.end_node,
        }


@dataclass(frozen=True)
class RoadNetwork:
    """The complete synthetic road network (nodes + segments)."""

    source: str
    status: str
    crs: str
    cell_size_m: float
    nodes: dict[str, tuple[int, int]]      # node_id -> (row, col)
    segments: tuple[RoadSegment, ...]
    fingerprint: str

    @property
    def n_segments(self) -> int:
        return len(self.segments)

    def by_id(self) -> dict[str, RoadSegment]:
        return {s.road_id: s for s in self.segments}

    def to_dict(self) -> dict[str, Any]:
        nodes = {
            nid: {
                "cell": [r, c],
                "xy": [round(x, 3), round(y, 3)],
            }
            for nid, (r, c) in self.nodes.items()
            for x, y in [cell_to_projected(r, c)]
        }
        return {
            "source": self.source,
            "status": self.status,
            "crs": self.crs,
            "cell_size_m": self.cell_size_m,
            "n_segments": self.n_segments,
            "nodes": nodes,
            "segments": [s.to_dict() for s in self.segments],
            "fingerprint": self.fingerprint,
            "labels": ["SYNTHETIC", "DEMO DATA", "NOT REAL ROAD GEOMETRY"],
        }


def _segment_fingerprint(road_id: str, road_class: str, length_m: float,
                         speed: float, start_node: str, end_node: str,
                         start_cell: tuple[int, int], end_cell: tuple[int, int]) -> str:
    payload = {
        "road_id": road_id,
        "road_class": road_class,
        "length_m": round(length_m, 6),
        "baseline_speed_kmh": speed,
        "start_node": start_node,
        "end_node": end_node,
        "start_cell": start_cell,
        "end_cell": end_cell,
        "source": ROAD_SOURCE,
        "status": ROAD_STATUS,
    }
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


def _road_class(row: int, col: int, horizontal: bool) -> str:
    """Primary for the DEM street corridors, otherwise secondary."""
    if horizontal:
        return "primary" if row in PRIMARY_ROWS else "secondary"
    return "primary" if col in PRIMARY_COLS else "secondary"


def build_synthetic_network() -> RoadNetwork:
    """Build the deterministic SYNTHETIC road network (no randomness)."""
    nodes: dict[str, tuple[int, int]] = {}
    for r in ROAD_ROWS:
        for c in ROAD_COLS:
            nodes[f"N_{r}_{c}"] = (r, c)

    segments: list[RoadSegment] = []
    # Horizontal segments (along rows), then vertical (along columns), then the
    # diagonal arterials — a fixed ordering so road ids are stable/reproducible.
    for r in ROAD_ROWS:
        for c1, c2 in zip(ROAD_COLS, ROAD_COLS[1:]):
            segments.append(_make_segment(r, c1, r, c2, _road_class(r, min(c1, c2), True)))
    for c in ROAD_COLS:
        for r1, r2 in zip(ROAD_ROWS, ROAD_ROWS[1:]):
            segments.append(_make_segment(r1, c, r2, c, _road_class(min(r1, r2), c, False)))
    for (r1, c1), (r2, c2) in DIAGONAL_SEGMENTS:
        segments.append(_make_segment(r1, c1, r2, c2, "primary"))

    # Assign deterministic R-XXX ids in build order.
    for i, seg in enumerate(segments):
        segments[i] = RoadSegment(
            road_id=f"R-{i + 1:03d}",
            geometry=seg.geometry,
            road_class=seg.road_class,
            length_m=seg.length_m,
            baseline_speed_kmh=seg.baseline_speed_kmh,
            source=seg.source,
            status=seg.status,
            fingerprint=_segment_fingerprint(
                f"R-{i + 1:03d}", seg.road_class, seg.length_m,
                seg.baseline_speed_kmh, seg.start_node, seg.end_node,
                seg.start_cell, seg.end_cell,
            ),
            start_node=seg.start_node,
            end_node=seg.end_node,
            start_cell=seg.start_cell,
            end_cell=seg.end_cell,
        )

    network_fp_payload = {
        "road_rows": list(ROAD_ROWS),
        "road_cols": list(ROAD_COLS),
        "primary_rows": list(PRIMARY_ROWS),
        "primary_cols": list(PRIMARY_COLS),
        "diagonal_segments": [[list(a), list(b)] for a, b in DIAGONAL_SEGMENTS],
        "baseline_speed_kmh": BASELINE_SPEED_KMH,
        "cell_size_m": CELL_SIZE_M,
        "grid_cells": GRID_CELLS,
        "crs": WB_PROJECTED_CRS,
        "segments": [s.fingerprint for s in segments],
    }
    network_fp = hashlib.sha256(
        json.dumps(network_fp_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]

    return RoadNetwork(
        source=ROAD_SOURCE,
        status=ROAD_STATUS,
        crs=WB_PROJECTED_CRS,
        cell_size_m=CELL_SIZE_M,
        nodes=nodes,
        segments=tuple(segments),
        fingerprint=network_fp,
    )


def _make_segment(r1: int, c1: int, r2: int, c2: int, road_class: str) -> RoadSegment:
    x1, y1 = cell_to_projected(r1, c1)
    x2, y2 = cell_to_projected(r2, c2)
    length_m = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
    speed = BASELINE_SPEED_KMH[road_class]
    return RoadSegment(
        road_id="",  # filled after ordering
        geometry=((x1, y1), (x2, y2)),
        road_class=road_class,
        length_m=length_m,
        baseline_speed_kmh=speed,
        source=ROAD_SOURCE,
        status=ROAD_STATUS,
        fingerprint="",  # filled after ordering
        start_node=f"N_{r1}_{c1}",
        end_node=f"N_{r2}_{c2}",
        start_cell=(r1, c1),
        end_cell=(r2, c2),
    )


# Module-level singleton (frozen dataclass, built once and cached by import).
NETWORK = build_synthetic_network()
