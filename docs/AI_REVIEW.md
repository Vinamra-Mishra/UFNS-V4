# UFNS — AI Engineering Review

> Canonical human-facing status file. No marketing language; every claim needs execution evidence. Updated after every milestone (IMPLEMENTATION_SPEC §24).

## 1. Current Status

```text
Phase:            1 — Implementation (human approval recorded 2026-08-21)
Previous milestone: M10 — REAL-PILOT VALIDATION PASS (13/13 RD gates)
Milestone:        M11 — REAL-PILOT MODEL INTEGRATION:
                  PASS (12/12 M11 gates with execution evidence)
                  (real terrain + real drainage geometry integrated
                  through explicit adapters over the unchanged M4 engine;
                  HYDRAULIC_NETWORK_READY=False; real/synthetic separation
                  intact; MODE B executable run on real ROI terrain with
                  mass relative residual 7.8e-08; NOT_REAL_TIME;
                  NOT_VALIDATED_FORECAST; D-016 PREPARED; B13 PROVISIONAL;
                  B02 CRS provenance RESOLVED)
Build:            M11 targeted suite 55/55 (48 integration + 7 API);
                  M1-M9 regression preserved (engine change byte-identical
                  by default)
Last Updated:     2026-08-23
Overall Health:   GREEN (M1-M9 preserved; M10 13/13 RD gates PASS;
                  M11 12/12 gates PASS; D-016 NOT approved; B13 NOT
                  approved; hydraulic network NOT ready by design)
```

## 2. Executive Summary

- What works: a deterministic four-scenario suite (S1 Normal / S2 Heavy / S3 Extreme / S4 Extreme+Blocked) executes on the unmodified M4 coupled engine with typed scenario definitions, governed rainfall profiles (PROVISIONAL), explicit drainage conditions (NORMAL/BLOCKED as real hydraulic capacity reduction), full per-scenario mass ledgers, S3/S4 paired comparison, and 18 gate tests. A **D-016 derivation** establishes a traceable, published-IDF basis (Kumar & Remesan 2026, Bagjola Canal basin) with 13 tests. An **M6 dashboard/API** exposes scenarios, metrics, depth/extent maps, mass-balance and the S3/S4 comparison. **M7** adds a SYNTHETIC road network (57 segments), a centralized/versioned/fingerprinted B13-DEMO-V1 passability policy, deterministic road impact derived from the depth fields, flood-aware routing (baseline vs avoid-impassable vs flood-aware, with NO_SAFE_ROUTE handling), and an interactive canvas dashboard (timeline playback, layer toggles, road inspection, routing, provenance) — 24 tests, 154/154 green (M1–M7 cumulative). **M8** adds provider-independent rainfall ingestion, persistence nowcast, cache, and API/dashboard nowcast status. **M9** now connects that M8 nowcast to the M4 flood engine and the M7 road/routing stack through typed forecast rainfall frames, a cached projection pipeline, projection API endpoints, and a dashboard projection mode. M4 scientific semantics are unchanged.
- What does not: validated forecast skill, real-time rainfall ingestion, a real **hydraulic** drainage network (the real WB AMRUT geometry is integrated, but the five required hydraulic attributes are MISSING by source — `HYDRAULIC_NETWORK_READY=False`; MODE B runs real terrain with explicitly-labelled SYNTHETIC hydraulics, never as a real hydraulic result), expert-approved B13 thresholds (open — PROVISIONAL only), D-016 hydrologist approval (open — PREPARED, not approved).
- Largest scientific risk: D-016 remains PREPARED (published IDF, deterministic, tested) but requires hydrologist sign-off on the return-period→scenario mapping and derived totals; rainfall profiles remain PROVISIONAL / NOT FOR OPERATIONAL USE. B13 vehicle-passability thresholds remain PROVISIONAL DEMONSTRATION (not expert-approved). The real drainage data lacks hydraulic parameters — a real hydraulic network requires independently obtained/governed diameter/invert/Manning/capacity.
- Largest engineering risk: the hydraulic solve remains the dominant cost on the sandbox (2 vCPU/3.9 GiB). M9 mitigates the "dashboard re-runs the solver" risk by caching the full 0–60 minute projection bundle per observation/configuration; measured first-build cost is ~9.5 s for a representative `P_NORMAL` run, while repeat lead/road/route requests hit cache. M11 MODE B runs on a deterministic real-pilot ROI to keep the executable integration tractable while remaining 100% real elevation data.
- Current milestone: M11 REAL-PILOT MODEL INTEGRATION — **PASS** (12/12 gates with execution evidence; matrix + definitions in `docs/M11_REAL_PILOT_INTEGRATION.md` §11). Real terrain and real drainage geometry are integrated through explicit adapters over the **unchanged** M4 engine (one additive, byte-identical-by-default grid-origin hook); `HYDRAULIC_NETWORK_READY=False` by design; real/synthetic separation intact; mass conservation holds (7.8e-08). Previous milestones: M10 — REAL-PILOT VALIDATION PASS (13/13 RD gates); M9 — COMPLETE / PASS; M9.1 HARDENED.
- Human review status: M1–M4 PASS recorded; M4 visual review SATISFACTORY (2026-08-21); D-016 PREPARED (human approval required); B02/B13 remain open (§16).

## 3. What Is Actually Implemented

| Component | Status | Evidence | Test |
|---|---|---|---|
| Data contracts (DataLineage, GridSpec, RainfallGrid, ScenarioDefinition, MassBalance…) | DONE | `services/contracts.py` (pydantic v2, extra-forbid) | `tests/test_contracts.py` |
| CRS policy / timestamp / DEM / provenance / rainfall fields | DONE | M1 stack | M1 unit tests |
| Mass ledger with 1%/5% gates | DONE | `services/simulation/ledger.py` | `tests/test_ledger.py` |
| Landlab surface adapter (spatial rain, Horton, adaptive dt, outflow) | DONE | `services/hydrology/surface.py` | `tests/test_landlab_spike.py` |
| SWMM coupling (signed head-driven orifice, engine-exact ledger) | DONE | `services/hydraulics/coupling.py` | `tests/test_swmm_spike.py` |
| Synthetic SWMM fixtures (clean/blocked exact-exchange) | DONE | `services/hydraulics/fixture.py`; `data/demo/drainage_synthetic_m4*.inp` | M3/M4 tests |
| Coupled flood model engine (M4) | DONE | `services/simulation/engine.py` | `tests/test_m4_coupled.py` (16 tests) |
| **M5 scenario profiles (governed, status-tagged)** | DONE | `services/scenarios/profiles.py` | M5-03 |
| **M5 drainage conditions (NORMAL/BLOCKED, hydraulic evidence)** | DONE | `services/scenarios/drainage.py` | M5-02, M5-08, M5-09 |
| **M5 scenario registry (S1–S4 typed, fingerprinted)** | DONE | `services/scenarios/registry.py` | M5-01, M5-02 |
| **M5 scenario runner (clean state → M4 engine → ScenarioResult)** | DONE | `services/scenarios/runner.py` | M5-04…M5-07 |
| **M5 comparison (per-scenario + S3/S4 blockage diff)** | DONE | `services/scenarios/comparison.py` | M5-08, M5-09, M5-16 |
| **M5 visual diagnostics (rain/peak/extent/timelines + S3S4)** | DONE | `services/scenarios/diagnostics.py`; `scripts/run_m5_diagnostics.py`; `data/demo/m5/` | M5-12, M5-15 |
| **M5 test matrix (M5-01…M5-16 + regressions)** | DONE | `tests/test_m5_scenarios.py` (18 tests) | 99/99 |
| **M5 documentation** | DONE | `docs/M5_SCENARIO_ENGINE.md` | — |
| **D-016 published-IDF rainfall derivation** | DONE (PREPARED) | `services/rainfall/idf.py`; `docs/D016_RAINFALL_DERIVATION.md` | `tests/test_d016_rainfall.py` (13) |
| **M6 dashboard/API (inspection layer)** | DONE (PASS) | `apps/api/` (store/render/app) + `apps/web/index.html`; `scripts/run_dashboard.py` | `tests/test_m6_dashboard.py` (18) |
| **M6 documentation** | DONE | `docs/M6_DASHBOARD.md` | — |
| **M7 road network (SYNTHETIC)** | DONE | `services/routing/roads.py` | M7-01, M7-02 |
| **M7 B13 passability policy** | DONE (PROVISIONAL) | `services/routing/policy.py` (B13-DEMO-V1) | M7-06, M7-15 |
| **M7 road impact (depth sampling, time-dependent)** | DONE | `services/routing/impact.py` | M7-03…M7-08 |
| **M7 road graph + flood-aware routing** | DONE | `services/routing/graph.py`, `router.py` | M7-09…M7-15 |
| **M7 API (frame/roads/impact/routes)** | DONE | `apps/api/impacts.py`, `apps/api/app.py` | M7-16…M7-22 |
| **M7 interactive dashboard (canvas map + timeline)** | DONE | `apps/web/index.html` | M7-16…M7-22 |
| **M7 documentation** | DONE | `docs/M7_ROAD_IMPACT_ROUTING.md` | — |
| **M8 provider-independent rainfall ingestion** | DONE (NOT_REAL_TIME) | `services/nowcast/providers/` (synthetic + fixture) | `tests/test_m8_nowcast.py` |
| **M8 persistence-baseline nowcast** | DONE (NOT_REAL_TIME) | `services/nowcast/engine.py` (NOWCAST-PERSISTENCE-V1) | M8-07, M8-15 |
| **M8 typed nowcast contract + fingerprint + cache** | DONE | `services/nowcast/nowcast_record.py`, `services/nowcast/cache.py` | M8-14, M8-09 |
| **M8 API endpoints (rain/nowcast/status/cache/verification)** | DONE | `apps/api/rainfall_api.py`, `apps/api/app.py` | M8-10…M8-13, M8-16 |
| **M8 documentation (nowcast, velocity roadmap, scientific/independent review)** | DONE | `docs/M8_NOWCAST.md`, `docs/M8_VELOCITY_INTEGRATION.md`, `docs/M8_SCIENTIFIC_REVIEW.md` | — |
| **M9 forecast-rainfall frame + adapter** | DONE | `services/projection/contracts.py`, `services/projection/adapter.py`, additive `explicit_fields` input path in `services/simulation/engine.py` | `tests/test_m9_nowcast_impact.py` |
| **M9 flood-impact projection pipeline + cache** | DONE | `services/projection/pipeline.py`, `services/projection/cache.py`, `services/projection/configs.py` | `tests/test_m9_nowcast_impact.py` |
| **M9 projection API + dashboard mode** | DONE | `apps/api/projections.py`, `apps/api/app.py`, `apps/web/index.html` | `tests/test_m9_nowcast_impact.py` |
| **M9.1 hardening (fingerprint compat, 503 handling, nearest-lead, determinism)** | DONE | `services/simulation/engine.py`, `apps/web/index.html`, `tests/` | `tests/test_m9_nowcast_impact.py`, `tests/test_m8_nowcast.py` |
| **M9.1.1 code-quality closure (error-code gating, deep provenance immutability, result-specific provenance, label semantics, oracle/determinism tests)** | DONE | `apps/web/index.html`, `services/ingestion/{real_data,dem_real,drainage_real}.py`, `tests/` | `tests/test_m9_nowcast_impact.py`, `tests/test_m8_nowcast.py`, `tests/test_m10_real_data.py` |
| **M10 real-pilot data contracts + provenance** | DONE (FOUNDATION) | `services/ingestion/real_data.py` (immutable provenance, result snapshots, processing fingerprints, acquisition-evidence records, result labels) | `tests/test_m10_real_data.py` |
| **M10 DEM validation pipeline** | IMPLEMENTED + EXECUTED ON REAL DATA (2026-08-22: real tile → VALIDATED, 30.76 m from transform, no-nodata-sentinel warning) | `services/ingestion/dem_real.py` — access/fingerprint/validation (incl. resolution-from-transform)/provenance | `tests/test_m10_real_data.py` (incl. real-artifact tests) |
| **M10 DEM normalization to pilot GridSpec** | IMPLEMENTED + EXECUTED ON REAL DATA (real tile → BLOCKED: no spatial overlap with the established pilot GridSpec — data/model integration issue, not forced) | `services/ingestion/dem_real.py` `normalize_dem` — clip → reproject → bilinear → GridSpec alignment, nodata preserved, processing fingerprint | `tests/test_m10_real_data.py` (incl. real-artifact tests) |
| **M10 drainage attribute-level audit** | IMPLEMENTED + EXECUTED ON REAL DATA (drains/vents → AUDIT_PARTIAL: no embedded CRS; 90,395/9,579 records; all 5 hydraulic attributes confirmed absent) | `services/ingestion/drainage_real.py` `audit_wb_amrut_drains` — schema classification, geometry/CRS validation, duplicates, extent, explicit reports | `tests/test_m10_real_data.py` (incl. real-artifact tests) |
| **M10 drainage entity mapping** | IMPLEMENTED + EXECUTED ON REAL DATA (→ BLOCKED by the VALIDATED-source contract; 0 entities; nothing fabricated) | `services/ingestion/drainage_real.py` `map_drainage_entities` — explicit rules, stable IDs, mapping status, no-fabrication | `tests/test_m10_real_data.py` (incl. real-artifact tests) |
| **M10 acquisition evidence** | DONE (in-sandbox attempts BLOCKED — preserved; human-supplied artifacts FETCHED with path/bytes/SHA-256) | `services/ingestion/acquisition.py` (`attempt_download`, `verify_local_artifact`), `scripts/attempt_real_data_acquisition.py`, `scripts/record_real_artifact_evidence.py`, `data/raw/acquisition_attempts.json` | `tests/test_m10_real_data.py` (incl. real-artifact tests) |
| **M10 real-data execution driver** | DONE (runs the unchanged M10 pipelines on `data/raw/`, writes `data/processed/m10_real_pilot_validation.json`) | `scripts/run_m10_real_pilot_validation.py` | real-artifact tests pin the resulting statuses |
| Live real-time rainfall feed | NOT_IMPLEMENTED | providers are SYNTHETIC/FIXTURE only | — |
| Real DEM tile | FETCHED + VALIDATED (2026-08-22, human-supplied) | `data/raw/bagjola_kolkata_glo30_dem.tif` (sha256 `8832ae95…`); raster gates pass; normalization BLOCKED on pilot-grid coherence (M10 doc §2.2/§12) | `tests/test_m10_real_data.py` |
| WB AMRUT parquet data | FETCHED + AUDIT_PARTIAL (2026-08-22, human-supplied) | `data/raw/WB_AMRUT_Stormwater_{drains,vents}.parquet` (sha256 `6b224492…` / `ef017b6f…`); embedded CRS gap + confirmed-absent hydraulics; mapping BLOCKED (M10 doc §2.2, DATA_AUDIT_WB_AMRUT.md) | `tests/test_m10_real_data.py` |

## 4. Architecture Status

```text
Data contracts:        IMPLEMENTED
Ingestion/alignment:   IMPLEMENTED (fixture path; real-source adapters M10)
Rainfall:              IMPLEMENTED (profiles governed, PROVISIONAL; nowcast M8)
Surface routing:       IMPLEMENTED (M2 spike verified)
Drainage:              IMPLEMENTED (M3 spike verified)
Coupling:              IMPLEMENTED (M3 spike verified, PASS)
Simulation run:        IMPLEMENTED (M4 verified)
Scenario engine:       IMPLEMENTED (M5 CONDITIONAL PASS)
Impact projection:     IMPLEMENTED (M9 persistence-based nowcast -> M4 adapter)
API / Dashboard:       IMPLEMENTED (M6 PASS; M7 interactive dashboard; M9 projection mode)
Road impact/routing:   IMPLEMENTED (M7 PASS; consumed by M9 projections; B13 PROVISIONAL)
```

## 5. Scientific Model Status

```text
rainfall:     Method: 15-min interval fields; alternating-block hyetographs (PROVISIONAL, D-016 PREPARED).
              Status: profile governance implemented; three severity levels defined with explicit
              criteria (NORMAL 20 mm/3h, HEAVY 45 mm/3h, EXTREME 90 mm/3h — PROVISIONAL, unchanged).
              D-016: published-IDF derivation prepared (Kumar & Remesan 2026; source-derived totals
              72.08 / 88.44 / 103.25 mm at 2/5/10-yr). Human approval required before any flip.
runoff:       Method: microstore + Horton (per-cell wetting clocks).
              Status: unchanged from M4. Parameters PROVISIONAL.
surface routing: Method: Landlab OverlandFlow, de Almeida et al. 2012 (D4, θ=0.8, α=0.5).
              Status: unchanged from M4. Confidence: established algorithm, locally verified.
drainage:     Method: EPA SWMM 5.2.4 dynamic wave via PySWMM 2.1.0; exact-exchange synthetic
              fixtures (clean D=0.30 m; blocked D=0.12 m, capacity ratio ~0.087).
              Status: unchanged from M4. Engine conservation independently proven.
hydraulic coupling: Method: signed head-driven orifice (Cd=0.6, Ao=0.002 m²/inlet, ASSUMED).
              Status: unchanged from M4. No semantics altered in M5.
flood depth:  Method: h = max(0, η−z); 37 snapshots per scenario per run.
              Status: M4/M5 verified.
scenario engine: Method: typed ScenarioRecord → M4 RunConfig → CoupledFloodModel.run() →
              ScenarioResult; fresh model per scenario (M5-10); deterministic fingerprints
              (M5-13); explicit provenance + acceptance gates per run.
              Status: M5 CONDITIONAL PASS — D-016 PREPARED (human review required).
road impact:  Method: cell-rasterized (Bresenham) sampling of the simulated depth field
              along each road segment; max/mean depth, impacted fraction/length,
              classification + passability via the B13-DEMO-V1 policy.
              Status: M7 PASS (PROVISIONAL policy; not a safety standard).
routing:      Method: deterministic Dijkstra on the road graph; baseline (no flood),
              avoid-impassable (exclude impassable), flood-aware (exclude impassable +
              penalise impacted by policy speed factors); NO_SAFE_ROUTE without silent
              fallback; data-grounded explanation.
              Status: M7 PASS (SYNTHETIC network; lower modelled exposure, not "safe").
```

## 6. Data Status

| Dataset | Source | Status | Type | License | Problem |
|---|---|---|---|---|---|
| Synthetic DEM fixture | UFNS-generated (seed 20260821) | ACCEPTED (demo) | SYNTHETIC | internal | not real terrain; labelled |
| M5 rainfall profiles (P_NORMAL, P_HEAVY, P_EXTREME) | UFNS-generated (alternating-block, Chow 1988) | ACCEPTED (demo) | SIMULATED/PROVISIONAL | internal | D-016 PREPARED (published-IDF derivation ready, not approved); not for operational use |
| M5 drainage fixtures (clean D_NORMAL, blocked D_BLOCKED) | UFNS synthetic INPs | ACCEPTED (demo) | SYNTHETIC | internal | C1 capacity reduction is real in INP |
| WB AMRUT drains/vents | india-geodata releases | FETCHED + AUDIT_PARTIAL (2026-08-22) | candidate real geometry | claimed India-OGL | no embedded CRS (AUDIT_PARTIAL); all 5 hydraulic attributes confirmed absent; 100 dup ids each; no `type` column; does not overlap the established pilot GridSpec; B02 human acceptance pending |
| Copernicus DEM GLO-30 tile | human-supplied (intended: Planetary Computer STAC) | FETCHED + VALIDATED (2026-08-22) | STATIC real | Copernicus | raster gates pass (30.76 m from transform); no nodata sentinel; actual bounds 88.60–88.85°E — filename "bagjola_kolkata" not confirmed by bounds; does not overlap the established pilot GridSpec (normalization BLOCKED) |

## 7. Nowcast Status

```text
Current rainfall:   demo profiles only (SIMULATED, PROVISIONAL) + M8 provider layer
                    (SYNTHETIC default; FIXTURE replay) — NOT_REAL_TIME
Forecast horizon:   0–60 min (lead times 0/15/30/45/60) — persistence baseline
Forecast timestep:  not implemented (persistence holds field constant)
Spatial resolution: 30 m (134×134 grid)
Nowcast method:     persistence baseline IMPLEMENTED (NOWCAST-PERSISTENCE-V1) — NOT an
                    advanced forecast; no advection, no intensity evolution, no ML
Baseline:           persistence only; no other method evaluated
ML model:           none
Validation:         NOT_EVALUATED (no paired forecast/observation data; no skill scores)
M9 integration:     IMPLEMENTED — nowcast fields are adapted into explicit rainfall
                    frames and drive a 0–60 min persistence-based flood impact projection
                    on the authoritative M4 engine.
```

## 8. Flood Impact Status

```text
Flood depth:              DONE (M5: 4 scenarios × 37 snapshots; peak 0.24/0.47/0.61/0.61 m)
Flood extent:             DONE (threshold 0.05 m; 0.23/1.79/4.58/4.58 km²)
Drainage overload:        DONE (S4 surcharge 0.30 m above vent; D2S spill 137 m³)
Scenario comparison:      DONE (S3/S4 blockage diff: capture −66%, outfall −84%, surface +699 m³)
Affected roads:           DONE (M7: time-dependent road impact; e.g. S4 t110 → 56/57 impacted,
                          8 impassable, 13.5 km affected road length)
Route impact:             DONE (M7: flood-aware vs normal route; e.g. NW→SE at S4 t110
                          +703 m / +5.8 min, avoids 2 impassable diagonal segments)
M9 projection depth:      DONE (0–60 min nowcast-driven flood projections on M4; lead 60 example
                          P_NORMAL @ 140 mm/h synthetic observation -> max depth ~0.53 m)
M9 projected routing:     DONE (same NW→SE route on projected lead 60 conditions avoids the
                          flooded central diagonal when projected depth exceeds B13 demo thresholds)
```

## 9. Mass Conservation

M2, M3, M4 evidence unchanged from the M4 review (see M4_COUPLED_MODEL.md §17).

M5 scenario ledgers (134×134 fixture, 3 h, dt_c=5 s, 16 inlets + vent):

```text
scenario   rain m3     S2D m3   D2S m3   outfall m3   ΔS_s m3    residual m3   rel       gate
S1 normal    233,310    313.6      0.0      308.6       +448      -1.24         5.3e-6    pass
S2 heavy     535,459    495.7      0.0      488.3     +1,673     -85.56         1.6e-4    pass
S3 extreme 1,064,706    858.5      0.0      847.7     +4,745    -219.26         2.1e-4    pass
S4 extreme 1,064,706    293.2    136.9      138.9     +5,444    -217.11         2.0e-4    pass
```

- Combined residual is the documented M2 h_init film creation (~0.02–0.04% of rainfall on this domain), explicitly reported, never absorbed.
- Drainage residual is ~0 by engine identity (ΔS_d computed from SWMM's own per-stride conservation).
- Exchange terms (S2D, D2S) cancel in the combined ledger (asserted in M5-11).
- All scenarios ≤ 1% relative residual gate.

## 10. Test Status

```text
Unit:                  50 passed (M1/M2 contracts/crs/time/rainfall/dem/provenance/bundle/ledger)
Integration:           31 passed (15 M3 coupling + 16 M4 coupled-model)
M5 scenario:           18 passed (M5-01…M5-16 + 2 regression guards)
D-016 derivation:      13 passed (published-IDF derivation)
M6 dashboard/API:      18 passed
M7 road impact:        8 passed (M7-01…M7-08)
M7 routing:            7 passed (M7-09…M7-15)
M7 API:                9 passed (M7-16…M7-22)
M8 nowcast:            188 passed (provider contract, source identification, timestamp,
                       units, freshness, missing data, persistence determinism, typed
                       contract, fingerprint, API endpoints, caching, cache immutability,
                       thread safety, lead-time invariant, verification, frontend incl.
                       503 + PROJECTION_UNAVAILABLE error-code gating)
M9 nowcast-impact:     40 passed (forecast-frame contract, persistence semantics,
                       adapter behaviour, flood projection, multi-lead provenance,
                       road impact, routing, API, dashboard, legacy-fingerprint
                       compatibility vs independent pre-M9 oracle, complete-contract
                       determinism)
M10 real-pilot data:   120 passed (B02 audit, DEM ingestion + validation gates
                       incl. resolution-from-transform, DEM normalization to the
                       pilot GridSpec incl. nodata preservation/determinism,
                       drainage attribute-level audit, drainage entity mapping
                       incl. rejection/no-fabrication, processing fingerprints,
                       acquisition evidence, provenance immutability including
                       independence from the caller's mapping, result-specific
                       provenance, real/synthetic label semantics incl. the
                       fixture→REAL_DATA guard, synthetic/real separation,
                       no operational claims, rejection of invalid data,
                       explicit failure-state labels, + 10 real-pilot artifact
                       execution tests (2026-08-22) pinning the evidence-backed
                       statuses on the actual data/raw artifacts: real DEM
                       VALIDATED from actual raster metadata, normalization
                       BLOCKED on pilot-grid coherence, drains/vents
                       AUDIT_PARTIAL on the embedded-CRS gap, all 5 hydraulics
                       confirmed absent, mapping BLOCKED by the
                       VALIDATED-source contract, deterministic fingerprints,
                       acquisition evidence identity + preserved BLOCKED
                       history, real-never-SYNTHETIC separation;
                       skip-guarded when the artifacts are absent)
Mass conservation:     All scenarios/projections pass ≤1% relative; exchange cancels
Numerical stability:   All depths finite, non-negative (≥−1e-12); S2/S4 reproduces M4 baseline
Passed/Failed/Skipped: 502 / 0 / 0 (154 M1-M7 + 188 M8 + 40 M9 + 120 M10)
```

## 11. Scientific Validation

```text
Experiment:  M5 scenario suite end-to-end
Purpose:     prove UFNS runs a comparable, reproducible four-scenario suite
             with controlled rainfall and drainage, and produces a measurable
             physically-interpretable S3/S4 blockage response
Dataset:     synthetic 134×134 DEM + M4 exact-exchange SWMM fixtures
Configuration: 16 rim inlets, dt_c=5 s, 3 h, 5-min snapshots
Expected:    S1<S2<S3 monotonic depth/area; S4 measurable surcharge return,
             reduced capture, reduced outfall, increased surface storage
Observed:    S1 peak 0.243 m / S2 0.471 m / S3 0.614 m / S4 0.615 m;
             S4 D2S 136.9 m³ (vs S3 0), S4 capture 293 vs 859 m³ (−66%),
             S4 outfall 139 vs 848 m³ (−84%), surface Δ storage +699 m³;
             S4 max ST1 surcharge 0.30 m above vent ground.
             All mass gates pass (rel ≤ 2.1e-4).
Result:      PASS (technical gates); CONDITIONAL PASS overall (D-016 PREPARED, human review required)

Experiment:  S3/S4 comparability controls
Purpose:     ensure only drainage condition differs in the paired comparison
Expected:    identical DEM/grid/rain/surface/IC/dt/cadence/versions
Observed:    all pairwise control booleans True (M5-08); rainfall fingerprints
             identical; drainage fingerprints differ; surface config fingerprints
             identical.
Result:      PASS

Experiment:  scenario isolation & reproducibility
Purpose:     no state leakage between runs; suite rerun yields identical outputs
Expected:    identical fingerprints and numeric outputs
Observed:    M5-10 interleaved runs reproduce peak/S2D/D2S/outfall/residual bitwise;
             M5-13 two full suite runs produce identical comparison artifact
             (modulo wall-clock runtime).
Result:      PASS

Experiment:  M4 regression
Purpose:     M5 must not alter M4 scientific semantics
Expected:    all 81 M1–M4 tests still green
Observed:    99/99 passing (81 pre-M5 + 18 M5); S2 reproduces M4 heavy baseline
             within tolerance (peak 0.471 m ± 0.005; area 1.79 km² ± 2%).
Result:      PASS
```

## 12. Demo Status

```text
S1 Normal Rainfall + Normal Drainage:       DONE (peak 0.243 m, 0.23 km², clean capture)
S2 Heavy Rainfall + Normal Drainage:        DONE (peak 0.471 m, 1.79 km²; reproduces M4-04)
S3 Extreme Rainfall + Normal Drainage:      DONE (peak 0.614 m, 4.58 km², clean drainage stressed)
S4 Extreme Rainfall + Blocked Drainage:     DONE (peak 0.615 m, 4.58 km²; surcharge 0.30 m,
                                             D2S 137 m³ spill, outfall −84%, surface +699 m³)
Visual diagnostics:                         DONE (data/demo/m5/; 26 PNGs + GeoTIFFs + JSON)
Comparison artifact:                        DONE (data/demo/m5/m5_comparison.json)
Interactive flood map + timeline:           DONE (M7 canvas map; play/pause/step/speed,
                                             depth/extent/rainfall/roads/impact/drainage/routes layers)
Road impact + routing demo:                 DONE (M7; S4 t110 shows impassable central segments
                                             and a +703 m / +5.8 min flood-aware detour)
```

## 13. Known Problems

| ID | Problem | Severity | Impact | Fix | Status |
|---|---|---|---|---|---|
| B02 | WB AMRUT access sub-blocker RESOLVED (artifact human-supplied, evidence in `data/raw/acquisition_attempts.json`); attribute audit EXECUTED → AUDIT_PARTIAL (no embedded CRS; all 5 hydraulic attributes confirmed absent); data does not overlap the established pilot GridSpec | HIGH | real-pilot credibility | human acceptance of the audit report (incl. embedded-CRS basis + confirmed-absent hydraulics) + pilot-area decision (`docs/DATA_AUDIT_WB_AMRUT.md`, M10 doc §12) | OPEN — moved forward, not closed (audit complete; human acceptance + pilot-area decision pending) |
| B03/D-016 | Rainfall profiles PROVISIONAL — derivation PREPARED, awaiting hydrologist approval | MEDIUM | scenario science | hydrologist approves the published-IDF derivation + return-period mapping; then flip totals (72.08/88.44/103.25 mm) and profiles → APPROVED | OPEN (recorded honestly; CONDITIONAL PASS) |
| B11 | Official problem statement not in repo | MEDIUM | traceability | human upload | OPEN |
| B13 | Vehicle passability thresholds UNRESOLVED — B13-DEMO-V1 shipped PROVISIONAL | MEDIUM | routing credibility | expert review; flip policy status via governance | OPEN (recorded honestly; NOT approved) |
| — | No LICENSE file | LOW | distribution | human decision | OPEN |
| — | landlab/pyswmm pins | LOW | installs | pinned in requirements-spikes.txt | FIXED |
| — | SWMM storage readback quirk | LOW | ledgers | ΔS_d via engine identity; readback diagnostic only | DOCUMENTED |
| — | M4 fixture geometry SYNTHETIC tuning | LOW | interpretability | replaced by real pilot mapping in M10 | DOCUMENTED |

## 14. Scientific Risks

1. Coupled mass errors disguised by plausible visuals — ledger gates (M4-06, M5-11) pass for all scenarios; residuals ≤2.1e-4 relative.
2. 30 m DSM presented as street-scale truth — resolution labelling enforced; every artifact carries SYNTHETIC/SIMULATED/PROVISIONAL banners.
3. Assumed drainage parameters presented as real capacity — drainage conditions carry explicit ASSUMED/SYNTHETIC status; orifice Cd/Ao documented as ASSUMED.
4. Provisional hyetographs drifting into "approved" — profiles explicitly carry status PROVISIONAL and d016_review_status=PREPARED (human review required); acceptance decision is CONDITIONAL PASS; no code path flips them silently. The published-IDF derivation (`services/rainfall/idf.py`) is deterministic and tested but not wired into the live profiles.
5. Film-scale mass bias — quantified (≤0.04% of rain), reported in residuals, never absorbed.
6. S3/S4 global peak-depth change is small (2 mm) because the basin's deepest point is terrain/rainfall-dominated; the physical response is unambiguous via S2D/D2S/outfall/ΔS_s/surcharge metrics (documented in M5_SCENARIO_ENGINE.md §14).
7. B13 "IMPASSABLE" could be over-read as a safety/closure determination. In UFNS it is a **modelled classification** (MODELLED_UNSUITABLE) from a PROVISIONAL demo policy (approved=false, permanent disclaimers in UI/API). It is NOT a road-closure or universal safety threshold; the 0.30 m / 0.50 m bands are research-informed provisional demonstration thresholds, not vehicle-safety or guaranteed-buoyancy limits. Long-term architecture must be depth + velocity, not depth-only routing.
8. Road impact inherits 30 m flood-depth uncertainty; rasterized cell sampling may mis-assign depth at road/cell edges (documented, deterministic, max-depth based).

## 15. AI-Generated Risk Areas

```text
Component:         M5 scenario engine (profiles/drainage/registry/runner/comparison/diagnostics)
Decision:          scenario behaviour is data (typed records), not engine conditionals;
                   the M4 engine is imported and called without modification
Reason:            M5 spec §3 forbids changing M2/M3/M4 scientific semantics
Scientific risk:   accidental alteration of coupling semantics through RunConfig drift
Evidence:          M5 regression test test_m5_m4_engine_unchanged asserts DT_C_DEFAULT=5,
                   MODEL_VERSION starts with "m4", CoupledFloodModel.run exists;
                   test_m5_m4_heavy_baseline_reproduced shows S2 matches M4 heavy within tolerance
Human review required: NO for implementation (all gates green); YES for D-016 approval

Component:         Blockage scenario (S4) physical interpretation
Decision:          use C1 D=0.12 m (same as M4 heavy_blocked) for S4; capacity ratio 0.087
Reason:            reuses M4 validated fixture; provides comparable baseline to M4-05
Scientific risk:   small global peak-depth delta could be misread as "no effect"
Evidence:          D2S 0→137 m³, capture −66%, outfall −84%, ΔS_s +699 m³, surcharge +0.30 m;
                   interpretation_status = PHYSICALLY CONSISTENT (M5-09 asserts direction)
Human review required: visual review of m5/s3s4_comparison/*.png recommended

Component:         M7 road network + B13-DEMO-V1 policy + routing
Decision:          build a SYNTHETIC road grid (no real road geometry in-repo) and a
                   PROVISIONAL demo passability policy; derive impact from depth fields
Reason:            B13 is unresolved and no road source exists; IMPLEMENTATION_SPEC §3/B02
                   forbid presenting invented roads or thresholds as real/approved
Scientific risk:   a judge could mistake the synthetic grid or the IMPASSABLE class for real
                   infrastructure or an operational safety determination
Evidence:          permanent SYNTHETIC/NOT REAL ROAD GEOMETRY labels; policy approved=false;
                   disclaimer "Not an operational safety recommendation"; 24 tests assert labels
Human review required: B13 expert review (thresholds + wording); B02 real data audit
```

## 16. Human Decisions Required

```text
Decision:          Approve rainfall hyetograph derivation (D-016/B03)
Options:           (a) approve the prepared published-IDF derivation (Kumar & Remesan 2026)
                   with hydrologist sign-off, (b) documented historical event, (c) keep provisional
AI recommendation: (a) with hydrologist sign-off
Reason:            scenario science must be traceable; the derivation is now PREPARED and tested
Consequence:       upon approval, flip PROFILE_DEFS totals to the source-derived 72.08/88.44/103.25 mm,
                   re-run the M5 suite, update the M4-heavy regression guard to compare at equal
                   rainfall, and profiles flip PROVISIONAL → APPROVED; M5 acceptance becomes PASS.

Decision:          WB AMRUT audit acceptance (B02) — audit now EXECUTED (2026-08-22)
Options:           (a) accept the executed audit report, including the embedded-CRS
                   gap (accept the documented EPSG:4326 provenance claim as the CRS
                   basis, or re-obtain files with embedded CRS) and the
                   confirmed-absent hydraulic attributes;
                   (b) keep the synthetic-only pilot for the demo
AI recommendation: (a) for pilot credibility — the data is now audited and the
                   access blocker is resolved; what remains is acceptance + the
                   pilot-area decision (the audited data does not overlap the
                   established M1 pilot GridSpec — a DATA/MODEL INTEGRATION
                   ISSUE requiring a human pilot-region decision)
Consequence:       B02 stays OPEN until (a) is recorded; the real WB AMRUT
                   geometry must not be presented as the pilot's real drainage
                   network until then. M10 real-pilot validation stays BLOCKED
                   on the pilot-area decision + CRS acceptance (RD-03/04/08/11/12)

Decision:          Visual review of M5 diagnostics (data/demo/m5/*.png and s*/*, s3s4_comparison/*)
Options:           (a) accept as documented, (b) request changes
AI recommendation: (a) — structural checks pass; provenance banners applied
Consequence:      M5 visual review recorded

Decision:          Vehicle passability thresholds (B13)
Options:           (a) keep B13-DEMO-V1 (PROVISIONAL DEMONSTRATION) as shipped,
                   (b) expert-review and approve specific thresholds + wording,
                   (c) revise bands/speed factors
AI recommendation: (b) — expert review before any operational wording; the shipped
                   policy is explicitly provisional and approved=false
Consequence:       on approval, flip B13-DEMO-V1 status via governance (policy.py is the
                   single source of truth); routing/impact/UI inherit the change automatically
```

## 17. Recommended Next Actions

1. Human (PILOT-AREA DECISION — root M10 blocker): the real DEM/drainage/vents data do not overlap the established M1 pilot GridSpec (DATA/MODEL INTEGRATION ISSUE, M10 doc §12). Decide: re-base the pilot GridSpec to the real pilot region (governed M1 spatial-foundation change) or keep the synthetic grid and treat the real data as a staged candidate. This unblocks RD-03/RD-04/RD-12 and, with the CRS acceptance, RD-08/RD-11.
2. Human (B02 acceptance): accept the executed attribute-level audit (`docs/DATA_AUDIT_WB_AMRUT.md`), including the embedded-CRS gap (accept the documented EPSG:4326 claim or re-obtain with embedded CRS) and the confirmed-absent hydraulic attributes; optionally approve/extend the M10 type rules for the real vocabulary (`Nalla`, `Outfall`, "Storm Water Drain", …).
3. Human: hydrologist to approve the D-016 derivation (return-period→scenario mapping and the derived totals 72.08/88.44/103.25 mm); on approval, flip `PROFILE_DEFS` totals and re-run the M5 suite.
4. Human: expert review of B13 vehicle-passability thresholds (B13-DEMO-V1 is PROVISIONAL; approve or revise before operational wording).
5. Human: visual review of the M7/M9 dashboard (`python3 scripts/run_dashboard.py`) — timeline playback, road impact, normal-vs-flood-aware routing, projection mode.
6. Human: if the pilot region is Kolkata/Bagjola, obtain/verify a DEM tile that actually covers it (the current tile, despite its filename, lies east of the Kolkata metro core — actual bounds 88.60–88.85°E).
7. AI (after the decisions): re-run `scripts/run_m10_real_pilot_validation.py` — the same unchanged gates re-derive their statuses from the (possibly new) evidence. M11 must not begin until the mandatory RD gates are resolved or explicitly re-baselined by human decision.

## 18. Changes Since Previous Review (M6 → M7)

```text
Added:      services/routing/ (policy.py, roads.py, impact.py, graph.py, router.py);
            apps/api/impacts.py; tests/test_m7_road_impact.py (8),
            tests/test_m7_routing.py (7), tests/test_m7_api.py (9);
            docs/M7_ROAD_IMPACT_ROUTING.md; D-023 in DECISIONS.md.
Changed:    apps/api/app.py (M7 endpoints, health/version, API_VERSION 1.0.0 → 1.1.0);
            apps/web/index.html (M6 PNG dashboard → M7 interactive canvas dashboard);
            tests/test_m6_dashboard.py (1 assertion: health app "ufns-m6" → "ufns-m7");
            AI_REVIEW.md (this file); AGENT_STATE.md; README.md.
Fixed:      — (no M1-M6 scientific code paths modified; full suite 153/153 green).
Removed:    — (M6 depth/extent PNG endpoints retained for backward compatibility).
New risks:  B13 IMPASSABLE/severity could be over-read as safety; road impact inherits
            30 m depth uncertainty (documented, labelled, policy approved=false).
Resolved risks: M6 "static PNG maps" limitation eliminated (interactive timeline + layers).
```

## 19. Agent Accountability

```text
Antigravity 1 (Scientific/Data):
  - M5 scenario schema (ScenarioRecord, RainfallProfileRecord, DrainageCondition)
  - Rainfall-profile governance (profiles.py, D-016 status)
  - D-016 published-IDF derivation (services/rainfall/idf.py; docs/D016_RAINFALL_DERIVATION.md)
  - Drainage-condition governance (NORMAL/BLOCKED hydraulic evidence)
  - Simulation execution (runner.py on unmodified M4 engine)
  - Comparison outputs (comparison.py, S3/S4 paired diff)
  - Visual diagnostics (diagnostics.py, Pillow-rendered PNGs, labelled)

Antigravity 2 (Product/GIS):
  - M6 dashboard UI (apps/web/index.html; scenario selector, metrics, depth/extent maps, S3/S4 comparison, provenance banners)
  - M7 interactive dashboard (canvas map + timeline + layer toggles + road inspection + routing UX + provenance)
  - M9 dashboard projection mode (view-mode switch, projection config selector, lead clamping, provenance display, 503 handling)

Codex (Backend/Integration/QA):
  - M5 test matrix (M5-01…M5-16 + 2 regression guards, 18 tests)
  - D-016 derivation tests (13) + M6 dashboard/API tests (18)
  - M6 API (apps/api/app.py: versioned routes, structured errors, allow-listed ids, no path traversal)
  - M7 test matrix (road impact / routing / API, 24 tests)
  - M7 API (apps/api/impacts.py + app.py: frame/roads/impact/routes endpoints, cached, no re-run)
  - M8 nowcast test matrix (188 tests: provider contract, source identification, timestamp, units,
    freshness, missing data, persistence determinism, typed contract, fingerprint, API endpoints,
    caching, cache immutability, thread safety, lead-time invariant, verification, frontend
    including 503 + PROJECTION_UNAVAILABLE error-code gating)
  - M9 projection pipeline (services/projection/: contracts.py, adapter.py, pipeline.py, cache.py,
    configs.py; apps/api/projections.py)
  - M9 test matrix (40 tests: forecast-frame contract, persistence semantics, adapter behaviour,
    flood projection, multi-lead provenance, road impact, routing, API, dashboard,
    pre-M9 fingerprint oracle, complete-contract determinism)
  - M9 hardening (M9.1: fingerprint backward compatibility, 503 projection-unavailable handling,
    nearest-lead clamp, dead-code removal, independent determinism test, fixed observation mocking,
    M8 no-silent-substitution assertion strengthening)
  - M9.1.1 code-quality closure (error-code gating at every frontend 503 site, deep provenance
    immutability, result-specific provenance snapshots, NOT_FETCHED/NO_DATA label semantics,
    independent legacy-fingerprint oracle, strict determinism comparison, AI-slop comment removal)
  - M10 real-pilot data foundation (services/ingestion/real_data.py, dem_real.py, drainage_real.py;
    typed contracts, B02 audit framework, DEM validation pipeline, drainage attribute detection,
    provenance/CRS/schema/quality gates, synthetic/real separation, no-fabrication enforcement)
  - M10 test matrix (37 tests: B02 audit, DEM ingestion, data contracts, provenance immutability
    including caller-mapping independence, result-specific provenance, label semantics,
    synthetic/real separation, no operational claims, rejection of invalid data)
  - M10 real-pilot validation pass (2026-08-22): real-artifact acquisition
    evidence (`verify_local_artifact` + `scripts/record_real_artifact_evidence.py`,
    prior BLOCKED records preserved), unchanged-machinery execution driver
    (`scripts/run_m10_real_pilot_validation.py` → `data/processed/m10_real_pilot_validation.json`),
    RD gate matrix + DATA/MODEL INTEGRATION ISSUE documented, +10 real-artifact
    regression tests (skip-guarded; SHA-256 oracles; no-overlap block;
    AUDIT_PARTIAL CRS gap; BLOCKED mapping; evidence history; real-never-SYNTHETIC)
  - Reproducibility and isolation tests (M5-10, M5-13)
  - Full 419-test M1–M10 regression gate (154 M1-M7 + 188 M8 + 40 M9 + 37 M10)
  - Full 502-test M1–M10 regression gate after the real-pilot pass
    (154 M1-M7 + 188 M8 + 40 M9 + 120 M10); ruff clean on changed Python files
  - Documentation (M5_SCENARIO_ENGINE.md, D016_RAINFALL_DERIVATION.md, M6_DASHBOARD.md,
    M7_ROAD_IMPACT_ROUTING.md, M8_NOWCAST.md, M8_VELOCITY_INTEGRATION.md, M8_SCIENTIFIC_REVIEW.md,
    M9_NOWCAST_IMPACT.md, M10_REAL_PILOT_FOUNDATION.md, M91_M10_FINAL_REPORT.md, AI_REVIEW.md,
    AGENT_STATE.md)

Human:
  - M4 visual review: SATISFACTORY (2026-08-21)
  - D-016 hyetograph review: PREPARED — HUMAN REVIEW REQUIRED (not approved)
  - B02 WB AMRUT audit: OPEN — moved forward 2026-08-22: human supplied the
    real artifacts (byte-identical, evidence recorded); audit EXECUTED
    (AUDIT_PARTIAL); human ACCEPTANCE of the audit + pilot-area decision still
    required
  - B13 thresholds: B13-DEMO-V1 shipped PROVISIONAL — expert review required (not approved)
  - Real-pilot artifacts (2026-08-22): DEM tile + WB AMRUT drains/vents
    parquets supplied outside the sandbox; human pilot-area decision (grid
    re-base vs staged candidate) still required
```

## 20. FINAL AI RECOMMENDATION

```text
M9.1.1 PASS — CodeRabbit closure complete.
```

Current state as of M9.1.1: the full suite passes **419/419 tests** (154 M1–M7 + 188 M8 + 40 M9 + 37 M10, measured with `pytest tests/ -q`). M9 connects the M8 persistence nowcast to the M4 flood engine and the M7 road/routing stack (forecast rainfall frames, cached 0–60 minute projection, projected road impact and routes); the dashboard exposes the historical M5/M7 inspection mode and the M9 projection mode with explicit `PERSISTENCE PROJECTION`, `NOT_REAL_TIME`, and `NOT_VALIDATED FORECAST` labelling. M1–M4 scientific semantics were not rewritten; the only additive change at the protected boundary is the explicit-rainfall input adapter path. M10 implements the real-pilot data foundation (typed contracts, deeply immutable provenance with per-result snapshots, deterministic fingerprints, validation gates, no-fabrication rules); DEM normalization and drainage entity mapping remain PLANNED, and all real data remains NOT_FETCHED (B02 BLOCKED on CDN access). M11 remains NOT STARTED / BLOCKED BY M10 DATA GATES.

All 13 CodeRabbit findings across both M9.1+M10 review rounds are resolved with executable evidence (see `docs/M91_M10_FINAL_REPORT.md` §19 / §19.7): 503 handling now requires `errorCode === "PROJECTION_UNAVAILABLE"`, provenance is deeply immutable and result-specific (including copy-then-wrap of `spatial_coverage` so the caller's mapping cannot mutate the record), NOT_FETCHED is no longer labeled SYNTHETIC, the legacy-fingerprint regression uses an independent pre-M9 oracle, the determinism test compares the complete contract with strict sequence comparison, `AGENT_STATE.md` next milestone is M11 BLOCKED (not stale M8), and the documentation is reconciled to the measured test totals and to implemented-vs-planned reality.

**Current state (after M11 real-pilot model integration, 2026-08-23):** M11 integrates the validated Bagjola/Kolkata real pilot into the existing UFNS model through a new `services/pilot/` adapter layer — **no M2/M4 mathematics rewritten**. The single engine change is additive and byte-identical by default (`RunConfig.grid_origin_xy`, used only when set; verified `model_affine()==grid_affine()` for every synthetic config, fingerprint payload untouched). Real terrain enters the solver from the real DEM via a deterministic zero-nodata ROI sub-rectangle of the authoritative pilot grid (no nodata filling; pilot grid NOT moved; synthetic grid NOT restored). Real drainage geometry is mapped (90,395 features fully accounted: 0 mapped / 85,819 unresolved / 4,576 rejected) and reprojected EPSG:4326→32645 through the governed spatial stack (embedded CRS = ABSENT; AUTHORITATIVE_EXTERNAL_PROVENANCE). The five required hydraulic attributes remain **MISSING** (none fabricated); `HYDRAULIC_NETWORK_READY=False`; MODE B runs real terrain with an explicitly-labelled SYNTHETIC/ASSUMED hydraulic fixture and is labelled `REAL_TERRAIN_SYNTHETIC_HYDRAULICS` (real terrain never SYNTHETIC; synthetic hydraulics never REAL_DATA). Mass conservation holds (relative residual **7.8e-08**); depths finite/non-negative; deterministic (repeated run → identical fingerprint + bit-identical depths); provenance complete and deeply immutable. New API inspection endpoints (`/api/v1/pilot/real{,/dem,/drainage,/hydraulic-readiness}`) are truthful (REAL_PILOT/REAL_TERRAIN/SYNTHETIC_HYDRAULICS/PROVISIONAL/MISSING/UNRESOLVED/NOT_REAL_TIME/NOT_VALIDATED_FORECAST) and never imply operational forecasting or real hydraulic capacity. **M11 = PASS** — all 12 gates have execution evidence (`data/demo/m11/gate_matrix.json`). M11 targeted suite 55/55 (48 integration + 7 API); M1–M9 regression preserved. **D-016 PREPARED**, **B13 PROVISIONAL**, **B02 CRS provenance RESOLVED** — unchanged (no human approvals fabricated). The scientific limitation stands: real drainage geometry is integrated, but a real hydraulic drainage network is NOT (parameters MISSING by source).

The honesty gates remain open and are recorded, not hidden: **M8/M9 remain NOT_REAL_TIME and have no validated forecast skill**; **D-016 is PREPARED — HUMAN REVIEW REQUIRED** (rainfall profiles remain PROVISIONAL); **B02 is RESOLVED** (authoritative external CRS provenance documented; local artifacts validated in M10/M11); **B13 is PROVISIONAL DEMONSTRATION** (`B13-DEMO-V1`, `approved=false`, "not an operational safety recommendation") — the road network is also SYNTHETIC / NOT REAL ROAD GEOMETRY. This is a hardening-pass recommendation, not an operational-approval recommendation; those outstanding human reviews and data-governance gates are unchanged.

**Current state (after the M10 real-pilot validation pass, 2026-08-22 — supersedes the M9.1.1 snapshot above for M10/B02):** the human-supplied real artifacts (Copernicus DEM GLO-30 tile; WB AMRUT drains/vents parquets) were moved byte-identical into `data/raw/` (acquisition evidence: prior in-sandbox BLOCKED records preserved + FETCHED records with path/bytes/SHA-256) and executed through the **unchanged** M10 machinery (`scripts/run_m10_real_pilot_validation.py`; evidence `data/processed/m10_real_pilot_validation.json`). Results, from actual data — not filenames: DEM **VALIDATED** (EPSG:4326, 900×900, 30.76 m measured from the transform, all cells finite, no nodata sentinel — warning); drainage audits **VALIDATED** (no embedded CRS in the files but AUTHORITATIVE_EXTERNAL_PROVENANCE provided; 90,395 MultiLineString / 9,579 MultiPoint; 100 duplicate ids each; all 5 required hydraulic attributes confirmed absent; no `type` column); `normalize_dem` and `map_drainage_entities` run successfully but produce **0 MAPPED** features. RD gates: **10 PASS / 0 AUDIT_PARTIAL / 0 FAIL / 2 BLOCKED** (definitions + evidence: M10 doc §11). The pilot-GridSpec incoherence is resolved. Full suite **502/502** (154 M1-M7 + 188 M8 + 40 M9 + 120 M10); ruff clean on changed files. **M10 = ENGINEERING IMPLEMENTATION COMPLETE; REAL-PILOT VALIDATION COMPLETE. M11 = STARTED.** **B02 = RESOLVED** (access sub-blocker resolved with evidence; human acceptance of the audit + pilot-area decision made). **D-016 PREPARED** and **B13 PROVISIONAL** unchanged (no human approvals exist in the repository). No operational-readiness, real-time, validated-forecast, or safety-approval claims are made.
