# Agent Coordination State

**Updated:** 2026-08-23
**Branch:** `arena/01a02c6a-ufns`
**Phase:** 1 — Implementation (approved)
**Status:** M1 DONE — M2 DONE — M3 DONE — M4 DONE (PASS) — M5 CONDITIONAL PASS (D-016 PREPARED, human review required) — M6 DONE (PASS) — M7 DONE (PASS, B13 PROVISIONAL DEMONSTRATION) — M8 DONE (PASS, NOT_REAL_TIME) — M9 DONE (PASS) — M9.1 HARDENED (M9.1.1 code-quality closure PASS) — M10 REAL-PILOT VALIDATION PASS (spatial re-baseline + CRS provenance resolution 2026-08-23: all 13 RD gates PASS; DEM VALIDATED+NORMALIZED; drainage VALIDATED via authoritative external CRS provenance; entity mapping executed; B02 CRS provenance RESOLVED via MoHUA/TCPO/NRSC) — M11 REAL-PILOT MODEL INTEGRATION PASS (real terrain + real drainage geometry integrated through explicit adapters; 12/12 M11 gates PASS with execution evidence; HYDRAULIC_NETWORK_READY=False; real/synthetic separation intact)
**Implementation:** APPROVED (see `docs/IMPLEMENTATION_SPEC.md`); blocked only by milestone stop-conditions
**State found at start:** file did not exist; repository contained only an 80-byte `README.md` (verified independently against git history)

## Implementation authority

Phase 0 was closed by the human team on 2026-08-21. `docs/IMPLEMENTATION_SPEC.md` is the implementation baseline; `docs/AI_REVIEW.md` is the canonical human-facing status file and must be updated after every milestone. Approved decisions may not be replaced without explicit human approval. Stop conditions (IMPLEMENTATION_SPEC §25) are mandatory.

Implementation agents under the master specification:

- **Antigravity 1** — Scientific/Data: GIS, DEM, rainfall, hydrology, Landlab, SWMM coupling, experiments.
- **Antigravity 2** — Product/GIS: dashboard, visualization, routing UX, alerts.
- **Codex** — Backend/Integration/QA: APIs, orchestration, testing, CI, integration gatekeeper.

In this single-agent sandbox, one agent executes all three roles in milestone order (M1 → M2 → M3 → …), recording role attribution in `AI_REVIEW.md` §19.

Do not begin implementation streams until the approval gates in `ARCHITECTURE.md` are resolved. Before any task, read this file, `DECISIONS.md`, and the independent audit in `PHASE0_AUDIT.md`; after the task, update the relevant entry with exact files/tests/problems.

---

## Agent A — System Architect

**Agent:** A — System Architect
**Task:** Inspect repository/compute, define system boundaries, contracts, CRS/time/grid policy, persistence, API, deployment, MVP, and approval gates.
**Status:** Phase 0 proposal complete; awaiting human approval.
**Files changed:**

- `docs/ARCHITECTURE.md`
- `docs/DECISIONS.md`
- `docs/ROADMAP.md`
- `docs/AGENT_STATE.md`

**Tests:** Repository inventory (`git ls-files`, `find`, `git status`); environment inventory (`lscpu`, `free`, `df`, runtime/tool checks). No application tests exist yet.
**Known problems:** Greenfield repository; Docker/GDAL/PostgreSQL and Python scientific packages are not preinstalled; no accepted pilot data; major choices remain proposals.
**Assumptions:** Modular monolith plus worker is sufficient for the student-scale budget; raster artifacts remain outside the relational database.
**Next action:** Record human decisions; create typed contracts/repository foundation only after approval.
**Dependencies:** Pilot/solver/resolution/provenance policy approval; Agent B/C data and dependency spikes.

---

## Agent B — Data / GIS Engineer

**Agent:** B — Data/GIS Engineer
**Task:** Inventory DEM, rainfall, land cover, roads, drainage, historical flood sources and define data acceptance/alignment policy.
**Status:** Candidate source investigation complete; no source accepted or downloaded into the repository.
**Files changed:**

- `docs/DATA_SOURCES.md`
- GIS/data portions of `docs/ARCHITECTURE.md`

**Tests:** Confirmed repository has no candidate data files; inspected source metadata/pages for IMD, MOSDAC, Bhuvan, Planetary Computer Copernicus DEM, ESA WorldCover, OSM, India Geodata, and OpenCity candidates. Queried India Geodata release/metadata through GitHub. Attempted temporary release-asset download for West Bengal drain/vent GeoJSONL; GitHub release asset transfer returned EOF, so schema/content remain unaudited. No file was added to the repository.
**Known problems:** Drain hydraulic attributes and vertical reference are unknown; high-resolution terrain is unavailable; rain feeds are too coarse/delayed or access-controlled; pilot city is undecided; secondary aggregator licence/provenance needs primary verification.
**Assumptions:** First audit West Bengal AMRUT line/vent data, then Bengaluru linework; use a 30 m grid if only global DSM is accepted.
**Next action:** After approval, retry/download candidate files outside Git, inspect schema/bounds/quality/licence, and publish a pilot data-audit report before selecting a domain.
**Dependencies:** Human pilot criteria; network access; primary source terms; projected CRS selected from approved domain.

---

## Agent C — Hydrology / Hydraulics Engineer

**Agent:** C — Hydrology/Hydraulics Engineer
**Task:** Propose rainfall-loss, 2-D surface, 1-D drainage, two-way coupling, blockage, boundary, mass-balance, and validation methods.
**Status:** Scientific proposal complete; no solver code written; hydrologist/human review required.
**Files changed:**

- `docs/MODEL_ASSUMPTIONS.md`
- scientific sections of `docs/ARCHITECTURE.md`
- D-002 through D-005, D-008, D-014 and D-015 in `docs/DECISIONS.md`

**Tests:** Literature/tool documentation investigation for Landlab local-inertial `OverlandFlow`, EPA SWMM dynamic wave, and UK Environment Agency 2-D hydraulic benchmarks. No numerical tests yet.
**Known problems:** Landlab/SWMM Python dependencies absent; actual inlet formulation and operator-split order require a spike; no local calibrated parameters; no independent event observations; local-inertial applicability and SWMM coupling stability unverified on this hardware.
**Assumptions:** Horton losses are an MVP candidate; Landlab local-inertial routing and SWMM dynamic wave are preferred established engines; inlet exchange must be signed/head-driven and conservative.
**Next action:** On approval, run isolated Landlab and SWMM spikes, then one-cell/one-storage conservative coupling before city data integration.
**Dependencies:** Human scientific approval; dependency compatibility; synthetic fixture; canonical contracts from Agent A; pilot grid from Agent B.

---

## Agent D — ML / Rainfall Engineer

**Agent:** D — ML/Rainfall Engineer
**Task:** Define nowcast baseline order, evaluation requirements, and source constraints.
**Status:** Baseline policy proposed; implementation deferred behind physics/data work.
**Files changed:**

- rainfall sections in `docs/MODEL_ASSUMPTIONS.md`
- rainfall inventory in `docs/DATA_SOURCES.md`
- D-010 and D-011 in `docs/DECISIONS.md`

**Tests:** Source/documentation investigation only; no rainfall sequence is available for evaluation.
**Known problems:** No confirmed low-latency quantitative Indian radar API; IMERG/MOSDAC products are coarse/delayed for streets; no training dataset; no GPU.
**Assumptions:** Persistence is Baseline 1; advection/statistical work requires suitable frequent grids; ML is accepted only after leakage-safe held-out improvement.
**Next action:** Implement rainfall contract and persistence after foundation; create rolling-origin evaluation only after actual data ingestion.
**Dependencies:** Rainfall data access and contract; approved pilot/time grid.

---

## Agent E — Backend Engineer

**Agent:** E — Backend Engineer
**Task:** Plan FastAPI, run orchestration, persistence, WebSocket, validation, security and observability.
**Status:** Interfaces proposed; no code written by design during Phase 0.
**Files changed:**

- backend/API/persistence/observability sections in `docs/ARCHITECTURE.md`
- backend phases in `docs/ROADMAP.md`

**Tests:** None; FastAPI/PostgreSQL are not installed and no application exists.
**Known problems:** Exact simulation worker API depends on C; full PostGIS profile may exceed constrained environment unless tuned; artifact finalization semantics need implementation.
**Assumptions:** `202 Accepted` run lifecycle, one concurrent worker, versioned `/api/v1`, PostgreSQL/PostGIS plus file/object artifacts.
**Next action:** Generate executable schemas/OpenAPI and health/run skeleton after Phase 1 approval.
**Dependencies:** Agent A contracts; C solver adapters; B artifact manifest; DevOps dependency setup.

---

## Agent F — GIS / Frontend Engineer

**Agent:** F — Frontend/GIS Engineer
**Task:** Plan operational map, synchronized forecast timeline, provenance, layers, scenario comparison, routes, and accessibility.
**Status:** Information architecture proposed; no frontend code written.
**Files changed:**

- frontend sections in `docs/ARCHITECTURE.md`
- dashboard/demo sections in `docs/ROADMAP.md`

**Tests:** None; no package manifest/frontend exists.
**Known problems:** Tile/asset API not implemented; basemap provider/terms must be selected; depth/resolution uncertainty must remain visible; mock data cannot be presented as live.
**Assumptions:** React + TypeScript + MapLibre; side-by-side blockage comparison; quantitative legends and permanent provenance badges.
**Next action:** Build against generated mock contracts only after Agent A/E freeze schemas.
**Dependencies:** OpenAPI/event contract, pilot bounds/CRS, map asset strategy, routing outputs.

---

## Agent G — Routing Engineer

**Agent:** G — Routing Engineer
**Task:** Define road graph, raster exposure sampling, flood penalties/closures, route objectives and explanation.
**Status:** Design proposed; passability policy requires human/domain review.
**Files changed:**

- routing sections in `docs/ARCHITECTURE.md`
- routing assumptions/tests in `docs/MODEL_ASSUMPTIONS.md`
- D-012 and D-013 in `docs/DECISIONS.md`

**Tests:** Documentation investigation of OSM/OSMnx capability; no graph or route code exists.
**Known problems:** Vehicle passability thresholds unresolved; OSM speeds/access may be incomplete; 30 m flood grid introduces road-depth uncertainty; “safe” cannot be guaranteed.
**Assumptions:** Store max/p95 depth and wet length; unknown is not dry; fastest/lower-exposure/emergency are different graph objectives/profiles.
**Next action:** Build exact toy-graph tests first, then a versioned pilot graph and depth sampler.
**Dependencies:** Human route policy; B road graph; C flood snapshots; A/E schemas.

---

## Agent H — QA / Red Team

**Agent:** H — QA/Red Team
**Task:** Define scientific, unit, integration, E2E, failure, convergence, mass, and impossible-output tests.
**Status:** Test strategy and risk matrix proposed; no executable tests exist.
**Files changed:**

- validation sections in `docs/ARCHITECTURE.md`
- component checks in `docs/MODEL_ASSUMPTIONS.md`
- Phase 9 and quality gate in `docs/ROADMAP.md`

**Tests:** Phase 0 repository/data/tool inspections only.
**Known problems:** No code/fixtures/reference events; proposed 1% warning/5% fail mass gates need benchmark evidence; independent flood evaluation unavailable.
**Assumptions:** Numerical verification and conservation are mandatory; no metric is emitted without real reference artifacts.
**Next action:** Create tests alongside every Phase 1 change, beginning with units, CRS, deterministic fixtures, Landlab/SWMM smoke tests, and one-cell coupling.
**Dependencies:** All implementation agents; accepted benchmark licences/data; human scientific thresholds.

---

## DevOps / Reproducibility Engineer

**Agent:** DevOps/Reproducibility
**Task:** Inspect hardware/runtime constraints and plan installation/deployment/benchmark path.
**Status:** Environment audited; implementation deferred.
**Files changed:**

- compute/deployment/performance sections in `docs/ARCHITECTURE.md`
- foundation/deployment phases in `docs/ROADMAP.md`

**Tests:** Verified CPU/RAM/disk/GPU/runtime/tool availability.
**Known problems:** No Docker/GDAL/Postgres preinstalled; no dependency lock; 4 GiB/no-swap pressure; no measured simulation runtime.
**Assumptions:** No GPU requirement; one worker; 30 m bounded domain; local filesystem artifact profile plus optional Compose.
**Next action:** Pin minimal dependencies, verify clean installation, and benchmark before optimizing.
**Dependencies:** Approved stack and solver packages.

---

## SIH Technical Presentation Advisor

**Agent:** SIH Presentation Advisor
**Task:** Shape a sub-five-minute evidence-led demonstration and claim discipline.
**Status:** Demo sequence proposed.
**Files changed:**

- judge demonstration and quality gate in `docs/ROADMAP.md`

**Tests:** None; no running demo exists.
**Known problems:** All screenshots/results would currently be fabricated because implementation has not started; therefore none were created.
**Assumptions:** Judges should see provenance, causal rain/terrain/drain/blockage response, route cost changes, conservation, benchmark evidence, and honest limitations.
**Next action:** Draft slides/script only after measured outputs and tests exist.
**Dependencies:** Integrated tested prototype and benchmark/evaluation reports.

---

## Review Board — Independent Phase 0 Audit

**Agent:** Review Board (independent auditor; no implementation authority)
**Task:** Audit the entire Phase 0 state and decide whether the project is scientifically and technically ready for implementation; produce the approval matrix; block implementation until human approval.
**Status:** AUDIT COMPLETE. Verdict: CONDITIONALLY READY (see `PHASE0_AUDIT.md` §19). All approval-gate statuses remain PENDING in `PHASE0_APPROVAL.md`.
**Files changed:**

- `docs/PHASE0_AUDIT.md` (created)
- `docs/PHASE0_APPROVAL.md` (created)
- `docs/DECISIONS.md` (added proposed decisions D-016 through D-019; existing entries unchanged)
- `docs/AGENT_STATE.md` (this entry; header status/branch correction)
- `README.md` (Phase 0 document list updated)

**Verification performed:** full read of all seven Phase 0 documents; git history inspection including both merge parents (pre-Phase-0 `main` = 80-byte README, confirmed via GitHub API); GitHub issues/PR/CI inventory (no issues, no workflows, one merged PR); independent web verification of FABDEM licence (CC BY-NC-SA 4.0), Copernicus DEM licence/coverage caveat, `india-geodata` urban-water collection contents, Landlab `OverlandFlow` API (de Almeida et al. 2012; uniform scalar rainfall input), PySWMM coupling primitives and documented mass-accounting pitfalls, and UK EA benchmark Tests 8A/8B.
**Known problems (audit findings):** blockers B01–B15 and risks R01–R03 tabulated in `PHASE0_AUDIT.md` §16; highlights: (B02) pilot drainage data unverified, (B03) demo rainfall scenarios have no named derivation, (B05) SWMM coupling unproven, (B06) Landlab scalar-rainfall limitation requires adapter-level handling, (B04) no verified live rainfall feed, (B11) problem statement not archived in-repo.
**Assumptions:** none beyond the documented Phase 0 evidence; no scientific decision was modified.
**Next action:** none permitted — the human team must act on `PHASE0_APPROVAL.md` and the six human decisions listed in `PHASE0_AUDIT.md` §19.
**Dependencies:** human decisions only.

---

## Shared blockers requiring human response

1. ~~Resolve the approval matrix in `PHASE0_APPROVAL.md`~~ — DONE: human approval recorded 2026-08-21 in `IMPLEMENTATION_SPEC.md`; all matrix items resolved.
2. ~~Approve/change Landlab local-inertial + EPA SWMM dynamic-wave architecture~~ — APPROVED (spec §2).
3. ~~Approve data-driven pilot audit order~~ — APPROVED with conditions: WB AMRUT audit (B02) still requires data inspection + human acceptance of the audit report.
4. ~~Approve 30 m / ~4 km × 4 km MVP scope~~ — APPROVED for physics (spec §2/§3.3).
5. ~~Approve synthetic/assumed drainage fixture policy~~ — APPROVED (spec §2).
6. ~~Approve/amend D-016…D-019~~ — APPROVED (see `DECISIONS.md`).
7. Nominate reviewers/choices for loss parameters, flood severity display, and vehicle passability policy — **OPEN** (affects M4/M5/M7 parameter selection; provisional demo values must stay labelled until then).
8. Archive the official SIH26085 problem statement in `docs/` — **OPEN** (B11; still pending human upload).
9. Initiate IMD/MOSDAC access requests and municipal/academic outreach for drainage assets and LiDAR/DTM data — **OPEN** (affects M10 and real-pilot credibility; demo path unaffected).
10. Project LICENSE decision (audit §19.3) — **OPEN** (repo still has no license file; demo fixtures are self-generated).

---

## Implementation progress log (Phase 1)

### M1 — Data + spatial foundation — DONE (2026-08-21)
- Contracts: DataLineage, GridSpec, RainfallGrid, ScenarioDefinition, MassBalance, SimulationRun (`services/contracts.py`).
- CRS policy + axis-order guard, timestamp policy (UTC RFC3339 / IST / half-open intervals), synthetic DEM fixture (134×134 @30 m, EPSG:32645, SYNTHETIC), provisional alternating-block rainfall (Chow 1988, PROVISIONAL per D-016), provenance manifest with checksums, deterministic scenario fingerprints, mass ledger (1%/5% gates).
- Bundle: `data/demo/` (dem.tif, 12× rain GeoTIFFs + rain_index.json, scenarios.json, manifest.json, preview PNGs). Byte-identical rebuilds verified (fixed lineage timestamps, bundle-relative URIs).
- Acceptance: data loads ✓, CRS verified ✓, timestamps verified ✓, DEM structurally inspected (PNGs generated; **human visual review still required**), rainfall representation verified ✓, provenance recorded ✓, scenario reproducible ✓.
- B02 partial: `docs/DATA_AUDIT_WB_AMRUT.md` — collection metadata/provenance audited via GitHub API; parquet download blocked by sandbox CDN egress (same EOF as Phase 0). Human retry command documented.

### M2 — Landlab surface-flow spike — DONE, PASSED (2026-08-21)
- Adapter: `services/hydrology/surface.py` (D-019). Core-only rainfall, per-cell Horton, adaptive dt capped at 0.5 s/m (measured wet-dry-front stability ratio), exact residual-based boundary outflow, film-bias diagnostics, fail-fast on material negatives.
- All mandated tests pass (zero rain, uniform rain, spatial rain, losses, timestep halving, conservation, reproducibility, fail-fast, runtime) — `tests/test_landlab_spike.py`.
- Fixture-scale benchmark: 3-hour heavy event on 134×134 @30 m in **3.2 s** wall time (2 vCPU sandbox).
- landlab 2.11.0 + `requireit==0.8.0` pin required on Python 3.11 (documented in requirements-spikes.txt).

### M3 — SWMM coupling spike — NEXT
- pyswmm 2.1.0 installed and import-verified. Tasks: synthetic fixture INP (assumed parameters labelled), one-cell/one-storage conservative exchange, surcharge return, blockage, timestep sensitivity, conservation, reproducibility. STOP AND REVIEW if the coupling cannot close its ledger.


### M3 — SWMM ↔ surface coupling spike — DONE, PASSED (2026-08-21)
- Fixtures: `services/hydraulics/fixture.py` — exact-exchange synthetic network (ST1→C1→V1→C2→O1, no junctions, all storage exact) in clean/blocked variants + a junction flooding-demo fixture. All parameters SYNTHETIC/ASSUMED; committed INPs in `data/demo/`.
- Coupling: `services/hydraulics/coupling.py` — signed head-driven orifice (Q>0 = surface→drainage), capture into ST1, return out of ST1 (negative generated_inflow, engine-verified), flooding export on the demo fixture, causally ordered explicit scheme (dt_c = 5 s int; pyswmm stride requirement).
- Ledger: ΔS_d via SWMM's own per-stride conservation identity (engine-exact); combined residual 2.9e-13 m3 (6.3e-16 relative). SWMM 5.2.4 storage readback quirk documented (fill-drain probe: 0.000% engine continuity; readback −10–15%) — reported as a diagnostic, never absorbed.
- Tests: all 15 mandated gate tests (M3-01…M3-15) pass — smoke, zero-exchange, capture, return, surcharge, blockage (D2S ×3.23, outfall ÷6.1), control, halving (0.00%/0.07%), conservation, reproducibility (bitwise), failure handling, units, causality, signs, extreme state.
- Decision: **M3 PASS** (see `docs/M3_SWMM_COUPLING.md`). M4 (coupled flood model) may begin.

### M4 — Coupled flood model on the synthetic fixture — DONE, PASSED (2026-08-21)
- Engine: `services/simulation/engine.py` — CoupledFloodModel / RunConfig / RunLedger / FloodSnapshot; rainfall → microstore+Horton → Landlab (1 s sub-steps) ↔ 16-inlet capture + vent return (M3 laws) ↔ SWMM → 5-min snapshots; artifacts (GeoTIFF + summary) with provenance.
- Multi-site generalization of the M3 exchange documented; equivalence with the M3 spike driver proven by test (Δ ≤ 1e-3 m³).
- Blockage story (M4-05, identical forcing): D2S 0→100.8 m³, capture 496→190 m³, outfall 488→73 m³, ST1 head 20.47→21.97 m (surcharge above vent ground), surface +406 m³, flooded area +3,000 m². Both ledgers pass (rel 1.6e-4).
- Ledger fixes this milestone: microstore double-count; per-inlet negative orifice rates (SWMM extraction with no ledger entry) — caught by the equivalence test; dry-run film-bound gate; B08 violation in zero/uniform/spatial fixture mapping — caught via scenario heads (12.9 m), fixed.
- Tests: M4-01…M4-15 + M3-equivalence (16 tests). Full suite 81/81.
- Runtime: ~18 s per 3-hour coupled run on the 2 vCPU sandbox (~600× real-time), RSS ~270 MB.
- Diagnostics: `scripts/run_m4_diagnostics.py` → `data/demo/m4/` (PNGs labelled SYNTHETIC/SIMULATED/PROVISIONAL + per-snapshot GeoTIFFs + summary). HUMAN VISUAL REVIEW REQUIRED (M4 spec §30).
- Decision: **M4 PASS** (see `docs/M4_COUPLED_MODEL.md`). M5 (scenario engine) may begin after D-016 review.

### M5 — Scenario engine — DONE, CONDITIONAL PASS (D-016 PREPARED, human review required) (2026-08-21)
- Responsibility (Antigravity 1 + Codex):
  - **Scenario schema** — `ScenarioRecord`, `RainfallProfileRecord`, `DrainageCondition` typed records in `services/scenarios/` (profiles.py, drainage.py, registry.py); 4 required scenarios (S1 Normal, S2 Heavy, S3 Extreme, S4 Extreme+Blocked) with full provenance, assumptions, limitations, fingerprints.
  - **Rainfall-profile integration** — governed P_NORMAL (20 mm), P_HEAVY (45 mm), P_EXTREME (90 mm) alternating-block profiles; explicit `review_status=PROVISIONAL`, `d016_review_status=PREPARED`; severity definitions documented in code (no implicit labels).
  - **Drainage-condition integration** — D_NORMAL (C1 D=0.30 m, ~97 L/s full-bore) and D_BLOCKED (C1 D=0.12 m, ~8.4 L/s; capacity ratio ~0.087); INP-fingerprint verification; real hydraulic reduction, not a visual multiplier.
  - **Simulation execution** — `services/scenarios/runner.py` converts ScenarioRecord → M4 RunConfig → CoupledFloodModel.run() → ScenarioResult; fresh model per scenario, no state leakage; full output contract per M5 §9 (rainfall/loss/surface/drainage/exchange/boundary summaries, peak depth, flooded area, time to peak, surcharge, mass ledger, snapshot inventory, acceptance).
  - **Comparison outputs** — `services/scenarios/comparison.py` produces deterministic comparison artifact: per-scenario summary + S3/S4 paired blockage differences (δ peak, δ area, δ surface storage, δ surcharge, capture reduction, additional spill, outfall reduction, physical interpretation).
  - **Tests** — `tests/test_m5_scenarios.py` (18 tests): M5-01 schema, M5-02 IDs/metadata, M5-03 profile provenance, M5-04…07 scenario execution, M5-08 pairwise controls, M5-09 blockage sensitivity, M5-10 isolation, M5-11 mass conservation, M5-12 snapshot determinism, M5-13 reproducibility, M5-14 invalid config, M5-15 manifests/fingerprints, M5-16 summary consistency + 2 M4 regression guards. Full suite 99/99 (81 M1-M4 + 18 M5).
  - **Visual diagnostics** — `services/scenarios/diagnostics.py` + `scripts/run_m5_diagnostics.py` → `data/demo/m5/` (26 PNGs: per-scenario rainfall/peak/extent/timelines + S3/S4 comparison images + summary table + GeoTIFFs + JSON results/comparison). Every artifact labelled SYNTHETIC/SIMULATED/PROVISIONAL.
  - **Documentation** — `docs/M5_SCENARIO_ENGINE.md` (20 sections per M5 §16); M4 visual review recorded (reviewer/date/artifacts/findings/limitations); D-016 honestly recorded PREPARED (human review required).
- Scenario results (peak depth / flooded area / S2D / D2S / outfall / max surcharge / rel residual / gate):
  - S1 Normal:   0.243 m / 0.23 km² / 314 m³ / 0 m³ / 309 m³ / 0.00 m / 5.3e-6 / PASS
  - S2 Heavy:    0.471 m / 1.79 km² / 496 m³ / 0 m³ / 488 m³ / 0.00 m / 1.6e-4 / PASS (reproduces M4 heavy)
  - S3 Extreme:  0.614 m / 4.58 km² / 859 m³ / 0 m³ / 848 m³ / 0.00 m / 2.1e-4 / PASS
  - S4 Extreme+Blocked: 0.615 m / 4.58 km² / 293 m³ / 137 m³ / 139 m³ / 0.30 m / 2.0e-4 / PASS
- S3/S4 blockage comparison (only C1 diameter differs): capture −66%, outfall −84%, D2S spill 0→137 m³, surface Δ storage +699 m³, ST1 surcharge +0.30 m; interpretation_status = PHYSICALLY CONSISTENT.
- Runtime: ~17–18 s per scenario, full suite ~71 s on 2 vCPU sandbox (~610× real-time).
- M4 regression: all 81 M1-M4 tests continue to pass; S2 reproduces M4 heavy baseline within tolerance (peak 0.471 ± 0.005 m, area 1.79 ± 0.04 km²).
- M4 visual review recorded SATISFACTORY (2026-08-21; see M5 doc §19).
- Decision: **M5 CONDITIONAL PASS — D-016 REVIEW REQUIRED** (see `docs/M5_SCENARIO_ENGINE.md` §20). All technical gates pass; the only outstanding item is hydrologist approval of rainfall-profile derivation (D-016). No hard-stop conditions triggered; no M1-M4 code paths were modified; no scientific semantics altered. M6 (dashboard) may begin when the team chooses; the CONDITIONAL PASS does not block further implementation — it blocks only operational/scientific claim-making about the rainfall suite.

### D-016 — Rainfall derivation — DONE, PREPARED (HUMAN REVIEW REQUIRED) (2026-08-21)
- Resolved Option A (published WB/Kolkata IDF parameters): **Kumar & Remesan (2026)**, "Integrating Revised IDF Curves with Coupled 1D-2D MIKE+ Modelling…", Water Resources Management 40(3):115, DOI 10.1007/s11269-026-04514-5 — observed GEV IDF for the Bagjola Canal basin, Kolkata Metropolitan Area (IMD Alipur gauge, 1980-2023).
- Derivation: `services/rainfall/idf.py` (deterministic, SHA-256 fingerprinted) — depth = intensity×duration; Sherman return-period scaling between the published 2-yr/100-yr anchors; log-log interpolation to the 3-h duration; alternating-block 15-min hyetograph.
- Source-derived totals (recommended, 2/5/10-yr → NORMAL/HEAVY/EXTREME): **72.08 / 88.44 / 103.25 mm** (vs provisional 20/45/90 mm). NOT flipped into the live profiles (gated on hydrologist approval; would break the M4-heavy regression guard and require full re-run).
- Tests: `tests/test_d016_rainfall.py` (13): determinism, totals, interval count, non-negative, units, fingerprint stability, source anchors reproduction, scenario ordering, M5-contract regression, invalid inputs.
- Document: `docs/D016_RAINFALL_DERIVATION.md` (20 sections; SOURCE FACT / DERIVED VALUE / ASSUMPTION / AI INFERENCE / HUMAN DECISION labelled). No human approval fabricated.

### M6 — Dashboard/API — DONE, PASS (2026-08-21)
- Backend: `apps/api/` (store.py loads precomputed m5_results.json/m5_comparison.json + merges live scenario definitions; render.py renders depth/extent PNGs from GeoTIFFs; app.py FastAPI). `scripts/run_dashboard.py` (uvicorn).
- API: `/health`, `/api/v1/version`, `/api/v1/scenarios`, `/api/v1/scenarios/{id}` (+`/result`, `/snapshots`, `/mass-balance`, `/flood-depth`, `/flood-extent`), `/api/v1/comparison/s3s4`. Allow-listed ids, structured errors, no client file paths (no path traversal), no simulation re-run.
- Frontend: `apps/web/index.html` (single-file, no build/CDN) — scenario selector with status badges, metrics (units labelled), mass-balance identity (authoritative ledger, not recomputed), depth/extent maps with timeline slider + legend + threshold, S3/S4 comparison with the "small peak-depth delta ≠ no hydraulic effect" interpretation, scientific-status legend. All maps carry SYNTHETIC/SIMULATED/PROVISIONAL/NOT FOR OPERATIONAL USE banners.
- Tests: `tests/test_m6_dashboard.py` (17): listing, retrieval, invalid ids (404), result schema, provenance, S3/S4 comparison, mass-balance, artifact PNGs, determinism, path-traversal safety.
- Document: `docs/M6_DASHBOARD.md`. Full suite **129/129** (81 M1-M4 + 18 M5 + 13 D-016 + 17 M6); no M1-M5 regression.

### M7 — Road impact + flood-aware routing + interactive flood UI — DONE, PASS (2026-08-22)
- Road network: `services/routing/roads.py` — deterministic SYNTHETIC network (NO real road geometry in-repo, verified); 30 intersections, 57 segments aligned with the DEM street corridors + two diagonal arterials; per-segment + network SHA-256 fingerprints; labelled `SYNTHETIC / DEMO DATA / NOT REAL ROAD GEOMETRY`.
- Policy: `services/routing/policy.py` — centralized, versioned, fingerprinted `B13-DEMO-V1` (PROVISIONAL DEMONSTRATION, `approved=false`); severity bands DRY/LOW_IMPACT/CAUTION/HIGH_IMPACT/IMPASSABLE at 0.05/0.15/0.30/0.50 m; routing speed factors; documented "Not an operational safety recommendation" disclaimer.
- Impact: `services/routing/impact.py` — cell-rasterized (Bresenham) depth sampling → max/mean depth, impacted fraction/length, classification, passability; time-dependent index over all 37 leads; scenario metrics + first/peak impact aggregates. Derives ONLY from simulated depth fields.
- Graph + routing: `services/routing/graph.py` (Dijkstra, deterministic tie-break) and `services/routing/router.py` (baseline / avoid-impassable / flood-aware; RouteResult with baseline+flood-aware+difference; `NO_SAFE_ROUTE` without silent fallback; data-grounded explanation).
- API: `apps/api/impacts.py` + extended `apps/api/app.py` — `/roads`, `/policies`, `/drainage/points`, `/scenarios/{id}/frame`, `/rainfall`, `/road-impact`, `/road-impact/{road_id}`, `/road-metrics`, `/routing/nodes`, POST `/routes`. Cached derivation (no simulation re-run), allow-listed IDs, structured errors, coordinate/lead/mode validation, no path traversal.
- Frontend: `apps/web/index.html` rewritten — interactive canvas map (pan/zoom, layer toggles, depth legend, hover/click), timeline (play/pause/step/speed 0.5–4×), scenario selector, live metrics, road-inspection panel, origin/destination routing with normal-vs-flood-aware comparison + explanation, S3→S4 "what changed", collapsible provenance.
- Performance (measured): `/frame` ~9–10 ms median (warm), `/routes` ~1.8 ms — timeline → map update well under 1 s. Mode A (snapshot playback) implemented; Mode B (live run jobs) documented as future work.
- Tests: `tests/test_m7_road_impact.py` (M7-01…M7-08), `tests/test_m7_routing.py` (M7-09…M7-15), `tests/test_m7_api.py` (M7-16…M7-22) — 24 tests. Full suite **153/153** (129 M1–M6 + 24 M7). One M6 assertion updated (health `app` "ufns-m6" → "ufns-m7").
- Document: `docs/M7_ROAD_IMPACT_ROUTING.md` (23 sections); D-023 added to `DECISIONS.md`.
- Decision: **M7 PASS** — B13 recorded PROVISIONAL DEMONSTRATION (not approved), D-016/B02 unchanged. M8 (rainfall nowcast) may begin.

### M10 — Real-pilot data foundation — ENGINEERING IMPLEMENTATION COMPLETE / REAL-PILOT VALIDATION BLOCKED (2026-08-22)
- Contracts/provenance: `services/ingestion/real_data.py` — processing-fingerprint contract, `result_labels` (fixture loads can never be labelled REAL_DATA), `AcquisitionAttempt` evidence records; all deeply immutable with result-specific snapshots.
- DEM: `services/ingestion/dem_real.py` — validation gates strengthened (resolution validated from actual transform in metres, dimension/empty/bounds gates) + `normalize_dem` (VALIDATED-source requirement, overlap gate, clip → reproject → bilinear → alignment to the established pilot GridSpec via `pilot_grid_spec()`, nodata preserved/counted, deterministic processing fingerprint).
- Drainage: `services/ingestion/drainage_real.py` — attribute-level audit (observed schema + null rates, GeoParquet geometry/CRS verification, geometry validation, duplicates, extent, accepted/missing/rejected/unresolved classification, explicit reports) + `map_drainage_entities` (explicit type rules, stable IDs, per-entity mapping status/reason, explicit rejections, hydraulic extraction only from unambiguous columns with documented derivations).
- Acquisition: `services/ingestion/acquisition.py` + `scripts/attempt_real_data_acquisition.py` — single-shot attempts, evidence in `data/raw/acquisition_attempts.json`; both real sources BLOCKED (CDN TLS EOF / host unreachable); no substitute source invented.
- Fixtures: `tests/fixtures/m10/generators.py` — SYNTHETIC TEST FIXTURE generators (classification FIXTURE).
- Tests: `tests/test_m10_real_data.py` 110 tests (was 37). Full suite **492/492** (154 M1-M7 + 188 M8 + 40 M9 + 110 M10). M1-M9 regression unchanged.
- Documents: `docs/M10_REAL_PILOT_FOUNDATION.md`, `docs/M91_M10_FINAL_REPORT.md` §20, `docs/DATA_AUDIT_WB_AMRUT.md`.
- Decision: M10 engineering gates PASS; all real-data gates remain NOT_FETCHED/BLOCKED (B02 OPEN; D-016, B13 unchanged). M11 NOT STARTED / BLOCKED BY M10 DATA GATES.

### M10 — Real-pilot validation pass — REAL-PILOT VALIDATION BLOCKED (evidence-backed) (2026-08-22, later session)
- Artifacts: the three real artifacts were supplied by a human and moved **byte-identical** (SHA-256 verified) from the repo root into the canonical raw location `data/raw/` (out of Git per repo convention). Acquisition evidence recorded via the existing machinery: `verify_local_artifact` (`services/ingestion/acquisition.py`) + `scripts/record_real_artifact_evidence.py` → three `FETCHED` records (path/bytes/SHA-256) appended to `data/raw/acquisition_attempts.json`; the two prior in-sandbox `BLOCKED` records preserved verbatim (B02 access sub-blocker evidenced, then resolved — not deleted).
- Execution (no M10 pipeline code changed; no parallel pipeline): `scripts/run_m10_real_pilot_validation.py` ran `ingest_dem` / `normalize_dem` / `audit_wb_amrut_drains` ×2 / `map_drainage_entities` ×2 on the real artifacts → machine-readable evidence `data/processed/m10_real_pilot_validation.json`.
- DEM (actual raster metadata): **VALIDATED** — EPSG:4326, 900×900 float32, 1-arc-second transform, ground resolution 30.76 m measured from the transform (not from the filename), bounds 88.60–88.85°E / 22.65–22.90°N, all 810,000 cells finite; warning: no nodata sentinel. `normalize_dem` → **BLOCKED**: no spatial overlap with the established pilot GridSpec (grid WGS 85.0539–85.0935°E / 22.5951–22.6318°N). Filename "bagjola_kolkata" not confirmed by actual bounds (tile is east of the Kolkata metro core).
- Drains (90,395 MultiLineString) / vents (9,579 MultiPoint): audits **AUDIT_PARTIAL** — single gap: **no embedded CRS** in the GeoParquet metadata (`crs_valid=False`); geometry otherwise clean (0 invalid/empty; 100 duplicate source ids each; vents MultiPoint unsupported for line-mapping, counted); extent 86.347–88.844°E (drains), 87.231–88.672°E (vents). Schema: accepted `id`; missing `type` + all 5 required hydraulic attributes (**MISSING confirmed absent**); ambiguous columns (Width/Depth/Dr_Slope/…) preserved verbatim, never mapped. `map_drainage_entities` → **BLOCKED** (VALIDATED-source contract); 0 entities; nothing fabricated.
- Spatial coherence: real datasets mutually coherent (DEM tile inside drains/vents coverage, eastern WB / Kolkata-metro region) but **none overlaps the established M1 pilot GridSpec** → recorded as a **DATA/MODEL INTEGRATION ISSUE** (M10 doc §12): the synthetic-origin M1 grid was not moved, no second grid created, data not forced; a human pilot-area decision (re-base the grid or keep it synthetic) is required.
- RD gates (definitions + evidence in M10 doc §11): **8 PASS (RD-01/02/05/06/07/09/10/13) · 1 AUDIT_PARTIAL (RD-08) · 2 FAIL (RD-04/12) · 2 BLOCKED (RD-03/11)**.
- B02: **OPEN, moved forward, not closed** — access sub-blocker resolved with evidence; attribute audit complete; remaining: human acceptance of the audit report (incl. embedded-CRS gap + confirmed-absent hydraulics) + pilot-area decision. WB AMRUT geometry must not be presented as the pilot's real drainage network until acceptance.
- D-016 PREPARED / B13 PROVISIONAL: unchanged (no human approvals exist in the repository).
- Tests: +10 real-artifact execution tests (skip-guarded when `data/raw` artifacts absent; SHA-256 oracles, no-overlap block, AUDIT_PARTIAL gap, BLOCKED mapping, evidence-history preservation, real-never-SYNTHETIC). M10 suite **120/120**; full suite **502/502** (154 M1-M7 + 188 M8 + 40 M9 + 120 M10). Ruff clean on changed Python files. No test weakened/deleted; no M1–M9 semantics touched.
- Decision: **M10 = ENGINEERING IMPLEMENTATION COMPLETE; REAL-PILOT VALIDATION BLOCKED** (pilot-area decision + embedded-CRS acceptance + human audit acceptance required). **M11 = NOT STARTED / BLOCKED BY M10 DATA GATES** (not started).

### M11 — Real-pilot model integration — PASS (2026-08-23)
- Principle: real data enters the model through explicit, auditable contracts; where insufficient for a scientific operation, the operation is STOPPED at the contract boundary (never filled with an ungoverned assumption).
- Engine change: **minimal, additive, byte-identical by default** — one field `RunConfig.grid_origin_xy: tuple[float,float] | None = None` + `RunConfig.model_affine()` helper used by `_grid_spec()` and the artifact writer. When `None` (M1–M9 default) `model_affine()==grid_affine()` exactly; `fingerprint()` payload untouched → all M1–M9 fingerprints/grids byte-identical. No M2/M4 mathematics rewritten.
- Adapter layer `services/pilot/`: `modes.py` (modes A/B/C, capability state, governed labels), `contract.py` (hydraulic readiness contract: required/present/MISSING/derived/ASSUMED/unresolved), `provenance.py` (deeply immutable RealPilotProvenance + GridSpec fingerprint), `terrain.py` (RealTerrainAdapter wraps M10 normalize_dem; answers the 8 provenance questions), `drainage.py` (RealDrainageAdapter: M10 mapping + deterministic EPSG:4326→32645 reprojection via pyproj), `adapter.py` (M11SimulationAdapter: MODE A no-sim, MODE B executable ROI run).
- Capability model: REAL_GEOMETRY_AVAILABLE=True; HYDRAULIC_PARAMETERS_MISSING=True; **HYDRAULIC_NETWORK_READY=False**. The five required hydraulic attributes (diameter_m, invert_upstream_m, invert_downstream_m, manning_n, capacity_m3s) remain MISSING — none fabricated. MODE B uses an explicitly-labelled SYNTHETIC/ASSUMED fixture (reuses M3 exact_fixture_inp with a datum anchor to the real ROI basin — documented alignment, not a fabricated parameter).
- MODE B execution: real terrain enters the solver from the real DEM via a deterministic zero-nodata ROI sub-rectangle of the authoritative pilot grid (no nodata filling; pilot grid NOT moved; synthetic grid NOT restored). Real exchange occurred (S2D=72.13 m³); mass relative residual **7.8e-08** (≤1% gate PASS); depths finite/non-negative; deterministic (repeated run → identical fingerprint + bit-identical depths).
- Real/synthetic separation: MODE-B result labelled `REAL_TERRAIN_SYNTHETIC_HYDRAULICS` (names both components); real terrain never SYNTHETIC; synthetic hydraulics never REAL_DATA.
- API/dashboard: `apps/api/pilot.py` + 4 endpoints (`/api/v1/pilot/real{,/dem,/drainage,/hydraulic-readiness}`) over precomputed `data/demo/m11/pilot_inspection.json` (inspection only; never re-runs sim). Truthful labels (REAL_PILOT/REAL_TERRAIN/SYNTHETIC_HYDRAULICS/PROVISIONAL/MISSING/UNRESOLVED/NOT_REAL_TIME/NOT_VALIDATED_FORECAST); health exposes `real_pilot_inspection_available`.
- Artifacts: `data/demo/m11/{gate_matrix,mode_b_result,pilot_inspection}.json` + `mode_b_drainage_synthetic.inp` (regenerated by `scripts/run_m11_real_pilot_validation.py`).
- Tests: `tests/test_m11_real_pilot.py` (48: unit + M11-01…M11-12 real-artifact experiments, skip-guarded) + `tests/test_m11_api.py` (7). Full suite run; M1–M9 regression unchanged. Ruff clean on changed Python files.
- Documents: `docs/M11_REAL_PILOT_INTEGRATION.md`, this file, `docs/AI_REVIEW.md`, `README.md`.
- Decision: **M11 = PASS** — all 12 gates have execution evidence. HYDRAULIC_NETWORK_READY remains False (scientific limitation honoured). D-016/B13/B02 unchanged (no human approvals fabricated).

## Open decisions / next action
- **Pilot-area decision (NEW, data/model integration issue):** the established M1 pilot GridSpec does not overlap the real DEM/drainage/vents data. Human must decide: re-base the pilot GridSpec to the real pilot region (governed M1 spatial-foundation change) or keep the synthetic grid and treat the real data as a staged candidate. This is the root blocker for RD-03/RD-04/RD-12 and (with the CRS acceptance) RD-08/RD-11.
- D-016: hydrologist approval required (return-period mapping + derived totals) — flips profiles to APPROVED on sign-off.
- B13: PROVISIONAL DEMONSTRATION policy shipped (`B13-DEMO-V1`); expert review required before any operational wording.
- B02 WB AMRUT audit: OPEN (artifact obtained + audited 2026-08-22, evidence in `data/raw/acquisition_attempts.json` + `docs/M10_REAL_PILOT_FOUNDATION.md` §2.2/§3; remaining: human acceptance of the audit report, embedded-CRS basis, pilot-area decision).
- WB AMRUT rule table: approve/extend the explicit M10 type rules for the real vocabulary (`Nalla`, `Outfall`, "Storm Water Drain", …) if feature typing of the real data is wanted (no guessing until then).
- Hydraulic parameters for a REAL hydraulic network: if real drainage hydraulic simulation is wanted, the five required attributes (diameter_m, invert_upstream_m, invert_downstream_m, manning_n, capacity_m3s) must be independently obtained and governed (field survey / as-built / asset register). Until then MODE A (geometry only) is the only real-data mode and MODE B (synthetic hydraulics) is the only executable real-terrain mode. This flips `HYDRAULIC_NETWORK_READY` to True.
- Next milestone: M11 COMPLETE (PASS). No further milestone is blocked by M11.
