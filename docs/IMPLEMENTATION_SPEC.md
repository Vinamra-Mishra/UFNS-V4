# UFNS — IMPLEMENTATION MASTER SPECIFICATION

**SIH26085 — Urban Flood Nowcasting System (Drainage and Rainfall Coupling)**

**Status:** APPROVED FOR IMPLEMENTATION
**Phase:** Implementation
**Human approval:** Granted for the approved architecture and implementation direction
**Approval record:** human team decision table, 2026-08-21 (below)
**Canonical AI review:** `docs/AI_REVIEW.md`

---

## 0. Human approval record (2026-08-21)

| Area | Current | I'd use | Why |
| --- | --- | --- | --- |
| Pilot | West Bengal AMRUT | **Keep** | Best match to available drainage data; conditional audit |
| Surface model | Landlab OverlandFlow | **Keep** | Good established starting point |
| Drainage | SWMM Dynamic Wave | **Keep** | Strong fit for urban drainage/surcharge |
| Resolution | 30 m / ~4×4 km | **Keep for physics** | Defensible with current data/compute |
| Drainage parameters | Real + assumed + synthetic | **Keep** | Honest handling of missing hydraulic attributes |
| Rainfall | Baseline + ML later | **Keep, but strengthen nowcast layer** | SIH explicitly emphasizes 0–3 h nowcasting |
| Flood output | Depth/extent | **Keep + add uncertainty/confidence** | Better decision-support product |
| Routing | Flood-aware routing | **Keep, but make it a major feature** | Makes the system much more useful operationally |
| Dashboard | GIS | **Strengthen substantially** | This is what judges will actually see |
| Validation | Physics + benchmarks | **Keep** | One of your strongest aspects |
| Live data | Later | **Keep as later phase** | Don't compromise the core model to chase APIs |

---

# 1. MISSION

Build UFNS, an Urban Flood Nowcasting System for SIH26085.

The system must demonstrate:

```text
Rainfall
  ↓
Rainfall nowcasting
  ↓
Spatial rainfall field
  ↓
Rainfall → runoff
  ↓
Surface water routing
  ↕
Urban drainage network
  ↓
Hydraulic capacity / surcharge
  ↓
Flood depth + extent
  ↓
Road/intersection impact
  ↓
Flood-aware routing
  ↓
GIS decision-support dashboard
  ↓
Alerts / operational information
```

The system should support a 0–3 hour forecast horizon where the implemented and validated methodology supports that claim.

The goal is not a generic ML flood classifier. The central value is the coupling of rainfall, terrain, surface flow and urban drainage.

---

# 2. APPROVED ARCHITECTURE

These decisions have been approved by the human team and are the implementation baseline.

Do not replace them without explicit human approval.

| Area | Approved decision | Principle |
|---|---|---|
| Pilot | West Bengal AMRUT candidate, subject to the defined data audit | Best available drainage-data path |
| Surface solver | Landlab `OverlandFlow` | Established surface-flow starting point |
| Drainage solver | EPA SWMM Dynamic Wave | Urban drainage / surcharge modelling |
| Physical resolution | 30 m, approximately 4 × 4 km initial domain | Defensible with available data/compute |
| Drainage data | Real audited geometry + `ASSUMED` hydraulic parameters + synthetic fixture | Honest handling of incomplete asset data |
| Rainfall | Baseline first, ML progressively, strengthen nowcast layer | SIH requires meaningful nowcasting |
| Flood output | Depth + extent + confidence/uncertainty where scientifically supported | Decision support |
| Routing | Flood-aware routing as a major feature | Operational value |
| Dashboard | Strong GIS decision-support interface | Primary judge-facing product |
| Validation | Physics + conservation + benchmarks + scenario tests | Scientific credibility |
| Live data | Later phase after demo stability | Do not compromise core model |

---

# 3. SCIENTIFIC BOUNDARIES

## 3.1 Never fake science

Never fabricate:

- observations
- datasets
- accuracy
- validation
- model performance
- hydraulic parameters
- API availability
- licenses
- real-time capability
- scientific references

If something is unknown, say so.

If something is simulated, label it simulated.

If something is assumed, label it `ASSUMED`.

If something has not been validated, say:

`NOT YET VALIDATED`

---

## 3.2 Data labels

Every important dataset or output must distinguish:

```text
OBSERVED
HISTORICAL
FORECAST
SIMULATED
SYNTHETIC
DERIVED
MODEL PREDICTION
```

Never allow synthetic/demo data to appear as live observations.

---

## 3.3 30 m resolution boundary

The physical model is approximately 30 m over an approximately 4 × 4 km pilot.

Describe this honestly as:

> neighbourhood-scale flood screening / impact modelling

Do not claim curb-scale hydrodynamic resolution.

Road/intersection impact can be derived by intersecting the flood field with road geometry.

Do not create artificial physical resolution by merely resampling a 30 m DEM to smaller pixels.

---

# 4. KNOWN PHASE-0 RISKS

The Phase 0 audit identified important risks. They remain active until resolved.

## B02 — Pilot drainage data

Verify the selected West Bengal AMRUT candidate for:

- geometry
- schema
- provenance
- licensing
- elevation
- hydraulic attributes

Use the approved synthetic fallback where required.

---

## B03 — Demo hyetograph derivation

Every demo rainfall/hyetograph must have a documented derivation.

Do not use arbitrary unnamed rainfall curves.

---

## B05 — SWMM/surface coupling

The actual two-way coupling must be experimentally demonstrated.

Required tests include:

- surface → drainage exchange
- drainage → surface exchange
- surcharge
- ponding
- blockage
- timestep sensitivity
- mass conservation
- reproducibility

---

## B06 — Landlab spatial rainfall

Landlab's rainfall interface must be reconciled with the UFNS spatial rainfall contract through an explicit adapter.

Test:

- zero rainfall
- uniform rainfall
- spatial rainfall
- losses
- timestep changes
- conservation
- reproducibility

---

## B07 — Mass-gate thresholds

Document explicit mass-balance acceptance thresholds.

---

## B08 — Vertical datum

Ensure terrain and drainage elevations use a compatible vertical reference.

Never silently mix vertical datums.

---

## B11 — SIH alignment

Keep implementation aligned with the actual SIH26085 problem statement.

Avoid unrelated features.

---

## B12 — Benchmark data

Obtain required benchmark datasets or explicitly document their unavailability.

Never fabricate benchmark results.

---

## B13 — Vehicle passability thresholds

Vehicle/road thresholds are configurable demonstration policies.

They are not universal public-safety guarantees.

---

## B15 — Landlab/de Almeida documentation alignment

Document exactly what solver formulation is being used.

Do not overstate its physical scope.

---

## R01 — Independent flood truth

Independent flood-depth/extent ground truth may be limited.

Use physics tests, benchmark tests and transparent limitations.

Do not claim real-event accuracy without appropriate observations.

---

# 5. TARGET ARCHITECTURE

```text
                    DATA SOURCES
                         |
        +----------------+----------------+
        |                |                |
     Rainfall           DEM             Roads
        |                |                |
        +----------------+----------------+
                         |
                  DATA INGESTION
                         |
                  DATA ALIGNMENT
                         |
             +-----------+-----------+
             |                       |
       Rainfall Model           Terrain Model
             |                       |
             +-----------+-----------+
                         |
                    RUNOFF
                         |
             +-----------+-----------+
             |                       |
       Surface Routing        Drainage Graph
             |                       |
             +-----------+-----------+
                         |
                 HYDRAULIC COUPLING
                         |
                  FLOOD STATE
                         |
          +--------------+--------------+
          |              |              |
       Depth          Extent       Drainage
          |              |           State
          +--------------+--------------+
                         |
                    ROAD RISK
                         |
                 ROUTING ENGINE
                         |
                  GIS DASHBOARD
                         |
                  ALERT SYSTEM
```

Use modular components, but do not create unnecessary microservices.

---

# 6. CORE DATA CONTRACTS

Support typed contracts equivalent to:

```text
DataLineage
GridSpec
RainfallGrid
TerrainBundle
FloodSnapshot
DrainageNode
DrainageLink
DrainageState
RoadSegmentRisk
RouteRequest
RouteOption
SimulationRun
MassBalance
ScenarioDefinition
```

Every spatial object must identify:

- CRS
- spatial resolution
- units
- timestamp
- provenance

Every forecast must identify:

- initialization time
- valid time
- forecast horizon
- model version
- source

---

# 7. SCENARIO DEFINITION

`ScenarioDefinition` is a core contract.

It should support:

```text
scenario_id
name
description
rainfall_source
rainfall_profile
duration
initial_conditions
drainage_configuration
blockage_configuration
surface_parameters
simulation_resolution
simulation_timestep
random_seed where applicable
data lineage
```

A scenario must be reproducible.

---

# 8. REPOSITORY STRUCTURE

Follow the existing approved Phase-0 structure where applicable.

A suitable structure is:

```text
UFNS/
│
├── apps/
│   ├── web/
│   └── api/
│
├── services/
│   ├── ingestion/
│   ├── rainfall/
│   ├── hydrology/
│   ├── hydraulics/
│   ├── simulation/
│   └── routing/
│
├── models/
├── data/
│   ├── raw/
│   ├── processed/
│   └── demo/
│
├── infrastructure/
├── tests/
├── notebooks/
├── scripts/
│
├── docs/
│
├── docker-compose.yml
├── README.md
└── .env.example
```

Do not restructure unnecessarily.

---

# 9. TECHNOLOGY POLICY

Preferred candidates:

### Backend
- Python
- FastAPI

### Geospatial
- GDAL
- Rasterio
- Xarray
- GeoPandas
- Shapely
- PostGIS

### Scientific
- Landlab
- EPA SWMM / PySWMM where appropriate

### ML
- PyTorch
- Scikit-learn
- XGBoost where justified

### Frontend
- React / Next.js
- TypeScript
- MapLibre GL or equivalent
- deck.gl where useful

### Infrastructure
- Docker
- Docker Compose

Do not add dependencies without justification.

---

# 10. MULTI-AGENT ORGANIZATION

The project uses three primary AI workers.

## Antigravity 1 — Scientific/Data Agent

Own:

- data engineering
- GIS
- DEM
- rainfall data
- hydrology
- Landlab
- SWMM scientific coupling
- scientific experiments

Must not silently alter approved scientific assumptions.

---

## Antigravity 2 — Product/GIS Agent

Own:

- frontend
- dashboard
- GIS visualization
- forecast timeline
- flood layers
- road risk
- routing UX
- alerts

The interface must expose scientific state rather than hide it.

---

## Codex — Backend/Integration/QA Agent

Own:

- backend
- APIs
- orchestration
- integration
- testing
- CI
- regression testing
- cross-agent integration
- code review

Codex acts as integration gatekeeper.

---

# 11. AGENT RULES

Every agent MUST:

1. Read the relevant documentation before major work.
2. Read `docs/AI_REVIEW.md` before major work.
3. Inspect existing code before modifying it.
4. Avoid unnecessary rewrites.
5. Preserve interfaces where possible.
6. Add tests for major functionality.
7. Never delete tests to make builds pass.
8. Never fabricate data or metrics.
9. Never hide failures.
10. Record meaningful scientific decisions.
11. Update `docs/AI_REVIEW.md` after major milestones.
12. Stop when a scientific gate fails.
13. Never interpret silence as approval.
14. Never silently change the approved architecture.

---

# 12. CANONICAL AI REVIEW FILE

Create and continuously maintain:

```text
docs/AI_REVIEW.md
```

This is the single canonical human-facing project status file.

The human reviewer should be able to understand the project's real state by reading this file and visually inspecting the running application.

The file must contain:

# UFNS — AI Engineering Review

## 1. Current Status

```text
Phase:
Milestone:
Build:
Last Updated:
Overall Health:
```

Health:

```text
GREEN
YELLOW
RED
BLOCKED
```

## 2. Executive Summary

Maximum 10–15 lines.

State:

- what works
- what does not
- largest scientific risk
- largest engineering risk
- current milestone
- human review status

No marketing language.

## 3. What Is Actually Implemented

Use:

| Component | Status | Evidence | Test |
|---|---|---|---|

Allowed:

```text
DONE
PARTIAL
BROKEN
NOT IMPLEMENTED
```

`DONE` requires execution and verification.

## 4. Architecture Status

For each major component:

```text
IMPLEMENTED
PARTIAL
PLANNED
```

## 5. Scientific Model Status

For:

- rainfall
- runoff
- surface routing
- drainage
- hydraulic coupling
- flood depth
- road impact
- routing

Record:

```text
Method:
Status:
Inputs:
Outputs:
Validation:
Confidence:
Limitations:
```

## 6. Data Status

Use:

| Dataset | Source | Status | Type | License | Problem |
|---|---|---|---|---|---|

## 7. Nowcast Status

Record:

```text
Current rainfall:
Forecast horizon:
Forecast timestep:
Spatial resolution:
Nowcast method:
Baseline:
ML model:
Validation:
Latency:
Confidence:
```

Do not claim 0–3 hour operational nowcasting unless supported by implementation and evaluation.

## 8. Flood Impact Status

Record:

```text
Flood depth:
Flood extent:
Affected roads:
Affected intersections:
Drainage overload:
Route impact:
```

## 9. Mass Conservation

Record:

```text
Scenario:
Input volume:
Losses:
Storage change:
Boundary outflow:
Drainage exchange:
Residual:
Tolerance:
Result:
```

## 10. Test Status

Record:

```text
Unit:
Integration:
End-to-end:
Scientific:
Mass conservation:
Numerical stability:
Frontend:
Backend:
Passed:
Failed:
Skipped:
```

## 11. Scientific Validation

For every experiment:

```text
Experiment:
Purpose:
Dataset:
Configuration:
Expected:
Observed:
Metric:
Result:
Interpretation:
```

Never invent metrics.

## 12. Demo Status

Track:

```text
Normal rainfall
Heavy rainfall
Extreme rainfall
Extreme rainfall + drainage blockage
```

## 13. Known Problems

Use:

| ID | Problem | Severity | Impact | Fix | Status |
|---|---|---|---|---|---|

Severity:

```text
BLOCKER
HIGH
MEDIUM
LOW
```

## 14. Scientific Risks

Identify where the system may produce convincing but scientifically incorrect outputs.

## 15. AI-Generated Risk Areas

For each scientifically consequential AI decision:

```text
Component:
Decision:
Reason:
Scientific risk:
Evidence:
Human review required:
```

## 16. Human Decisions Required

List only decisions genuinely requiring human approval.

For each:

```text
Decision:
Options:
AI recommendation:
Reason:
Consequence:
```

## 17. Recommended Next Actions

Exactly five highest-priority actions.

## 18. Changes Since Previous Review

```text
Added:
Changed:
Fixed:
Removed:
New risks:
Resolved risks:
```

## 19. Agent Accountability

```text
Antigravity 1:
Antigravity 2:
Codex:
Human:
```

Do not dump raw logs.

## 20. FINAL AI RECOMMENDATION

Exactly one:

```text
CONTINUE
CONTINUE WITH CAUTION
STOP AND REVIEW
BLOCKED
READY FOR HUMAN DEMONSTRATION
```

Maximum 10 lines of justification.

---

# 13. MILESTONE PLAN

Implementation must proceed in order.

---

## M1 — DATA + SPATIAL FOUNDATION

Implement:

- approved pilot
- CRS
- DEM ingestion
- DEM conditioning
- rainfall representation
- spatial grid
- temporal grid
- provenance
- reproducible demo fixture
- ScenarioDefinition

Acceptance:

```text
[ ] Data loads
[ ] CRS verified
[ ] Timestamp handling verified
[ ] DEM visually inspected
[ ] Rainfall spatial representation verified
[ ] Provenance recorded
[ ] Scenario reproducible
```

Update `AI_REVIEW.md`.

---

# M2 — LANDLAB SURFACE-FLOW SPIKE

This is mandatory.

Implement the minimum adapter required to reconcile spatial rainfall with the approved Landlab approach.

Test:

### Zero rainfall

No rainfall-driven new input.

### Uniform rainfall

Sensible response.

### Spatial rainfall

Correct spatial mapping.

### Losses

Correct treatment and accounting.

### Timestep halving

Results remain within documented tolerance.

### Mass conservation

Track:

```text
rainfall input
-
losses
-
outflow
-
storage change
```

### Reproducibility

Same inputs reproduce the same output.

If the spatial rainfall adapter cannot be defended:

```text
STOP AND REVIEW
```

---

# M3 — SWMM COUPLING SPIKE

Implement the minimum two-way exchange needed to verify:

```text
surface
  ↕
exchange
  ↕
SWMM
```

Test:

- surface → drainage
- drainage → surface
- surcharge
- ponding
- outlet
- blockage
- timestep sensitivity
- mass conservation
- reproducibility

Do not assume the coupling works because API methods exist.

If the coupling fails:

```text
STOP AND REVIEW
```

---

# M4 — COUPLED FLOOD MODEL

Only after M2 and M3 pass.

Implement:

```text
Rainfall
↓
Runoff
↓
Landlab surface routing
↕
SWMM drainage
↓
Flood state
```

Outputs:

- water depth
- flood extent
- drainage state
- mass balance

---

# M5 — SCENARIO ENGINE

Implement:

## Scenario 1 — Normal rainfall

## Scenario 2 — Heavy rainfall

## Scenario 3 — Extreme rainfall

## Scenario 4 — Extreme rainfall + drainage blockage

Scenario 4 is the primary demonstration of drainage/rainfall coupling.

The same scenario inputs must produce reproducible results within documented numerical tolerance.

---

# M6 — GIS DASHBOARD

Build the judge-facing decision-support interface.

Layers:

- rainfall
- rainfall forecast
- DEM
- flood depth
- flood extent
- drainage
- drainage overload
- roads
- road risk

Controls:

- timeline
- layer toggles
- scenario selection
- legend
- units
- timestamps
- data source

Forecast timeline target:

```text
NOW
+15 min
+30 min
+60 min
+120 min
+180 min
```

Only display horizons actually produced by the underlying system.

---

# M7 — ROAD IMPACT + FLOOD-AWARE ROUTING

Implement a road graph.

Derive road risk from flood state.

Conceptually:

```text
Water depth
    ↓
Road impact
    ↓
Routing cost
```

Support:

```text
NORMAL
PENALIZED
HIGH RISK
BLOCKED
```

where justified.

Display:

```text
Fastest route
Flood-aware route
Recommended route
```

The route engine must actually consume flood predictions.

---

# M8 — RAINFALL NOWCAST

Implement:

```text
Persistence baseline
```

Then evaluate additional methods where data supports them:

```text
Statistical
Radar extrapolation
ML
Advanced ML
```

For every model record:

- dataset
- forecast horizon
- spatial resolution
- temporal resolution
- metric
- result
- baseline comparison
- inference latency

Do not use advanced ML merely for appearance.

---

# M9 — NOWCAST → IMPACT PIPELINE

Integrate:

```text
Rainfall nowcast
      ↓
Spatial rainfall
      ↓
Flood simulation
      ↓
+15
+30
+60
+120
+180
      ↓
Flood depth
      ↓
Flood extent
      ↓
Road impact
      ↓
Routing
```

This is the central SIH demonstration.

---

# M10 — LIVE DATA

Only after DEMO MODE is stable.

Use only verified live sources.

Expose:

```text
Source
Timestamp
Latency
Freshness
Provenance
```

If unavailable:

```text
LIVE DATA UNAVAILABLE
```

Never silently fall back to synthetic data while claiming live operation.

---

# M11 — VALIDATION + BENCHMARKING

Run applicable validation:

### Analytical

- closed-bowl
- planar-slope

### Surface

- wetting/drying
- timestep sensitivity

### Drainage

- SWMM continuity
- surcharge
- blockage

### Coupled

- mass conservation
- exchange behaviour

### Benchmarks

- EA 8A
- EA 8B where applicable

### Integration

- CRS
- timestamps
- provenance

### Sensitivity

Important uncertain parameters.

Never fabricate benchmark results.

---

# M12 — FINAL SIH DEMONSTRATION

The demonstration should tell one coherent story:

```text
Current rainfall
      ↓
0–3 hour nowcast
      ↓
Flood evolution
      ↓
Drainage response
      ↓
Drainage overload
      ↓
Flood depth
      ↓
Affected roads
      ↓
Flood-aware route
      ↓
Alert / decision support
```

---

# 14. DEMO MODE

DEMO MODE must be deterministic and reproducible.

It should allow selection of:

```text
rainfall scenario
drainage condition
blockage scenario
simulation duration
```

The UI must clearly state:

```text
DEMO / SIMULATED DATA
```

where applicable.

---

# 15. LIVE MODE

LIVE MODE must remain clearly separate.

It must never silently replace missing live data with synthetic data.

Every live source must provide:

```text
source
timestamp
latency
freshness
provenance
```

---

# 16. RAINFALL NOWCAST POLICY

The nowcast must be evaluated against a baseline.

At minimum:

```text
Persistence
```

Only retain ML if it provides measurable benefit.

The system should expose:

```text
forecast initialization time
forecast valid time
forecast horizon
rainfall intensity
source
model version
```

---

# 17. FLOOD UNCERTAINTY

Where scientifically supportable, expose uncertainty/confidence.

Potential sources:

- rainfall uncertainty
- DEM limitations
- drainage assumptions
- model parameter uncertainty
- incomplete observations

Do not invent confidence values.

If uncertainty is not yet quantified:

```text
Uncertainty quantification:
NOT YET IMPLEMENTED
```

---

# 18. FLOOD-AWARE ROUTING

The routing engine must use the flood field.

Example conceptual transformation:

```text
No flood
→ normal cost

Moderate flood
→ increased cost

Severe flood
→ very high cost

Impassable condition
→ road unavailable
```

Thresholds must remain configurable.

The UI must clearly state when a threshold is a demonstration policy.

---

# 19. SCIENTIFIC SANITY CHECKS

Before every major milestone:

### Zero rainfall

No new rainfall-driven flooding.

### Increased rainfall

Generally greater runoff/flood potential where the model permits.

### Reduced drainage capacity

Greater surcharge/surface accumulation where physically appropriate.

### Improved drainage capacity

Reduced surface accumulation where physically appropriate.

### Elevation

Water behaviour should respond sensibly to terrain.

### Water depth

No unexplained negative depth.

### Mass balance

Residual remains within documented tolerance.

### Timestep

Halving timestep must not create unexplained catastrophic changes.

---

# 20. RED-TEAM TESTS

Continuously test:

```text
A — Extreme rainfall
B — Zero rainfall
C — Blocked drainage
D — Missing drainage
E — DEM sinks
F — CRS mismatch
G — Timestamp mismatch
H — Missing rainfall
I — Multiple outlets
J — Negative depth
K — Numerical instability
L — Flooded road incorrectly selected
```

For every failure record:

```text
Expected:
Observed:
Cause:
Fix:
Regression test:
```

---

# 21. PERFORMANCE

Measure:

- data ingestion latency
- preprocessing time
- rainfall inference
- surface simulation time
- SWMM runtime
- coupling overhead
- total forecast runtime
- API latency
- frontend rendering

Do not claim real-time capability without measured latency.

---

# 22. SECURITY

Never commit:

- API keys
- passwords
- tokens
- credentials

Use:

```text
.env
.env.example
```

Validate external inputs.

---

# 23. REPRODUCIBILITY

The main demonstration must be reproducible from a clean environment.

Document:

```text
installation
dependencies
dataset preparation
configuration
simulation command
dashboard command
expected output
```

Do not rely on a developer's private machine state.

---

# 24. HUMAN REVIEW GATES

After every major milestone:

1. Update `docs/AI_REVIEW.md`.
2. Run tests.
3. Perform scientific sanity checks.
4. Ensure the application launches.
5. Ensure outputs are visually inspectable.
6. Record limitations.
7. Record human decisions if required.
8. Decide whether to continue.

Do not accumulate large amounts of autonomous work without review.

---

# 25. STOP CONDITIONS

Immediately set:

```text
STOP AND REVIEW
```

if:

- mass conservation fails materially
- numerical instability appears
- SWMM coupling fails
- Landlab spatial rainfall mapping is invalid
- required data becomes unavailable
- licensing is uncertain
- scientific behaviour contradicts expectations
- validation contradicts the model
- a major architecture change becomes necessary
- an agent cannot determine whether an implementation is scientifically defensible

Do not weaken the test merely to continue.

---

# 26. FINAL QUALITY GATE

Before declaring UFNS ready for SIH demonstration:

```text
[ ] Phase 0 approval recorded
[ ] Pilot verified
[ ] Data provenance documented
[ ] DEM pipeline works
[ ] CRS verified
[ ] Rainfall pipeline works
[ ] Rainfall/runoff works
[ ] Landlab surface routing works
[ ] Landlab spatial rainfall adapter validated
[ ] SWMM Dynamic Wave works
[ ] SWMM/surface coupling validated
[ ] Drainage participates in flooding
[ ] Blockage changes results
[ ] Mass conservation passes
[ ] Numerical stability checked
[ ] Flood depth generated
[ ] Flood extent generated
[ ] Road impact generated
[ ] Flood-aware routing works
[ ] Rainfall nowcast evaluated
[ ] 0–3 hour horizon claim supported where made
[ ] GIS dashboard works
[ ] Forecast timeline works
[ ] Demo scenarios reproducible
[ ] Demo/live distinction visible
[ ] Synthetic data labelled
[ ] Assumed data labelled
[ ] No fabricated metrics
[ ] No fake real-time claims
[ ] No secrets committed
[ ] Validation documented
[ ] Limitations documented
[ ] AI_REVIEW.md current
[ ] Human visual review completed
```

---

# 27. AGENT STARTUP PROCEDURE

When the agents receive this specification:

## Step 1

Inspect the repository.

## Step 2

Read:

```text
README.md
docs/ARCHITECTURE.md
docs/DATA_SOURCES.md
docs/MODEL_ASSUMPTIONS.md
docs/ROADMAP.md
docs/DECISIONS.md
docs/AGENT_STATE.md
docs/PHASE0_AUDIT.md
docs/PHASE0_APPROVAL.md
```

## Step 3

Confirm that the human-approved architecture matches this document.

If a conflict exists:

```text
STOP AND REVIEW
```

Do not silently resolve it.

## Step 4

Create/update:

```text
docs/AI_REVIEW.md
```

## Step 5

Begin:

```text
M1 — DATA + SPATIAL FOUNDATION
```

## Step 6

After M1:

```text
M2 — LANDLAB SPIKE
```

## Step 7

After M2:

```text
M3 — SWMM COUPLING SPIKE
```

## Step 8

Only after both spikes pass:

```text
M4 — COUPLED FLOOD MODEL
```

Then continue sequentially through M12.

---

# 28. FINAL ENGINEERING PHILOSOPHY

The system must optimize for:

```text
Scientific credibility
+
Reproducibility
+
Demonstrability
+
Engineering quality
```

not merely:

```text
Lines of code
+
Number of AI models
+
Dashboard complexity
```

Prefer:

```text
small + correct + validated
```

over:

```text
large + impressive + unvalidated
```

Use established scientific solvers rather than inventing them.

Use ML where it provides measurable value.

Use assumptions transparently where data is incomplete.

Keep the physical model honest about its 30 m neighbourhood-scale resolution.

Make the drainage-rainfall coupling the central differentiator.

Make the 0–3 hour nowcast → flood impact → routing pipeline the central SIH story.

---

# 29. FINAL DIRECTIVE TO THE AI TEAM

You are not being judged by how much code you produce.

You are being judged by whether UFNS can convincingly demonstrate:

> **Given rainfall and urban drainage conditions, how will flooding evolve over the next 0–3 hours, what areas and roads will be affected, and how should people respond?**

Build the system so that every important claim can be traced to:

```text
data
→ method
→ calculation
→ validation
→ visualization
```

When speed conflicts with scientific correctness:

**choose correctness.**

When complexity conflicts with reproducibility:

**choose reproducibility.**

When an impressive unvalidated model conflicts with a simpler validated model:

**choose the validated model.**

Never fabricate evidence.

Never hide uncertainty.

Never silently change approved scientific decisions.

Never claim a feature works until it has been executed and tested.

---

# 30. CANONICAL STATUS RULE

`docs/AI_REVIEW.md` is the single authoritative AI-to-human project status summary.

After every major milestone it must tell the human team:

```text
What works
What failed
What was validated
What remains uncertain
What changed
What is risky
What requires human attention
What should happen next
```

The human team will use:

```text
docs/AI_REVIEW.md
+
the running application
+
visual GIS outputs
```

as the primary review interface.

The AI team must never substitute marketing language for evidence.

---

# END OF IMPLEMENTATION MASTER SPECIFICATION
