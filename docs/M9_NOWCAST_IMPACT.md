# M9 — Nowcast → Impact Pipeline

> **Status:** M9 PASS — TECHNICAL IMPLEMENTATION COMPLETE
> **Date:** 2026-08-22
> **Scientific status:** persistence-based impact projection only
> **Claim boundary:** `NOT_REAL_TIME`, `NOT_VALIDATED_FORECAST`, `PROVISIONAL DEMONSTRATION`

---

## 1. Summary

M9 connects the implemented M8 rainfall nowcast to the existing M4 flood model,
M7 road-impact system, M7 routing API, and dashboard.

The executed chain is now:

```text
RainfallObservation
  -> NowcastRecord[]
  -> ForecastRainfallFrame[]
  -> CoupledFloodModel (M4)
  -> FloodImpactProjection
  -> RoadImpactProjection
  -> RouteProjection
  -> API / dashboard
```

This is **not** an operational flood forecast. It is a **persistence-based flood
impact projection**:

```text
forecast rainfall at t + Δ = latest observed rainfall field
```

No advection, no ML, no claimed forecast skill, and no live-data claim are added.

## 2. Smallest safe integration point

The protected M4 hydraulic semantics were not rewritten. The smallest safe
integration point was the rainfall-input adapter:

- M4 already expects a sequence of gridded rainfall fields.
- Before M9, the engine could only build those fields indirectly from M4/M5
  scenario specifications (`uniform`, `spatial`, `profile`).
- M9 adds an **additive input mode**: `RainfallSpec(kind="explicit_fields")`.

This preserves the authoritative M4 physics while allowing M8 nowcast fields to
reach the solver without silent resampling or pattern substitution.

## 3. Architecture

### 3.1 New modules

```text
services/projection/
  __init__.py          version + lead constants
  configs.py           projection-configuration registry (P_NORMAL, P_BLOCKED)
  contracts.py         ForecastRainfallFrame, FloodImpactProjection,
                       RoadImpactProjection, RouteProjection
  adapter.py           nowcast -> frame -> RunConfig adapter
  cache.py             TTL cache for expensive projection bundles
  pipeline.py          executable orchestration and route generation

apps/api/projections.py
  projection API service layer

tests/test_m9_nowcast_impact.py
  dedicated M9 contract/integration/API/dashboard suite
```

### 3.2 Existing modules reused unchanged in semantics

- `services/nowcast/*` — observation, quality, persistence nowcast, cache
- `services/simulation/engine.py` — M4 hydraulic engine (physics unchanged)
- `services/routing/impact.py` — M7 road sampling and classification
- `services/routing/router.py` — M7 routing logic and `NO_SAFE_ROUTE`
- `apps/web/index.html` — extended with M9 projection mode

## 4. Data flow

### 4.1 Observation -> nowcast

M9 reuses the active M8 provider via `apps/api/rainfall_api.py`.

Rules preserved from M8:

- invalid or stale observations do **not** become AVAILABLE projections
- M8 observation and nowcast cache semantics stay intact
- persistence nowcast remains `NOWCAST-PERSISTENCE-V1`
- providers remain `SYNTHETIC` / `FIXTURE`

### 4.2 Nowcast -> forecast rainfall frame

`services/projection/contracts.py::ForecastRainfallFrame` adds an explicit typed
representation of a future rainfall field with:

- initialization time
- valid time
- valid interval (`valid_from`, `valid_to`)
- lead minutes
- full rainfall field (`mm/h`)
- spatial reference and resolution
- dimensions
- source/provider identity
- nowcast method
- nowcast fingerprint
- observation fingerprint
- frame fingerprint
- provenance/status labels

### 4.3 Forecast frame -> M4 engine

`services/projection/adapter.py` performs the M9 adapter step.

Safety rules:

- preserve grid shape
- preserve CRS and cell size
- preserve `mm/h`
- reject incompatible grids
- reject negative/non-finite rainfall
- no silent resampling
- no silent `mm/h <-> mm` conversion

The adapter builds:

```python
RainfallSpec(kind="explicit_fields", explicit_fields_mmh=[...])
```

for the M4 engine.

### 4.4 Why one simulation is sufficient

For persistence, every forecast frame is the same rainfall field. The M4 engine
advances over time, so one 0–60 minute run per observation/configuration is the
scientifically correct and cheapest approach.

M9 therefore runs **one 60-minute coupled simulation** per projection bundle and
extracts lead snapshots at:

```text
0, 15, 30, 45, 60 min
```

The interval-start rainfall frames at leads 0, 15, 30, and 45 drive the
intervals `[0,15)`, `[15,30)`, `[30,45)`, and `[45,60)`.

The lead-60 rainfall frame is still preserved for provenance and UI display,
but it does not start an additional interval inside the 0–60 minute run.

## 5. Projection configurations

M9 introduces two nowcast-impact configurations:

| Config | Drainage | Reuses |
|---|---|---|
| `P_NORMAL` | clean synthetic drainage (`D_NORMAL`) | M5/M7 normal-drainage baseline |
| `P_BLOCKED` | blocked synthetic drainage (`D_BLOCKED`) | M5/M7 blocked-drainage baseline |

These configurations reuse the M5/M4 hydraulic parameter baseline (Manning n,
Horton parameters, microstore, coupling constants, inlet mapping, DEM, etc.)
without changing M4 semantics.

## 6. Flood-impact projection contract

Each `FloodImpactProjection` exposes:

- lead time
- initialization time
- valid time
- rainfall-frame provenance
- max depth in the projected snapshot
- flooded area / cells
- surface storage
- drainage state (ST1 head, D2S, outfall, surcharge flag)
- M9 model version
- M4 engine version
- configuration fingerprint
- observation fingerprint
- nowcast fingerprint
- projection fingerprint
- mass-balance summary (`PASS`/`FAIL` from the authoritative run)
- labels (`PERSISTENCE_PROJECTION`, `NOT_REAL_TIME`, `NOT_VALIDATED_FORECAST`, ...)

## 7. Road impact and routing integration

### 7.1 Road impact

M9 reuses the M7 deterministic road-impact implementation directly.

```text
projected depth field
  -> Bresenham cell sampling
  -> road max/mean depth
  -> impacted fraction/length
  -> B13-DEMO-V1 classification
```

No second road-impact algorithm was introduced.

### 7.2 Routing

M9 reuses M7 routing directly against projected road-impact states.

Supported leads:

```text
route at lead 0
route at lead 15
route at lead 30
route at lead 45
route at lead 60
```

Preserved M7 semantics:

- baseline route
- `avoid_impassable`
- `flood_aware`
- deterministic Dijkstra
- `NO_SAFE_ROUTE` / no silent fallback
- B13 remains `approved=false`

## 8. API

### 8.1 New endpoints

```text
GET  /api/v1/projections/nowcast/status
GET  /api/v1/projections/nowcast/cache
GET  /api/v1/projections/nowcast/configs
GET  /api/v1/projections/nowcast/{config_id}
GET  /api/v1/projections/nowcast/{config_id}/frame?lead=L
GET  /api/v1/projections/nowcast/{config_id}/rainfall?lead=L
GET  /api/v1/projections/nowcast/{config_id}/flood?lead=L
GET  /api/v1/projections/nowcast/{config_id}/road-impact?lead=L
GET  /api/v1/projections/nowcast/{config_id}/road-impact/{road_id}
POST /api/v1/projections/nowcast/{config_id}/routes
```

### 8.2 Error behaviour

- invalid config -> `404 PROJECTION_CONFIG_NOT_FOUND`
- invalid lead -> `400 INVALID_LEAD`
- unavailable observation/nowcast/projection -> `503 PROJECTION_UNAVAILABLE`
- invalid road id -> `404 ROAD_NOT_FOUND`

No invalid lead silently falls back.

## 9. Dashboard integration

`apps/web/index.html` now includes an M9 projection mode with:

- view-mode toggle (`Historical M5 scenarios` vs `M9 persistence projection`)
- projection-config selector (`P_NORMAL`, `P_BLOCKED`)
- projection lead selector/timeline (`0, 15, 30, 45, 60`)
- projected rainfall frame display
- projected flood depth map
- projected road impact
- projected route comparison
- provenance block for observation / nowcast / projection fingerprints

Permanent labels remain visible:

- `PERSISTENCE PROJECTION`
- `NOT_REAL_TIME`
- `NOT_VALIDATED FORECAST`
- `NOT FOR OPERATIONAL USE`

M7 historical scenario inspection remains available; the M9 mode is additive.

## 10. Cache behaviour

M9 adds a dedicated projection cache (`services/projection/cache.py`).

Key identity includes:

- observation fingerprint
- combined nowcast fingerprint
- projection-config fingerprint
- M4 RunConfig fingerprint
- M9 model version

This prevents returning a stale projection for a different rainfall field or
configuration.

The projection cache stores the entire 0–60 minute bundle so the backend does
**not** re-run the hydraulic solver for every lead, road-impact request, or
route request.

## 11. Provenance

Every M9 bundle preserves traceability from dashboard/API output back to the
observation.

Minimal chain:

```text
dashboard frame / route
  -> projection fingerprint
  -> nowcast fingerprint
  -> observation fingerprint
  -> provider/source identity
```

## 12. Performance

Measured on the 2 vCPU sandbox for a representative `P_NORMAL` build driven by a
140 mm/h synthetic observation:

| Operation | Measured time |
|---|---:|
| nowcast generation | ~2.4 ms |
| flood projection (0–60 min run) | ~7886 ms |
| flood projection per lead (effective) | ~1577 ms |
| road impact derivation | ~12 ms |
| route computation | ~0.9 ms |
| total first projection build | ~9477 ms |
| repeat request after cache | cache hit (solver not rerun) |

The dominant cost remains the hydraulic solve, which is why the bundle cache is
required for the API/dashboard path.

## 13. Tests

`tests/test_m9_nowcast_impact.py` adds 36 dedicated M9 tests covering:

- forecast-frame contract validation
- persistence equality across 0/15/30/45/60
- adapter behaviour and grid compatibility
- M4 projection generation and determinism
- multi-lead traceability
- projected road impact
- projected routing and `NO_SAFE_ROUTE`
- projection API
- dashboard integration labels/controls

Full regression on this checkout (as-of-M9 historical snapshot — superseded;
as of M9.1.1 the full suite is 418 tests, see `docs/AI_REVIEW.md` §10):

```text
366 passed, 0 failed, 0 skipped
```

## 14. Limitations

1. `NOT_REAL_TIME` — the active providers remain `SYNTHETIC` / `FIXTURE`.
2. Persistence only — no advection, no growth/decay, no ML.
3. `NOT_VALIDATED_FORECAST` — no forecast skill is claimed.
4. No flood-state data assimilation beyond the configured synthetic initial state.
5. D-016 remains `PREPARED` / human review required.
6. B02 remains open / unaudited.
7. B13 remains `PROVISIONAL DEMONSTRATION` / `approved=false`.
8. Roads and drainage geometry remain synthetic fixtures.

## 15. Acceptance

M9 is technically implemented: the M8 nowcast is now executable input to the
flood-impact, road-impact, routing, API, and dashboard stack.
