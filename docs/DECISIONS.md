# Architecture and Scientific Decision Log

All entries dated 2026-08-21 are **proposed** until the human team records approval. A proposal guides investigation but is not permission to make irreversible scientific claims.

---

## D-001 — Use a modular monolith for the student-scale prototype

**Status:** Proposed — pending human approval
**Decision:** Keep scientific modules in one monorepo and deploy a web app, FastAPI process, bounded simulation worker process, PostGIS, and artifact storage rather than independent microservices.
**Date:** 2026-08-21
**Problem:** The system has clear scientific boundaries but only 2 vCPU, 3.8 GiB RAM in the current sandbox and a student deployment budget.
**Options:**

1. many independently deployed microservices and a message bus;
2. single unstructured application;
3. modular monolith with typed module boundaries and a separate CPU worker process.

**Chosen solution:** Option 3.
**Reason:** Preserves interfaces/testability without network, deployment, observability, and memory overhead at every boundary. CPU simulation is isolated from HTTP.
**Trade-offs:** Lower independent scaling and fault isolation than microservices; module discipline must be enforced in code review.
**Validation:** Measure API responsiveness during a simulation; contract/integration tests across modules; revisit only if demonstrated concurrency requires independent scaling.

---

## D-002 — Use established local-inertial 2-D surface hydraulics

**Status:** Proposed — pending hydrologist/human approval and dependency spike
**Decision:** Wrap Landlab `OverlandFlow`, based on the de Almeida/Bates local-inertial shallow-water approximation, instead of inventing a raster redistribution algorithm.
**Date:** 2026-08-21
**Problem:** Surface rain must produce physically interpretable depth and terrain-driven movement fast enough for a student CPU.
**Options:**

1. D8 accumulation/cellular spreading;
2. custom diffusive/kinematic raster solver;
3. established Landlab local-inertial solver;
4. full 2-D shallow-water package requiring heavier setup/compute;
5. precomputed ML flood map.

**Chosen solution:** Option 3 for MVP.
**Reason:** It solves a documented reduced-physics formulation, supports depth/discharge and adaptive stepping, has published verification literature, and avoids novel physics. It is a credible speed/complexity compromise for shallow, slowly varying urban inundation.
**Trade-offs:** Neglects convective acceleration, uses a structured raster representation, has limitations in steep/rapid/supercritical flow, and still requires boundary/roughness/terrain review. A library choice does not validate local predictions.
**Validation:** Reproduce library example; closed-bowl and planar-flow tests; wetting/drying; UK Environment Agency benchmark candidates; convergence and mass ledger; benchmark current hardware. Stop for review if it cannot couple conservatively or install reliably.

---

## D-003 — Use EPA SWMM dynamic wave for drainage

**Status:** Proposed — pending hydrologist/human approval and Python-interface spike
**Decision:** Represent the 1-D drainage network in EPA SWMM 5.2 dynamic-wave routing and drive/read it through a maintained Python toolkit.
**Date:** 2026-08-21
**Problem:** The model must credibly represent conduit capacity, pressurization, surcharge, backwater, and flow reversal without inventing underground hydraulics.
**Options:**

1. custom directed graph with fixed per-edge capacity;
2. EPA SWMM kinematic wave;
3. EPA SWMM dynamic wave;
4. commercial drainage engine.

**Chosen solution:** Option 3.
**Reason:** SWMM is established/open, documented by US EPA, and dynamic wave can represent the required surcharge/backwater/reversal behaviors.
**Trade-offs:** More computation and smaller timesteps; network data requirements are high; Python stepping/coupling behavior must be verified. Missing local dimensions/inverts still make results scenario-based.
**Validation:** Compare current `epaswmm`, SWMM Toolkit/PySWMM, and `swmm-api`; reproduce an EPA example; inspect continuity report; controlled capacity/backflow/blockage tests; verify Linux/Python 3.11 packaging and licence.

---

## D-004 — Couple surface and drains by conservative two-way inlet exchange

**Status:** Proposed — pending hydrologist/human approval and coupling spike
**Decision:** Exchange water according to surface head, drain node head, and a cited inlet weir/orifice formulation; cap by available volume/capacity; return SWMM surcharge/backflow to mapped surface cells.
**Date:** 2026-08-21
**Problem:** One-way drainage removal cannot represent surcharge/backflow and can create/destroy water if independently calculated.
**Options:**

1. fixed drainage sink independent of node state;
2. one-way inlet capture plus separately painted surcharge;
3. signed head-driven two-way exchange with equal-and-opposite ledgers;
4. a single monolithic 1-D/2-D commercial engine.

**Chosen solution:** Option 3.
**Reason:** Makes capacity and node head causally control capture/backflow and gives an auditable conservation identity.
**Trade-offs:** Operator splitting can oscillate; inlet parameters are often unknown; coupling interval affects results.
**Validation:** One-cell/one-storage equilibrium, capture, surcharge and oscillation tests; timestep halving; UK Environment Agency surcharge benchmark candidate; exchange IDs must cancel exactly in the whole-system ledger.

---

## D-005 — Default to native 30 m terrain and a small domain

**Status:** Proposed — pending pilot/data approval
**Decision:** Use an approximately 4 km × 4 km domain at 30 m when Copernicus/ALOS global DSM is the best accepted terrain. Permit a 10 m model only with a defensible higher-resolution DTM/DEM; flag any upsampling.
**Date:** 2026-08-21
**Problem:** The prompt asks for street-level impact, but available open terrain identified so far is 30 m and compute is limited.
**Options:**

1. blindly resample 30 m DSM to 10 m and claim high resolution;
2. 30 m data-honest screening pilot;
3. block all work until LiDAR is obtained;
4. very small 10 m synthetic terrain only.

**Chosen solution:** Option 2, while pursuing high-resolution terrain and retaining a synthetic verification fixture.
**Reason:** Avoids false precision and remains executable. Street segments can be impacted by neighbourhood-scale depth while the limitation is explicit.
**Trade-offs:** Kerbs, underpasses, drains, many roads, and buildings are unresolved; shallow-depth assignment is highly uncertain; no curb-scale claim.
**Validation:** Runtime/memory benchmark; cell-size/DEM-source sensitivity; show native/working resolution in every output; revisit after pilot terrain audit.

---

## D-006 — Use dual CRS policy and strict vertical-reference handling

**Status:** Proposed — pending pilot approval
**Decision:** Use longitude/latitude OGC:CRS84/EPSG:4326 for web/API interchange and one local projected metric CRS for simulation. Reject missing/implausible CRS and do not treat drainage elevations as real until their vertical reference is compatible with terrain.
**Date:** 2026-08-21
**Problem:** Hydraulic slopes, volumes, lengths, and route buffers cannot be computed in angular coordinates, and vertical mismatch can reverse hydraulic behavior.
**Options:**

1. calculate directly in EPSG:4326;
2. hardcode one India-wide UTM zone;
3. select a projected CRS per pilot and preserve explicit interchange/vertical metadata.

**Chosen solution:** Option 3.
**Reason:** Provides metric calculations and an explicit transformation boundary without locking the system to one city.
**Trade-offs:** More metadata and validation; multi-zone/regional domains need a different suitable projection.
**Validation:** round-trip coordinate tests, known-distance/area tests, extent plausibility, axis-order tests, vertical metadata audit, and fail-fast mismatch cases.

---

## D-007 — Keep bulk rasters in versioned artifact storage

**Status:** Proposed — pending system architecture approval
**Decision:** Store source/result raster cubes as immutable COG/CF-NetCDF/Zarr artifacts with checksums; use PostgreSQL/PostGIS for lineage, run state, drainage/road vectors, risk, routes, alerts, and spatial indexes.
**Date:** 2026-08-21
**Problem:** Flood/rainfall rasters across many timesteps are bulky, while vector/status queries need relational and spatial indexing.
**Options:**

1. all cells/timesteps in one database table;
2. all state in ad-hoc files;
3. hybrid artifact store plus PostGIS catalog/vector state;
4. dedicated cloud data cube from day one.

**Chosen solution:** Option 3.
**Reason:** Fits COG/NetCDF tooling and cheap local/S3 storage while preserving queryable metadata and vectors.
**Trade-offs:** Requires artifact/database consistency and backup policy; local filesystem profile is not horizontally scalable.
**Validation:** content checksums, transactional manifest finalization, missing-artifact failure tests, map tile/load benchmark.

---

## D-008 — Keep a deterministic synthetic hydraulic fixture

**Status:** Proposed — pending scientific/data-policy approval
**Decision:** Include a fully parameterized synthetic catchment/drain network for numerical verification and guaranteed four-scenario demonstration. Use audited real static layers separately where available, and label every synthetic/assumed field.
**Date:** 2026-08-21
**Problem:** Open drain linework may lack dimensions, inverts, inlets, outlets, and licence certainty; reproducibility cannot depend on inaccessible municipal data.
**Options:**

1. invent parameters and present the network as real;
2. omit drainage until perfect data appears;
3. synthetic verified fixture plus a separately status-labelled real-area pilot;
4. fixed pre-rendered maps.

**Chosen solution:** Option 3.
**Reason:** Allows honest scientific verification and blockage demonstration without fabricating local truth.
**Trade-offs:** Judges must understand that the synthetic network is a demonstration, not city asset intelligence; a real pilot remains data-limited.
**Validation:** deterministic seed/checksum, documented design equations/parameters, visible status badges, automated check that synthetic data cannot be served under a real/observed status.

---

## D-009 — Prefer West Bengal AMRUT data audit; retain Bengaluru fallback

**Status:** Proposed — pilot is intentionally undecided
**Decision:** First audit a small West Bengal AMRUT urban area because candidate drain lines and vent points exist. If primary provenance/attributes/coverage are inadequate, audit Bengaluru's published primary/secondary/tertiary drain maps.
**Date:** 2026-08-21
**Problem:** A pilot is needed, but city choice should follow actual data fitness rather than name recognition.
**Options:**

1. Kolkata/West Bengal candidate;
2. Bengaluru candidate;
3. Hyderabad candidate;
4. synthetic-only generic city;
5. human-supplied city/data.

**Chosen solution:** Audit order 1 → 2, while accepting option 5 if the team has stronger data; keep option 4 as verification.
**Reason:** The West Bengal candidate uniquely advertises vent points as well as drains; Bengaluru has public hierarchy linework. No candidate currently has confirmed hydraulic attributes.
**Trade-offs:** The ultimate pilot may not be a headline metro; secondary aggregator provenance needs verification; city change affects UTM CRS and prepared data but not service contracts.
**Validation:** actual file schema/bounds/geometry/licence audit, parameter completeness report, terrain/road overlap, domain selection, human approval. The collection name must not be assumed to include central Kolkata.

---

## D-010 — No mandatory ML in the MVP

**Status:** Proposed — pending product approval
**Decision:** Implement and evaluate persistence first; add statistical/advection and ML only when suitable sequences and measurable improvement exist.
**Date:** 2026-08-21
**Problem:** The problem asks for nowcasting but available high-resolution low-latency rainfall training data/access is unresolved and no GPU is available.
**Options:**

1. start with ConvLSTM/large model;
2. persistence, then simple baseline, then justified ML;
3. no forecast component;
4. label an external NWP forecast as UFNS AI nowcast.

**Chosen solution:** Option 2.
**Reason:** Establishes a hard-to-beat reference, avoids leakage/fake metrics, and keeps physics as priority.
**Trade-offs:** Less flashy initial AI story; persistence may be weak at long leads.
**Validation:** rolling-origin lead-specific metrics on actual held-out fields. Retain the simplest best-performing model.

---

## D-011 — Use explicit provenance and null probability

**Status:** Proposed — pending product approval
**Decision:** Every asset/result has a provenance class; deterministic `flood_probability` is null, and scenario-member frequencies are not called probabilities without justified weights.
**Date:** 2026-08-21
**Problem:** Synthetic forcing, static real maps, external forecasts, and model predictions can otherwise be visually conflated; deterministic output has no statistical probability.
**Options:**

1. one generic “live” badge;
2. assign attractive confidence percentages;
3. explicit provenance/quality and unknown/null values where unsupported.

**Chosen solution:** Option 3.
**Reason:** Satisfies scientific honesty and traceability.
**Trade-offs:** UI and contracts are more verbose; uncertainty cannot be reduced to one unsupported number.
**Validation:** schema constraints, UI tests, run lineage integration test, and automated prohibition of synthetic-as-observed labels.

---

## D-012 — Flood-aware routing means changed graph costs and closures

**Status:** Proposed — passability thresholds pending expert review
**Decision:** Sample depth along each road, apply vehicle-profile penalties/closures, and compute actual alternative routes. Use “lower modelled exposure,” not guaranteed “safe.”
**Date:** 2026-08-21
**Problem:** Drawing an alternate line without changing graph impedance is not flood-aware routing and can be dangerous.
**Options:**

1. static preselected green route;
2. binary road flood flag only;
3. max/p95 depth, wet length, nodata-aware cost, closure, and route explanation;
4. route solely by straight-line distance.

**Chosen solution:** Option 3.
**Reason:** Makes flood predictions causally change path selection and exposes the ETA/exposure trade-off.
**Trade-offs:** Passability depends on vehicle, flow, road geometry, uncertainty, and policy; depth-only cost is simplified.
**Validation:** exact toy graphs, closed-edge exclusion, disconnected/no-route cases, forecast-time route change, reviewed profile thresholds before real use.

---

## D-013 — Treat proposed depth bands as demo severity, not safety standards

**Status:** Proposed — pending hydrology/disaster-management review
**Decision:** Use configurable 0.05 m, 0.15 m, and 0.30 m boundaries for demonstration severity if approved; store the thresholds with outputs and keep route passability separate.
**Date:** 2026-08-21
**Problem:** The prompt supplies example bands but explicitly says they are not universal safety standards.
**Options:**

1. hardcode and market as official safety classes;
2. omit quantitative severity;
3. configurable demo bands with visible disclaimer and version.

**Chosen solution:** Option 3.
**Reason:** Supports consistent visualization while preserving policy/scientific honesty.
**Trade-offs:** A class label can still be overinterpreted; the UI must show numeric depth and disclaimer.
**Validation:** boundary unit tests, configuration/version display, reviewer sign-off before any emergency profile mapping.

---

## D-014 — Do not indiscriminately fill DEM depressions

**Status:** Proposed — pending GIS/hydrology approval
**Decision:** Preserve legitimate urban depressions and condition only documented artifacts/verified flow structures, with before/after reports and sensitivity.
**Date:** 2026-08-21
**Problem:** Sink filling simplifies drainage extraction but can erase the locations where pluvial water should accumulate.
**Options:**

1. fill all pits;
2. never condition any cell;
3. reviewed minimal conditioning and verified culvert/channel breaching.

**Chosen solution:** Option 3.
**Reason:** Balances artifact correction with physical depression storage.
**Trade-offs:** Requires human review and source knowledge; unresolved DSM artifacts may remain.
**Validation:** affected-cell/volume report, maps, original-versus-conditioned sensitivity, known-feature checks.

---

## D-015 — Mass balance is a run-level quality gate

**Status:** Proposed — numeric thresholds pending benchmark evidence
**Decision:** Track interval/component/whole-system volumes; surface–drain exchange cancels internally. Initially flag >1% residual and fail >5% plus absolute dry-run checks.
**Date:** 2026-08-21
**Problem:** Coupled solvers can hide water creation/loss, particularly during clipping, dry-cell handling, and inlet exchange.
**Options:**

1. no ledger;
2. final surface volume only;
3. full rainfall/loss/outflow/storage/drain ledger with gates.

**Chosen solution:** Option 3.
**Reason:** Conservation is a central credibility and debugging requirement.
**Trade-offs:** Additional state/instrumentation; relative percent is unstable for tiny storms and needs absolute checks.
**Validation:** exact closed systems, exchange equality, SWMM continuity parsing, dry cases, extreme cases, timestep/grid convergence. Thresholds are revised from measured numerical evidence, never loosened merely to pass.

---

## D-016 — Derive demo rainfall scenarios from named design storms or documented events

**Status:** Approved 2026-08-21 (human team, IMPLEMENTATION_SPEC.md §4 B03/B05/B06, §2, §15)
**Decision:** The normal/heavy/extreme demo hyetographs must be derived from named, cited sources — e.g., alternating-block hyetographs built from published intensity–duration–frequency curves, or a documented historical rainfall event — and the derivation must be recorded in the scenario manifest. Intensities may not be invented ad hoc during coding.
**Date:** 2026-08-21
**Problem:** The four deterministic scenarios are the demo's scientific core, but no scenario hyetograph has a defined derivation. Invented intensities would silently define what "extreme" means.
**Options:**

1. ad-hoc plausible intensities chosen by the implementing agent;
2. cited design-storm derivation approved by a hydrologist (recommended);
3. documented historical event rainfall where a suitable record exists;
4. no extreme scenario (reject — the blockage comparison depends on it).

**Chosen solution:** Option 2, with Option 3 as an accepted alternative when data supports it.
**Reason:** Keeps the demo deterministic and reproducible while making every intensity traceable to an external authority.
**Trade-offs:** Requires a hydrologist review step and a slightly longer scenario definition phase.
**Validation:** scenario manifest records derivation, source, and parameters; identical seeds reproduce identical fields; audit review before Phase 5 acceptance.

---

## D-017 — Live mode requires a verified quantitative rainfall feed

**Status:** Approved 2026-08-21 (human team, IMPLEMENTATION_SPEC.md §4 B03/B05/B06, §2, §15)
**Decision:** Live mode (including live persistence nowcasting) is activated only after a quantitative near-real-time rainfall feed is verified in writing: source, terms, latency, resolution, and machine-access method. Until then, the live controls display "unavailable" and persistence is demonstrated in replay/historical mode only. Simulated data may never masquerade as live data.
**Date:** 2026-08-21
**Problem:** No verified live feed exists today (IMD access is pending, no open quantitative Indian radar API is confirmed). A "live" toggle fed by synthetic fields would be fabricated nowcasting.
**Options:**

1. ship a live toggle driven by synthetic/replay data;
2. gate live mode on a verified feed (recommended);
3. remove all live UI until Phase 9.

**Chosen solution:** Option 2.
**Reason:** Preserves the product story while keeping the honesty guarantees of D-011.
**Trade-offs:** Judges see replay/demo mode only unless access is granted in time; live-path adapters remain optional and fail visibly.
**Validation:** automated prohibition of `SIMULATED_SCENARIO` data behind live endpoints; staleness/gap tests per the red-team matrix.

---

## D-018 — DEM licensing posture: Copernicus DEM primary, FABDEM restricted

**Status:** Approved 2026-08-21 (human team, IMPLEMENTATION_SPEC.md §4 B03/B05/B06, §2, §15)
**Decision:** Use Copernicus DEM GLO-30 (free for the general public, attribution required; pilot-tile coverage must be verified) as the primary pilot DEM. FABDEM v1.2 (CC BY-NC-SA 4.0, confirmed during the audit) is restricted to internal sensitivity/cross-check runs unless the human team explicitly accepts the ShareAlike/non-commercial implications for any derived redistribution.
**Date:** 2026-08-21
**Problem:** FABDEM is scientifically attractive (buildings/forests removed) but its NC-SA terms inherit into derived terrain products and could constrain SIH demo distribution.
**Options:**

1. adopt FABDEM as primary and accept NC-SA constraints;
2. Copernicus DEM primary; FABDEM internal-only (recommended);
3. avoid FABDEM entirely.

**Chosen solution:** Option 2.
**Reason:** Maximises demo redistributability while keeping a valuable cross-check available for internal science.
**Trade-offs:** DSM artifacts (buildings/vegetation) remain in the primary terrain; conditioning policy (D-014) must absorb this.
**Validation:** licence string recorded in the bundle manifest; attribution notices in dashboard/docs; GLO-30 pilot-tile coverage check at ingestion.

---

## D-019 — Landlab adapter applies spatially variable rainfall and infiltration

**Status:** Approved 2026-08-21 (human team, IMPLEMENTATION_SPEC.md §4 B03/B05/B06, §2, §15)
**Decision:** Because Landlab `OverlandFlow` accepts rainfall as a uniform scalar intensity, the `SurfaceModel` adapter must apply spatially variable rainfall fields and per-cell infiltration (Horton) as explicit, ledger-accounted depth increments/removals at the coupling cadence, verified by closure and stability tests in the Phase 1 spike.
**Date:** 2026-08-21
**Problem:** The rainfall contract is spatially variable, but the chosen component cannot consume it directly; undocumented per-cell manipulation of solver state could silently break conservation.
**Options:**

1. restrict the model to uniform rainfall (reject — contract requires spatial fields);
2. adapter-level per-cell application with ledger accounting and spike verification (recommended);
3. substitute a different surface solver.

**Chosen solution:** Option 2.
**Reason:** Preserves the chosen established solver and the spatial rainfall contract while keeping mass accounting explicit.
**Trade-offs:** Adapter code is sensitive (HIGH-RISK AI AREA per audit §14); spike scope grows slightly.
**Validation:** single-cell closure tests, spatially variable rain test, infiltration-capped-by-available-volume tests, timestep-halving sensitivity.

---

## D-020 — Human approval of Phase 0: implementation begins

**Status:** Approved 2026-08-21 — human team decision (recorded in `IMPLEMENTATION_SPEC.md` §0)
**Decision:** The human team approved the Phase 0 architecture and implementation direction: West Bengal AMRUT pilot (subject to the defined data audit), Landlab `OverlandFlow`, EPA SWMM Dynamic Wave, 30 m / ~4×4 km physical resolution, real+assumed+synthetic drainage parameters, baseline-first rainfall with a strengthened nowcast layer, depth+extent+supported uncertainty outputs, flood-aware routing as a major feature, a substantially strengthened GIS dashboard, physics/benchmark validation, and live data as a later phase.
**Date:** 2026-08-21
**Problem:** Phase 0 was blocked pending human approval of the six gates and the audit's proposed decisions.
**Options:**

1. keep everything as proposed;
2. approve with the added emphasis in the human table (nowcast, uncertainty, routing, dashboard);
3. reject/re-scope specific areas.

**Chosen solution:** Option 2.
**Reason:** Consistent with the audit verdict (CONDITIONALLY READY); the added emphasis strengthens the SIH story without changing the scientific core.
**Consequences recorded:** D-001…D-015 are approved via this umbrella entry (their implementation remains gated by the Phase 1/2 spikes and audits they already specify, e.g. SWMM spike stop-conditions). D-016 (design-storm derivation), D-017 (live-mode gate), D-018 (DEM licensing default posture), and D-019 (Landlab spatial-rainfall adapter) are approved as recorded in `PHASE0_APPROVAL.md`.
**Validation:** milestone gates M1–M12 in `IMPLEMENTATION_SPEC.md`; `docs/AI_REVIEW.md` after every milestone; human review gates §24.

---

## D-021 — D-016 rainfall derivation: adopt published Bagjola Canal (Kolkata) IDF, keep profiles PROVISIONAL until approval

**Status:** Proposed 2026-08-21 — AI-prepared; requires hydrologist sign-off (no approval fabricated)
**Decision:** Resolve D-016 (Option A) against Kumar & Remesan (2026), "Integrating Revised IDF Curves with Coupled 1D-2D MIKE+ Modelling…", Water Resources Management 40(3):115 (DOI 10.1007/s11269-026-04514-5). Derive deterministic 3-hour storm totals for the 2/5/10-year return periods (recommended NORMAL/HEAVY/EXTREME mapping, per CPHEEO 2019): 72.08 / 88.44 / 103.25 mm. Keep the live M5 profiles PROVISIONAL at 20/45/90 mm and record D-016 as PREPARED — HUMAN REVIEW REQUIRED.
**Date:** 2026-08-21
**Problem:** The provisional 20/45/90 mm totals have no documented return-period or source basis; the source-derived totals differ materially (notably NORMAL 20→72 mm), so a flip changes every scenario result and the M4-heavy regression baseline.
**Options:**

1. flip the live profiles to the source-derived totals now;
2. prepare + document + test the derivation, keep profiles PROVISIONAL, flip on hydrologist approval (chosen);
3. keep the provisional totals indefinitely.

**Chosen solution:** Option 2.
**Reason:** The flip is gated on human approval (D-016 §8/§11); flipping now would pre-empt the review gate and break the M4-heavy regression guard without a compensating scientific necessity. The derivation is deterministic and tested (`tests/test_d016_rainfall.py`), so the flip is a one-line change upon sign-off.
**Trade-offs:** The live demo still uses provisional magnitudes until a hydrologist signs off; the prepared derivation documents the exact replacement values and the re-run procedure.
**Validation:** 13 D-016 tests (determinism, totals, units, anchors reproduction, ordering, contract regression); `docs/D016_RAINFALL_DERIVATION.md`.

---

## D-022 — M6 dashboard/API: smallest maintainable inspection layer (FastAPI + single-file UI)

**Status:** Proposed 2026-08-21 — AI decision (architecture choice within the approved "strengthen GIS dashboard" direction)
**Decision:** Implement M6 as a FastAPI backend + a single-file, dependency-free HTML/JS dashboard consuming the precomputed M5 results — not the full React + TypeScript + MapLibre stack proposed in Phase 0 (ARCHITECTURE §13). Depth/extent maps are server-rendered PNGs from the precomputed GeoTIFFs with a timeline slider and legend.
**Date:** 2026-08-21
**Problem:** M6 must satisfy the acceptance gates (scenario list, metrics, depth/extent maps, S3/S4 comparison, mass balance, provenance, safe API) without introducing a heavy frontend toolchain or re-running the solver per request.
**Options:**

1. full React + MapLibre + tile/COG frontend (Phase 0 proposal);
2. FastAPI + single-file dashboard with server-rendered map PNGs (chosen);
3. API-only with no UI.

**Chosen solution:** Option 2.
**Reason:** Smallest maintainable architecture that satisfies M6 acceptance gates; no build step, no CDN, no simulation re-run (precomputed results only); the Phase 0 frontend stack remains the target for the later operational dashboard if the team funds it.
**Trade-offs:** No vector tiles / interactive basemap; adequate for the 134×134 synthetic fixture, not a tile server.
**Validation:** 17 M6 tests (listing, retrieval, invalid ids, schema, provenance, comparison, mass balance, artifacts, determinism, traversal safety); `docs/M6_DASHBOARD.md`.

---

## D-023 — M7 road impact + flood-aware routing: synthetic network + B13-DEMO-V1 + interactive canvas dashboard

**Status:** Proposed 2026-08-22 — AI decision (within the approved "routing as a major feature" and "strengthen GIS dashboard" directions)
**Decision:** Implement M7 on the precomputed M5 flood snapshots (no simulation re-run) with: (1) a deterministic SYNTHETIC road network (no real road geometry exists in-repo — verified), clearly labelled NOT REAL ROAD GEOMETRY; (2) a centralized, versioned, fingerprinted B13 passability policy `B13-DEMO-V1` (PROVISIONAL DEMONSTRATION, `approved=false`); (3) road impact derived by cell-rasterized depth sampling against the policy; (4) a deterministic Dijkstra router (baseline / avoid-impassable / flood-aware); and (5) an interactive single-file canvas dashboard (no build/CDN) replacing the M6 static PNGs.
**Date:** 2026-08-22
**Problem:** M6 maps are static PNG artifacts; there is no time-evolving flood visualization, no road impact, no routing, and B13 remains unresolved.
**Options:**
1. full React + TypeScript + MapLibre + tile/COG frontend (Phase 0 proposal);
2. extend the existing FastAPI + single-file dashboard with a canvas map + timeline + routing (chosen);
3. API-only road-impact/routing with no UI upgrade.
**Chosen solution:** Option 2.
**Reason:** Preserves architectural consistency (no build step, no CDN), delivers genuine interactivity (pan/zoom, layer toggles, hover/click, timeline playback, routing), keeps all science in Python, and keeps B13 honest as a provisional demonstration policy.
**Trade-offs:** No vector-tile basemap (adequate for the 134×134 fixture); single-file JS is larger; the synthetic grid is 2-connected so a genuine no-route state is covered by unit test rather than demo data.
**Validation:** 24 M7 tests (road impact / routing / API) + full M1–M6 regression; measured frame latency ~9–10 ms (target: <1 s); `docs/M7_ROAD_IMPACT_ROUTING.md`.

---

## D-024 — M8 rainfall nowcast: provider-independent ingestion + persistence baseline

**Status:** Proposed 2026-08-22 — AI decision (within the approved "nowcast layer" and "baseline-first rainfall" directions)
**Decision:** Implement M8 with: (1) a provider-independent `RainfallProvider` interface supporting REAL/SYNTHETIC/FIXTURE source types; (2) concrete synthetic and fixture providers (no real data available — D-017 in force); (3) data-quality validation with freshness/units/completeness checks; (4) a persistence-baseline nowcast (NOWCAST-PERSISTENCE-V1) with conservative 0–60 min horizon at 15-min intervals; (5) typed `NowcastRecord` contract with full provenance; (6) API endpoints for rainfall/nowcast/providers/verification; (7) dashboard panel showing source, freshness, method, uncertainty, and verification status; (8) verification marked NOT_EVALUATED (no paired data exists).
**Date:** 2026-08-22
**Problem:** UFNS has no rainfall ingestion or nowcast capability; the M1–M7 rainfall is entirely scenario-based (precomputed demo profiles).
**Options:**
1. skip nowcast until real data exists;
2. implement provider-independent architecture + persistence baseline (chosen);
3. implement advanced ML nowcast without training data.
**Chosen solution:** Option 2.
**Reason:** Establishes the correct architecture for future real-data integration while providing a scientifically honest, testable, transparent baseline now. No fabricated data, no fake real-time claims, no fake forecast confidence.
**Trade-offs:** Persistence has limited skill for convective systems; no real data means no verification; no uncertainty quantification.
**Validation:** 79 M8 tests (provider contract, source identification, timestamps, units, freshness, missing data, determinism, nowcast contract, fingerprints, API, provenance, caching, forecast/observation separation, dashboard status, synthetic labelling, provider failure, M1–M7 regression, verification behaviour); `docs/M8_NOWCAST.md`, `docs/M8_SCIENTIFIC_REVIEW.md`, `docs/M8_INDEPENDENT_REVIEW.md`.
