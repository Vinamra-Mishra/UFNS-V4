"""M7-B — Deterministic road graph + Dijkstra shortest-path.

Builds an undirected weighted graph from the synthetic road network:
  - nodes  = road intersections (cell centres, projected metres);
  - edges  = road segments (length m, baseline speed km/h, road_id).

Edge cost is travel time (s) = length / speed; routing modes modify the cost
via the B13 policy (speed factors / exclusion), not by hidden weights.

The graph is deterministic: it is built from the fixed synthetic network, so
identical inputs always yield identical adjacency and shortest paths.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from typing import Callable, Optional

from services.routing.policy import POLICY, PassabilityPolicy, speed_factor
from services.routing.roads import RoadNetwork, RoadSegment, cell_to_projected


@dataclass
class RoadGraph:
    """Undirected road graph. `edges` maps road_id -> segment; `adjacency`
    maps node_id -> list[(neighbour_node_id, road_id)]."""

    network: RoadNetwork
    adjacency: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    node_xy: dict[str, tuple[float, float]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for nid, (r, c) in self.network.nodes.items():
            self.node_xy[nid] = cell_to_projected(r, c)
        for seg in self.network.segments:
            self.adjacency.setdefault(seg.start_node, []).append((seg.end_node, seg.road_id))
            self.adjacency.setdefault(seg.end_node, []).append((seg.start_node, seg.road_id))

    def segment(self, road_id: str) -> RoadSegment:
        return self.network.by_id()[road_id]

    def travel_time_s(self, road_id: str) -> float:
        seg = self.segment(road_id)
        speed_ms = seg.baseline_speed_kmh / 3.6
        return seg.length_m / speed_ms


def build_graph(network: RoadNetwork) -> RoadGraph:
    return RoadGraph(network)


def snap_to_node(graph: RoadGraph, x: float, y: float) -> str:
    """Snap a projected (x, y) coordinate to the nearest intersection node.

    Route endpoints are snapped to the nearest road intersection (M7
    limitation: no mid-edge splitting at 30 m grid scale; documented).
    """
    best = None
    best_d = math.inf
    for nid, (nx, ny) in graph.node_xy.items():
        d = (nx - x) ** 2 + (ny - y) ** 2
        if d < best_d:
            best_d = d
            best = nid
    assert best is not None
    return best


def dijkstra(
    graph: RoadGraph,
    origin_node: str,
    destination_node: str,
    edge_cost: Callable[[str], Optional[float]],
) -> Optional[tuple[float, list[str], list[str]]]:
    """Dijkstra over the graph. Returns (cost, node_path, road_path) or None.

    edge_cost(road_id) -> travel time in seconds, or None to exclude the edge
    (used to close impassable roads). Deterministic: uses a fixed tie-break on
    node id so equal-cost paths resolve identically across runs.
    """
    if origin_node not in graph.adjacency or destination_node not in graph.adjacency:
        return None

    dist: dict[str, float] = {origin_node: 0.0}
    prev: dict[str, tuple[str, str]] = {}  # node -> (prev_node, road_id)
    visited: set[str] = set()
    heap: list[tuple[float, int, str]] = [(0.0, 0, origin_node)]
    counter = 0

    while heap:
        d, _, node = heapq.heappop(heap)
        if node in visited:
            continue
        visited.add(node)
        if node == destination_node:
            break
        for nxt, road_id in graph.adjacency[node]:
            c = edge_cost(road_id)
            if c is None:
                continue
            nd = d + c
            if nxt not in dist or nd < dist[nxt]:
                dist[nxt] = nd
                prev[nxt] = (node, road_id)
                counter += 1
                heapq.heappush(heap, (nd, counter, nxt))

    if destination_node not in dist:
        return None

    # Reconstruct paths.
    node_path = [destination_node]
    road_path: list[str] = []
    cur = destination_node
    while cur != origin_node:
        pnode, road_id = prev[cur]
        road_path.append(road_id)
        node_path.append(pnode)
        cur = pnode
    node_path.reverse()
    road_path.reverse()
    return dist[destination_node], node_path, road_path


def baseline_edge_cost(graph: RoadGraph) -> Callable[[str], Optional[float]]:
    """Edge cost = travel time at baseline speed (no flood constraints)."""

    def cost(road_id: str) -> float:
        return graph.travel_time_s(road_id)

    return cost


def flood_aware_edge_cost(
    graph: RoadGraph,
    impacts: dict[str, object],
    mode: str,
    policy: PassabilityPolicy = POLICY,
) -> Callable[[str], Optional[float]]:
    """Edge cost that consumes actual road-impact information.

    mode == "avoid_impassable": impassable roads excluded; others at baseline
        speed (no penalty).
    mode == "flood_aware": impassable roads excluded; impacted roads penalised
        by the policy speed factor (configurable, documented).

    Unknown roads (no impact record) are treated as DRY at baseline speed so a
    missing impact record cannot silently block a route; a genuinely impassable
    road always has an impact record with classification IMPASSABLE.
    """
    if mode not in ("avoid_impassable", "flood_aware"):
        raise ValueError(f"unknown routing mode: {mode!r}")

    def cost(road_id: str) -> Optional[float]:
        seg = graph.segment(road_id)
        imp = impacts.get(road_id)
        cls = imp.classification if imp is not None else "DRY"
        if cls == "IMPASSABLE":
            return None
        base = seg.length_m / (seg.baseline_speed_kmh / 3.6)
        if mode == "avoid_impassable":
            return base
        return base / speed_factor(cls, policy)

    return cost
