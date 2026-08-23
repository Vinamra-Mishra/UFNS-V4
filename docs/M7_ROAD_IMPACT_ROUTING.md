# M7 — Road Impact + Flood-Aware Routing + Interactive Flood UI + UX Upgrade

**Status:** DONE (technical gates PASS; B13 PROVISIONAL DEMONSTRATION, D-016 unchanged)
**Model version:** `m7-road-routing-v1`
**Depends on:** M1–M6 (precomputed M5 flood snapshots; no simulation re-run)
**Tests:** `tests/test_m7_road_impact.py`, `tests/test_m7_routing.py`, `tests/test_m7_api.py` (24 tests)

---

## 1. Objective

Upgrade UFNS from the M6 static-PNG dashboard to a genuinely interactive,
time-evolving flood decision-support application: an interactive flood map,
time-dependent road impact, flood-aware routing with a normal-vs-aware
comparison, and a four-question UX:

```text
1. What is happening?         (scenario + live metrics)
2. Where is it happening?     (interactive flood map + timeline)
3. What infrastructure is affected?   (road impact + road inspection)
4. What route should I take?  (normal vs flood-aware routing)
```

The goal is **not** to look impressive; it is to make the existing M1–M6
scientific work usable, interactive, auditable, and visually understandable,
with every road/flood/routing number traceable to an actual simulation state
and an explicitly documented policy.

## 2. Architecture

```text
Python simulation (unchanged M4/M5)
      ↓
precomputed depth GeoTIFFs (data/demo/m5/s*/depth_t*.tif)
      ↓
services/routing/*  (roads, policy, impact, graph, router — pure Python)
      ↓
apps/api/impacts.py (cached derivation layer; NO simulation re-run)
      ↓
FastAPI (apps/api/app.py)
      ↓
single-file interactive dashboard (apps/web/index.html, canvas map)
```

Science stays in Python (Landlab/SWMM/M4/M5 are untouched). The browser
visualizes authoritative outputs — it never recreates the hydraulic model.

## 3. Road data

The repository contains **no real road geometry** (verified during M7
inspection: `data/` holds only the synthetic DEM, rainfall fields, drainage
INPs and M5 flood GeoTIFFs). Per the M7 requirement, a deterministic
**SYNTHETIC ROAD NETWORK** was therefore created, clearly labelled:

```text
SYNTHETIC / DEMO DATA / NOT REAL ROAD GEOMETRY
```

Design (deterministic, seeded-free — fully procedural, no randomness):
a street grid at rows `(20, 47, 67, 87, 96, 113)` and columns
`(20, 47, 67, 87, 113)` (30 m cells, EPSG:32645), plus two diagonal arterials
through the centre. Row 67 / column 67 align with the synthetic DEM's lowered
street corridors (the flood hotspot), and row 96 crosses the depression basin.
This is what makes the simulated flood field actually intersect road geometry.
Network: **30 intersections, 57 segments** (24 horizontal + 25 vertical + 8
diagonal).

## 4. Provenance

Every road segment and every impact result carries provenance:

- road `source = SYNTHETIC_DEMO`, `status = SYNTHETIC / DEMO DATA / NOT REAL
  ROAD GEOMETRY`;
- per-segment SHA-256 fingerprint + a network fingerprint;
- every `RoadImpact` records `scenario_id`, `snapshot_time`, `policy_version`
  (`B13-DEMO-V1`), and `policy_fingerprint`;
- the API attaches `SYNTHETIC / SIMULATED / PROVISIONAL / NOT FOR OPERATIONAL
  USE` labels to every response.

## 5. Synthetic-data policy

No road is presented as real infrastructure (IMPLEMENTATION_SPEC §3, B02).
The dashboard header and the roads endpoint permanently show the
`NOT REAL ROAD GEOMETRY` badge. B02 (WB AMRUT audit) remains OPEN; if M7 uses
synthetic infrastructure, `SYNTHETIC ROAD NETWORK / SYNTHETIC DEM / SYNTHETIC
DRAINAGE` remain clearly identifiable.

## 6. Road sampling method

For each road segment (a straight grid line between two intersection cells):

1. rasterize the segment to the ordered list of grid cells it passes through
   (integer Bresenham, inclusive) — `services/routing/impact.py::rasterize_line`;
2. sample the simulated depth field at those cells;
3. compute `max_depth` (max), `mean_depth` (mean over rasterized cells),
   `impacted_fraction` (cells with depth > 0.05 m), `impacted_length_m`
   (= fraction × length).

Because each Bresenham step advances one cell along the dominant axis, cells
are ~equally spaced along the segment, so the unweighted mean approximates the
length-weighted mean. No sub-cell interpolation is implied — the model itself
is 30 m resolution. The 0.05 m "impacted" threshold equals the M5 flood-extent
threshold, so road impact and flood extent use a consistent notion of "wet".

## 7. Impact calculation

Classification maps a road's `max_depth` onto five states via the B13 policy:

| depth (m)        | class        | passability |
|------------------|--------------|-------------|
| ≤ 0.05           | DRY          | PASSABLE    |
| (0.05, 0.15]     | LOW_IMPACT   | PASSABLE    |
| (0.15, 0.30]     | CAUTION      | PASSABLE    |
| (0.30, 0.50]     | HIGH_IMPACT  | PASSABLE    |
| > 0.50           | IMPASSABLE   | IMPASSABLE  |

Every impact is deterministic and versioned against the policy fingerprint.

## 8. B13 policy

B13 (vehicle passability thresholds) is **UNRESOLVED**. No expert-approved
threshold is claimed. M7 ships `B13-DEMO-V1`:

- `status = PROVISIONAL_DEMONSTRATION`, `approved = false`;
- thresholds centralized in `services/routing/policy.py` (never scattered);
- versioned (`version = 1`) and SHA-256 fingerprinted;
- documented disclaimer: *"Not an operational safety recommendation."*

The severity bands reuse D-013's demo bands (0.05 / 0.15 / 0.30 m) plus a
0.50 m demonstration impassable cutoff. A future human-approved policy can
replace `B13-DEMO-V1` in one place without touching sampling/routing/UI code.

## 9. Routing graph

`services/routing/graph.py` builds an undirected weighted graph: nodes are
intersections (cell-centre projected coordinates), edges are road segments.
Edge cost = travel time = length / speed (km/h → m/s). The graph is
deterministic (built from the fixed network).

## 10. Routing algorithm

Dijkstra over the graph with a pluggable edge-cost function:

- **baseline** — travel time at baseline speed (no flood constraints);
- **avoid_impassable** — impassable roads excluded; others at baseline speed;
- **flood_aware** — impassable roads excluded; impacted roads penalised by the
  policy speed factor.

Dijkstra uses a deterministic tie-break (counter + node id) so equal-cost
paths resolve identically across runs.

## 11. Route cost

- Baseline speed: primary 50 km/h, secondary 40 km/h (SYNTHETIC/ASSUMED).
- Flood-aware speed factors: DRY 1.0, LOW_IMPACT 0.7, CAUTION 0.5,
  HIGH_IMPACT 0.3; IMPASSABLE excluded. These are explicit, configurable,
  versioned — not hidden weights.

## 12. Route safety

"Safe" is never claimed. The flood-aware route uses **lower modelled exposure**
(D-012), not guaranteed safety. If no route satisfies the policy, the result
reports `NO_SAFE_ROUTE` and **never** silently falls back to the normal route.

## 13. Timeline architecture

- 37 precomputed snapshots (0–180 min, 5-min cadence) per scenario.
- The frontend timeline (play/pause/restart/step, 0.5×/1×/2×/4×) scrubs over
  the cached depth grids + the precomputed road-impact index — **no simulation
  re-run, no fake progress**.
- Playback is "Mode A" (snapshot playback). "Mode B" (live run jobs) is
  documented as future work (see §17).

## 14. API

New/updated endpoints (all typed, structured errors, allow-listed IDs):

```text
GET  /api/v1/roads
GET  /api/v1/policies
GET  /api/v1/drainage/points
GET  /api/v1/scenarios/{id}/frame?lead=X          (single timeline payload)
GET  /api/v1/scenarios/{id}/rainfall?lead=X
GET  /api/v1/scenarios/{id}/road-impact?lead=X
GET  /api/v1/scenarios/{id}/road-impact/{road_id}
GET  /api/v1/scenarios/{id}/road-metrics?lead=X
POST /api/v1/routes                               (baseline + flood-aware + diff)
GET  /api/v1/routing/nodes
```

`/frame` returns the depth grid (flat, row-major), drainage state, rainfall
summary, per-road impact, scenario road metrics, and the policy in one
round-trip — the key to sub-second timeline interaction. Existing M6 endpoints
are unchanged.

## 15. Frontend

`apps/web/index.html` — a single-file, no-build, no-CDN interactive dashboard:

- HTML5 canvas map with pan/zoom, layer toggles (depth/extent/rainfall/roads/
  road-impact/inlets-vent/routes), quantitative depth legend, and hover/click
  inspection;
- road click → impact panel (status, depth, impacted length, first-impact and
  impassable times);
- origin/destination click → normal vs flood-aware route with distance/time,
  change (+m / +min), avoided roads, and a data-grounded explanation;
- S3→S4 "what changed" comparison; collapsible scientific provenance.

## 16. UX

The dashboard is organised around the four questions above. Scenario selection
drives the map, timeline, metrics, road panel, routing and provenance — one
coherent flow rather than four disconnected features.

## 17. Performance

Measured on the 2 vCPU sandbox (warm cache, uvicorn):

| operation | median latency |
|-----------|----------------|
| `/frame` (cached) | ~9–10 ms |
| `/routes` (POST)  | ~1.8 ms |

Timeline interaction → map update is well under 1 second (target met). Depth
rasters are read once and cached (`lru_cache`); the per-scenario road-impact
index is computed once; the graph/network are module singletons. Live
simulation jobs (Mode B) are explicitly **future work** — snapshot playback is
the implemented mode.

## 18. Tests

`tests/test_m7_road_impact.py` (M7-01…M7-08): fixture determinism, geometry
validity, dry/flooded/partial classification, threshold boundaries, impact
reproducibility, time-dependent impact.

`tests/test_m7_routing.py` (M7-09…M7-15): baseline route, flood-aware route,
impassable avoidance, comparison, no-safe-route, determinism, policy
fingerprint.

`tests/test_m7_api.py` (M7-16…M7-22): frame API, road-impact API, route API,
invalid handling, security/path-traversal, timeline metadata, M6 regression.

## 19. Limitations

- SYNTHETIC road network — not real geometry, 30 m grid-aligned.
- Route endpoints snap to the nearest intersection (no mid-edge splitting).
- Depth sampling is cell-rasterized (30 m resolution); no sub-cell depth.
- Baseline speeds are SYNTHETIC/ASSUMED.
- The synthetic grid is 2-connected, so a genuine "no safe route" state does
  not occur naturally in the demo (covered by a unit test instead).

## 20. Scientific risks

1. Road impact inherits all 30 m flood-depth uncertainty; "IMPASSABLE" is a
   demonstration class, not a measured condition.
2. B13 thresholds are provisional — over-interpretation as safety standards is
   the primary risk (mitigated by permanent disclaimers + `approved=false`).
3. Rasterized sampling could mis-assign depth at road/cell edges (documented,
   deterministic, conservative — max-depth based).

## 21. Engineering risks

- Single-file JS dashboard is larger than M6's; it remains no-build/no-CDN by
  design and is exercised through the API contract, not a JS test runner.
- The frame payload is ~150 KB; acceptable locally, not a tile server.

## 22. Human review

Required: B13 passability thresholds (expert review before any operational
wording), B02 (real road/drainage data), D-016 (unchanged — hydrologist
sign-off). M7 does **not** fabricate any of these approvals.

## 23. Acceptance decision

All M7 technical gates pass (24 new tests + full M1–M6 regression green).
**M7 PASS** with B13 recorded as PROVISIONAL DEMONSTRATION and D-016/B02
unchanged. See `AI_REVIEW.md` for the canonical status.
