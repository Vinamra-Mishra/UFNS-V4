"""M7 — Road impact + flood-aware routing (UFNS SIH26085).

This package implements the M7 milestone on top of the precomputed M5 flood
snapshots. It does NOT re-run the hydraulic simulation and does NOT modify any
M1-M6 scientific semantics.

Components:
  - policy.py  — B13 vehicle passability policy (B13-DEMO-V1, PROVISIONAL)
  - roads.py   — RoadSegment contract + deterministic SYNTHETIC road network
  - impact.py  — flood-depth sampling along roads + time-dependent RoadImpact
  - graph.py   — deterministic road graph (nodes/edges/adjacency + Dijkstra)
  - router.py  — baseline + flood-aware routing + route comparison

Honesty guarantees (IMPLEMENTATION_SPEC §3, §4 B13):
  - the road network is SYNTHETIC DEMO DATA (NOT REAL ROAD GEOMETRY);
  - road impact is derived ONLY from the simulated flood-depth fields;
  - the B13 passability policy is a PROVISIONAL DEMONSTRATION POLICY, not an
    expert-approved or operational safety recommendation.
"""

MODEL_VERSION = "m7-road-routing-v1"
