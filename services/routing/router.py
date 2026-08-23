"""M7-B — Baseline + flood-aware routing and route comparison.

Computes two routes on the same deterministic road graph:
  - baseline ("Normal"): shortest travel time with NO flood constraints;
  - flood-aware: shortest travel time using actual road-impact information
    (impassable roads excluded; impacted roads penalised per the B13 policy).

The result includes the distance/time/geometry of both routes, the difference
(additional distance/time), the avoided roads, and a data-grounded explanation
built from the avoided roads' actual impact classifications — never a generic
text disconnected from the routing data.

No-safe-route handling: if no route satisfies the selected passability policy,
the result reports NO_SAFE_ROUTE and does NOT silently fall back to the
baseline route (M7 §14).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from services.routing.graph import (
    RoadGraph,
    baseline_edge_cost,
    build_graph,
    dijkstra,
    flood_aware_edge_cost,
    snap_to_node,
)
from services.routing.policy import POLICY, PassabilityPolicy
from services.routing.roads import RoadNetwork


@dataclass
class Route:
    """One computed route (baseline or flood-aware)."""

    distance_m: float
    estimated_time_s: float
    road_ids: list[str]
    geometry: list[list[float]]
    node_path: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "distance_m": round(self.distance_m, 3),
            "estimated_time_s": round(self.estimated_time_s, 3),
            "road_ids": list(self.road_ids),
            "geometry": [[round(x, 3), round(y, 3)] for x, y in self.geometry],
        }


@dataclass
class RouteResult:
    """Typed route-result contract (M7 §13)."""

    scenario_id: str
    lead_minutes: int
    snapshot_time: str
    mode: str
    origin: dict[str, Any]
    destination: dict[str, Any]
    baseline: Optional[Route]
    flood_aware: Optional[Route]
    status: str                       # "OK" | "NO_SAFE_ROUTE"
    difference: dict[str, Any]
    explanation: dict[str, Any]
    policy_version: str
    policy_fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "lead_minutes": self.lead_minutes,
            "snapshot_time": self.snapshot_time,
            "mode": self.mode,
            "origin": self.origin,
            "destination": self.destination,
            "status": self.status,
            "baseline": self.baseline.to_dict() if self.baseline else None,
            "flood_aware": self.flood_aware.to_dict() if self.flood_aware else None,
            "difference": self.difference,
            "explanation": self.explanation,
            "policy_version": self.policy_version,
            "policy_fingerprint": self.policy_fingerprint,
            "labels": ["SYNTHETIC", "SIMULATED", "PROVISIONAL"],
        }


def _route_geometry(graph: RoadGraph, node_path: list[str]) -> list[list[float]]:
    return [[round(x, 3), round(y, 3)] for x, y in (graph.node_xy[n] for n in node_path)]


def _route_distance(graph: RoadGraph, road_ids: list[str]) -> float:
    return sum(graph.segment(rid).length_m for rid in road_ids)


def compute_route(
    network: RoadNetwork,
    impacts: dict[str, Any],
    origin_xy: tuple[float, float],
    destination_xy: tuple[float, float],
    mode: str,
    scenario_id: str,
    lead_minutes: int,
    snapshot_time: str,
    policy: PassabilityPolicy = POLICY,
) -> RouteResult:
    """Compute baseline + flood-aware routes and their comparison."""
    graph = build_graph(network)
    o_node = snap_to_node(graph, *origin_xy)
    d_node = snap_to_node(graph, *destination_xy)

    origin = {"node": o_node, "xy": [round(origin_xy[0], 3), round(origin_xy[1], 3)]}
    destination = {"node": d_node, "xy": [round(destination_xy[0], 3), round(destination_xy[1], 3)]}

    # Baseline (no flood constraints).
    base = dijkstra(graph, o_node, d_node, baseline_edge_cost(graph))
    baseline = _make_route(graph, base)

    # Flood-aware (mode controls exclusion vs penalty).
    faw = dijkstra(graph, o_node, d_node, flood_aware_edge_cost(graph, impacts, mode, policy))
    flood_aware = _make_route(graph, faw)

    if flood_aware is None:
        return RouteResult(
            scenario_id=scenario_id, lead_minutes=lead_minutes, snapshot_time=snapshot_time,
            mode=mode, origin=origin, destination=destination,
            baseline=baseline, flood_aware=None,
            status="NO_SAFE_ROUTE",
            difference={}, explanation=_no_route_explanation(mode, policy),
            policy_version=policy.policy_id, policy_fingerprint=policy.fingerprint,
        )

    diff, explanation = _difference_and_explanation(graph, baseline, flood_aware, impacts)
    return RouteResult(
        scenario_id=scenario_id, lead_minutes=lead_minutes, snapshot_time=snapshot_time,
        mode=mode, origin=origin, destination=destination,
        baseline=baseline, flood_aware=flood_aware,
        status="OK", difference=diff, explanation=explanation,
        policy_version=policy.policy_id, policy_fingerprint=policy.fingerprint,
    )


def _make_route(graph: RoadGraph, res: Optional[tuple[float, list[str], list[str]]]) -> Optional[Route]:
    if res is None:
        return None
    cost, node_path, road_path = res
    return Route(
        distance_m=_route_distance(graph, road_path),
        estimated_time_s=cost,
        road_ids=road_path,
        geometry=_route_geometry(graph, node_path),
        node_path=node_path,
    )


def _difference_and_explanation(
    graph: RoadGraph,
    baseline: Optional[Route],
    flood_aware: Route,
    impacts: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    base_ids = set(baseline.road_ids) if baseline else set()
    faw_ids = set(flood_aware.road_ids)
    avoided = sorted(base_ids - faw_ids)              # roads the flood-aware route avoids
    flooded_avoided = [rid for rid in avoided
                       if impacts.get(rid) is not None
                       and impacts[rid].classification != "DRY"]

    add_dist = flood_aware.distance_m - (baseline.distance_m if baseline else 0.0)
    add_time = flood_aware.estimated_time_s - (baseline.estimated_time_s if baseline else 0.0)

    difference = {
        "additional_distance_m": round(add_dist, 3),
        "additional_time_s": round(add_time, 3),
        "avoided_roads": avoided,
        "flooded_roads_avoided": flooded_avoided,
    }

    reasons = []
    for rid in avoided:
        imp = impacts.get(rid)
        if imp is None:
            reasons.append(f"{rid} (no impact record)")
        else:
            reasons.append(f"{rid} ({imp.classification}, max depth {imp.max_depth_m:.2f} m)")

    if flooded_avoided:
        summary = (f"Route changed because {', '.join(flooded_avoided)} exceeded the selected "
                   f"passability threshold at this snapshot.")
    elif avoided:
        summary = "Route changed to avoid roads excluded by the selected passability policy."
    else:
        summary = "Flood-aware route follows the same roads as the normal route."
    explanation = {"summary": summary, "avoided_road_details": reasons}
    return difference, explanation


def _no_route_explanation(mode: str, policy: PassabilityPolicy) -> dict[str, Any]:
    return {
        "summary": (
            f"No route satisfies the selected passability policy "
            f"({policy.policy_id}, mode {mode}) at the selected scenario and "
            "simulation time."
        ),
        "avoided_road_details": [],
    }
