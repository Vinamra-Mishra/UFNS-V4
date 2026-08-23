# SIH26085 Delivery Roadmap

**Status:** Phase 0 complete in documentation; implementation blocked on architecture/scientific approval
**Last updated:** 2026-08-21

## 1. Product increments

The build is organized around vertical, testable evidence rather than dashboard-first development.

### Phase 0 — Architecture and source investigation (current)

**Outputs**

- [x] Inspect repository and current compute environment.
- [x] Identify that no local data/code exists.
- [x] Catalogue candidate data sources/APIs and access constraints.
- [x] Propose scientific architecture, contracts, CRS/time/grid policy, storage, APIs, and deployment.
- [x] Propose model equations, assumptions, validation, and mass-balance gates.
- [x] Define scientifically credible MVP, risks, and unknowns.
- [x] Create `ARCHITECTURE.md`, `DATA_SOURCES.md`, `MODEL_ASSUMPTIONS.md`, `ROADMAP.md`, `AGENT_STATE.md`, and `DECISIONS.md`.
- [ ] Human team approves or changes the Phase 0 gates.

**Exit criterion:** pilot strategy, solver approach, default resolution, data-labelling rules, and assumed-data policy are approved.

---

### Phase 1 — Reproducible foundation and dependency spikes

**System architect / DevOps**

- Create monorepo package structure and contribution/testing conventions.
- Pin Python and Node dependencies after checking existing capabilities.
- Add `.gitignore`, `.env.example`, licence/attribution files, structured logging, model/version manifest.
- Add `Makefile` or task runner targets for install, lint, test, pilot build, simulation, API, web, and full demo.
- Add Docker Compose for API, web, and PostGIS only after local non-Docker test path works.

**Hydrology/hydraulics spikes**

- Install/run Landlab `OverlandFlow` on Python 3.11/Linux and reproduce an upstream example.
- Evaluate current EPA SWMM Python interfaces for stepping, lateral inflow, head/flooding output, controls, continuity, Linux wheels, and licence.
- Prove conservative transfer between one surface cell and one SWMM storage node.
- Measure memory/runtime on current 2-vCPU/3.8-GiB sandbox.

**GIS/data spikes**

- Query/subset Copernicus DEM through STAC.
- Inspect actual West Bengal AMRUT and Bengaluru drain files: attributes, bounds, geometry, licence, coverage.
- Select one pilot only after a written audit.
- Freeze a small OSM road extract and inspect topology/speed/access coverage.

**Tests/evidence**

- dependency smoke tests;
- exact rainfall/unit tests;
- one-cell exchange conservation;
- data audit report and checksums;
- initial benchmark JSON.

**Stop condition:** if the SWMM stepping/coupling interface or pilot data cannot meet the documented contract, pause and update `DECISIONS.md` for human review; do not silently implement custom hydraulics.

---

### Phase 2 — Versioned demo and pilot data bundle

**Data/GIS**

- Implement source-adapter interface and immutable raw manifests.
- Validate CRS, axis order, bounds, nodata, timestamp, units, vertical metadata, licences, and checksums.
- Build canonical projected grid and clip/reproject DEM and land cover.
- Produce DEM conditioning report; preserve meaningful depressions.
- Build/version road graph and drainage topology.
- Classify every drainage parameter as measured/published/derived/assumed.
- Create a small deterministic synthetic catchment/network fixture with documented design and seed.

**Outputs**

- bundle manifest;
- COG/NetCDF/GeoPackage/GraphML assets as appropriate;
- data-quality JSON/Markdown report;
- no large raw data committed to Git.

**Tests**

- corrupt/missing raster, missing CRS, implausible bounds, nodata, duplicate IDs, invalid geometry, disconnected graph, time/unit mismatch;
- exact rebuild checksum or explained deterministic variation;
- sampled visual review in QGIS/scripted thumbnail.

---

### Phase 3 — Rainfall loss and 2-D surface model

**Hydrology**

- Implement rainfall field contract and persistence forecast.
- Implement depression/micro-storage and reviewed Horton loss model.
- Wrap established local-inertial solver behind a stable `SurfaceModel` interface.
- Implement adaptive stepping, boundaries, dry/wet handling, snapshots, and component mass ledger.
- Emit depth and valid velocity only where numerically supported.

**QA evidence**

- zero-rain dry case;
- exact closed-bowl rain volume;
- rain/loss/micro-storage closure;
- planar runoff/accepted benchmark;
- wetting/drying/depression test;
- negative/NaN/extreme-rain failure handling;
- cell-size/timestep/roughness/boundary sensitivity;
- measured runtime and peak memory.

**Exit criterion:** no drainage yet, but rain genuinely becomes loss + routed surface water with traceable conservation.

---

### Phase 4 — SWMM drainage and two-way coupling

**Hydraulics**

- Generate/read a reviewed SWMM model from drainage contracts.
- Dynamic-wave routing with nodes, conduits, storage/outfall, and continuity parsing.
- Implement inlet capture and surface surcharge/backflow exchange with selected cited formula.
- Implement 0%, 25%, 50%, and 100% blockage as actual hydraulic controls/opening changes.
- Combine surface, drainage, loss, boundary, outfall, and storage ledgers.

**QA evidence**

- EPA example regression;
- simple conduit capacity cross-check;
- normal, surcharge, backflow, and blocked-link controlled cases;
- one-cell equilibrium and capture/surcharge conservation;
- coupling timestep-halving test;
- UK Environment Agency urban rainfall/surcharge benchmarks where reusable;
- whole-system mass gate.

**Exit criterion:** drainage can remove surface water, exceed capacity, surcharge back to the surface, and change flood depth under blockage with no hidden water source/sink.

---

### Phase 5 — Simulation orchestration and deterministic scenarios

**Simulation/backend**

- Implement immutable scenario definitions and seeded spatial rainfall generators.
- Create normal, heavy, extreme, and extreme-plus-blockage scenarios after parameter review.
- Run in a bounded worker process with cancellation, progress, timeout, and one-concurrent-run default.
- Produce artifact manifests, snapshots, model/source versions, and diagnostics.
- Cache identical deterministic run fingerprints.

**Scenario acceptance**

- scenario 1: minimal flooding under its reviewed definition;
- scenario 2: localized flood response;
- scenario 3: broader/deeper response;
- scenario 4: hydraulic blockage changes surcharge and flood outputs relative to scenario 3;
- outcomes must emerge from the model, not hardcoded desired maps;
- all inputs/results carry simulation/prediction labels.

---

### Phase 6 — API, persistence, and live update contract

**Backend/data**

- Create migrations for catalog/core/rainfall/drainage/roads/simulation/impact schemas.
- Implement versioned FastAPI endpoints and generated OpenAPI.
- Serve raster tiles/assets efficiently; avoid cell-by-cell giant GeoJSON.
- WebSocket simulation event stream with reconnect and terminal failure events.
- Add request bounds, finite-number validation, CORS, rate/concurrency limits, and structured errors.

**Tests**

- API schema/contract tests;
- async run lifecycle and failure propagation;
- missing external source does not become zero/live;
- database unavailable/artifact missing/restart recovery;
- path traversal/upload rejection if file ingestion exists;
- basic API latency benchmark.

---

### Phase 7 — Road risk, multi-objective routing, and alerts

**Routing**

- Densify/buffer road segments and sample max/p95 depth, wet length, nodata.
- Implement reviewed configurable vehicle profiles and actual edge closure/penalties.
- Return fastest, lower-exposure, and emergency-profile route options with reasons.
- Handle disconnected graph and no-route conditions.

**Alerts**

- Rule versioning and traceable flood/drain/road/model-quality alerts.
- Do not represent model rules as official government warnings.

**Tests**

- exact small-graph route cases;
- flooded edge penalty and closure;
- dynamic forecast timestep changes route;
- unknown raster is not assumed dry;
- integration: rainfall → coupled flood → road risk → alternate route.

---

### Phase 8 — Operational GIS dashboard

**Frontend/GIS**

- React + TypeScript + MapLibre.
- Map layers: rainfall, depth, extent, drainage state, road risk, assets, route.
- Timeline and scenario comparison, especially extreme vs extreme-plus-blockage.
- Provenance badges, issue/valid time, native resolution, source age, model version, assumptions, mass warning.
- Scenario controls live only in demo mode; live-source failure/staleness visible.
- Route trade-off view with ETA, max depth, wet length, closures avoided, recommendation rationale.
- Responsive accessible palette/legend and no unsupported 3-D spectacle.

**Tests**

- component tests for provenance/time/severity/units;
- timeline fetch/race/cancel behavior;
- WebSocket reconnect/failure;
- browser end-to-end of the four-scenario judge flow;
- no map-layer mismatch across forecast times.

---

### Phase 9 — Evaluation, red team, and performance

**QA/red team matrix**

- no rain, extreme rain, alternating rain/nodata;
- corrupt DEM, missing CRS, wrong axis/UTM zone, vertical mismatch;
- zero/negative/NaN/inf parameters and depth;
- steep/flat terrain, disconnected depressions, open/closed boundary;
- absent drainage, disconnected link, invalid invert, blocked outlet, all links blocked;
- drainage backflow and oscillating surface/drain head;
- disconnected/no-route road graph;
- stale/missing provider, database/artifact failure, worker timeout;
- issue/valid/local time rollover and forecast gap;
- repeated identical run determinism;
- large requested domain/duration rejected before resource exhaustion.

**Evaluation**

- rainfall metrics only from held-out source sequences;
- flood extent/depth metrics only from independent aligned references;
- routing travel/exposure trade-offs on deterministic graph cases;
- conservation and convergence reports always;
- if reference unavailable, state exactly: `Evaluation unavailable due to lack of a suitable independent reference dataset.`

**Benchmarking**

- ingestion, alignment, forecast, losses, surface solver, SWMM, coupling, artifact writes, road sampling, route, API, frontend rendering;
- wall time, CPU time, peak RSS, grid/active-cell count, timesteps, hardware and versions;
- optimize after profiling, not by removing physics/tests.

---

### Phase 10 — Reproducibility, deployment, and SIH material

- Clean install in an isolated environment.
- One documented command to fetch/build small demo data, run tests, launch services, and reproduce the judge scenario.
- Offline/prebuilt scenario artifacts as a fallback, visibly identified as previous model predictions—not live.
- Deployment guide for student laptop and low-cost VM.
- Model card, data card, API docs, architecture diagram, benchmark report, limitations, security and attribution.
- Five-minute demonstration script and failure fallback.
- Presentation emphasizes causal coupling, mass balance, blockage comparison, route cost changes, and limitations—not invented accuracy.

## 2. Parallel work plan after approval

Work can proceed in parallel only through reviewed contracts.

| Stream | Can start after | Produces | Consumers |
|---|---|---|---|
| Foundation/API schemas | Phase 0 approval | Typed common contracts, task runner | all streams |
| Pilot data audit | Phase 0 approval | bundle/grid/network report | hydrology, routing, frontend |
| Surface solver spike | Phase 0 approval | adapter and numerical evidence | coupling, simulation |
| SWMM/coupling spike | contracts + synthetic fixture | drainage adapter/evidence | simulation |
| Road graph/routing core | grid/road contract | routing tests and graph | backend/frontend |
| Frontend shell | OpenAPI/mock contracts | operational layout | integration |
| External rainfall adapters | source access + rainfall contract | source-labelled fields | forecast/simulation |
| Scientific QA | equations/contracts | benchmark fixtures and gates | all model streams |

The system architect owns cross-stream interface changes. API/schema changes require a decision-log entry and coordinated consumer updates.

## 3. MVP versus stretch scope

### MVP—must work

- deterministic demo rainfall and persistence forecast;
- accepted static DEM/land cover/roads plus explicitly status-labelled drainage data;
- rainfall losses;
- established 2-D local-inertial surface routing;
- EPA SWMM dynamic-wave drainage;
- conservative two-way inlet/surcharge exchange;
- water depth and extent through time;
- hydraulic blockage scenarios;
- road risk and genuinely modified routing costs/closures;
- API, GIS timeline, provenance, alerts, diagnostics;
- unit/integration/E2E/scientific tests and reproducible demo.

### Stretch—only after MVP gates

- IMD/MOSDAC live adapter if access is approved;
- radar advection/optical-flow nowcast;
- calibrated statistical or ML rainfall model;
- probabilistic/weighted ensemble;
- tidal boundary, pumps/gates, field sensors and assimilation;
- high-resolution DTM/building/kerb/culvert representation;
- multi-user queue/cache/managed object storage;
- multilingual alerts and official workflow integration.

Not planned: Kubernetes, blockchain, LLM decision-making, mandatory GPU, fake digital twin, or decorative 3-D.

## 4. Major risks and mitigations

| Risk | Impact | Mitigation / decision trigger |
|---|---|---|
| No hydraulically complete drainage data | Cannot claim actual local overload | Keep synthetic verified network; label assumptions; seek municipal SWMM/CAD; report assumed-field percentage |
| 30 m DSM too coarse for streets | Shallow depths/road assignment uncertain | Limit domain/claim; expose native resolution; sensitivity; seek LiDAR/DTM; do not call curb-scale |
| No open low-latency quantitative radar feed | Live high-resolution nowcast blocked | Reproducible demo + persistence; optional IMD/MOSDAC access; external NWP labelled forecast |
| Local-inertial/SWMM coupling unstable | Unreliable surcharge exchange | Phase 1 one-cell spike, conservative ledger, substep convergence, stop for review if it fails |
| Surface solver runtime on 2 vCPU | Judge demo too slow | 30 m/4 km domain, vectorized established library, one worker, profile, precomputed fallback clearly labelled |
| Drain/DEM vertical mismatch | Impossible heads/backflow | Reject real hydraulic claim; require common datum or run as assumed synthetic elevations |
| Unknown road passability standards | Unsafe recommendation wording | Human-reviewed vehicle profiles; “lower modelled exposure,” never guaranteed safe |
| No independent urban flood depth data | No accuracy metrics | Numerical verification + honest unavailable statement; pursue Sentinel/field events without fabricating depth |
| Public APIs fail/rate-limit | Demo interruption | Freeze permitted bundle; cache with source time; no silent live→simulation switch |
| Dataset licence uncertain | Cannot redistribute demo | Primary-source licence audit before commit; manifest; external fetch or substitute |
| Scope expansion | Core coupling unfinished | Enforce MVP priority; ML/live/advanced UI are stretch |

## 5. Judge demonstration target (<5 minutes)

1. **0:00–0:30 — Evidence and labels:** show pilot source status, native DEM/rain resolution, normal scenario, and model limitations.
2. **0:30–1:15 — Rainfall forecast:** move timeline across current/+15/+30/+60; explain persistence/simulated forcing labels.
3. **1:15–2:15 — Physical response:** show effective rain, terrain routing, depth accumulation, and mass ledger.
4. **2:15–3:00 — Drainage:** inspect inlet capture, network flow/head, surcharge node and outlet volume.
5. **3:00–3:45 — Blockage comparison:** side-by-side identical extreme rain with 0% vs reviewed blockage; show changed hydraulic state and depth, not only colors.
6. **3:45–4:30 — Routing:** fastest route has higher exposure; lower-exposure route incurs a documented ETA trade-off and avoids closed/penalized edges.
7. **4:30–5:00 — Validation/architecture:** show tests, conservation/convergence, benchmark hardware, data gaps, and exactly which metrics are unavailable.

## 6. Definition of done / current quality gate

The phrase “project complete” is prohibited until every item is verified from a clean environment.

- [ ] Clean installation works.
- [ ] Demo data loads/rebuilds with manifest and attribution.
- [ ] Simulation executes.
- [ ] Flood map is generated.
- [ ] Water depth is calculated and finite/non-negative.
- [ ] Rainfall losses and terrain causally affect results.
- [ ] Drainage network participates in the simulation.
- [ ] Surface capture and surcharge/backflow conserve volume.
- [ ] Blockage scenario changes hydraulic/flood results.
- [ ] Whole-system mass ledger passes reviewed gates.
- [ ] GIS dashboard displays synchronized results/provenance.
- [ ] Flood-aware routing actually changes edge costs/closures and works.
- [ ] API and live run events work.
- [ ] Unit, scientific, integration and E2E tests pass.
- [ ] No secrets are committed.
- [ ] No fake metrics or unsupported accuracy claims.
- [ ] No simulated/derived data is presented as observed/real.
- [ ] Documentation, model/data cards, benchmarks and limitations are complete.
- [ ] Demo reproduces from a clean environment.

**Current state:** architecture documentation only; all implementation quality gates remain open.
