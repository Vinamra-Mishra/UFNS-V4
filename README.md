# UFNS

**SIH26085 — Urban Flood Nowcasting System (Drainage and Rainfall Coupling)**

**Phase 1 — Implementation.** Phase 0 (architecture and scientific review) was completed, independently audited, and approved by the human team on 2026-08-21. The implementation baseline is [`docs/IMPLEMENTATION_SPEC.md`](docs/IMPLEMENTATION_SPEC.md); the canonical human-facing status file is [`docs/AI_REVIEW.md`](docs/AI_REVIEW.md).

UFNS is a reproducible, student-scale prototype that couples rainfall forcing, terrain-controlled surface flow, a 1-D storm-drain model, street exposure, and flood-aware routing for neighbourhood-scale flood screening. The current implementation supports:

- **historical / fixture scenario inspection** over **0–180 minutes** (M5–M7), and
- **persistence-based flood impact projection** over **0–60 minutes** from the latest M8 rainfall observation/nowcast (M9).

It is described honestly as **neighbourhood-scale flood screening**, not curb-scale hydraulics.

## Codebase Statistics

- **Real Code Base (SLOC)**: **20,855 source lines of code** (26,021 total lines across 103 `.py` and `.html` source files; excluding documentation markdown, JSON/YAML configs, and data fixtures).
  - `services/`: 10,307 SLOC (59 files)
  - `apps/`: 2,574 SLOC (10 files)
  - `scripts/`: 1,111 SLOC (8 files)
  - `tests/`: 6,863 SLOC (26 files)

## Documents

- [Implementation master specification](docs/IMPLEMENTATION_SPEC.md) — human-approved baseline (M1–M12)
- [AI engineering review](docs/AI_REVIEW.md) — canonical project status, updated after every milestone
- [Independent Phase 0 audit](docs/PHASE0_AUDIT.md) — audit findings, blockers, red-team record
- [Phase 0 approval matrix](docs/PHASE0_APPROVAL.md) — human decisions recorded
- [Architecture and data contracts](docs/ARCHITECTURE.md)
- [Candidate data sources and access audit](docs/DATA_SOURCES.md)
- [Scientific assumptions, equations, and validation plan](docs/MODEL_ASSUMPTIONS.md)
- [Delivery roadmap and quality gate](docs/ROADMAP.md)
- [Architecture/scientific decision log](docs/DECISIONS.md)
- [Agent coordination state](docs/AGENT_STATE.md)
- [M4 coupled flood model](docs/M4_COUPLED_MODEL.md)
- [M5 scenario engine](docs/M5_SCENARIO_ENGINE.md) — four-scenario suite, CONDITIONAL PASS (D-016 review)
- [D-016 rainfall derivation](docs/D016_RAINFALL_DERIVATION.md) — published-IDF derivation, PREPARED (human review required)
- [M6 dashboard & API](docs/M6_DASHBOARD.md) — scenario inspection dashboard + versioned API
- [M7 road impact + flood-aware routing](docs/M7_ROAD_IMPACT_ROUTING.md) — interactive flood UI, road impact, routing, B13-DEMO-V1 policy
- [M8 rainfall nowcast](docs/M8_NOWCAST.md) — provider-independent ingestion, persistence baseline, 188 tests (NOT_REAL_TIME)
- [M8 scientific review](docs/M8_SCIENTIFIC_REVIEW.md) — authoritative literature review informing nowcast architecture
- [M8 independent review](docs/M8_INDEPENDENT_REVIEW.md) — independent AI research review
- [M8 velocity integration roadmap](docs/M8_VELOCITY_INTEGRATION.md) — future B13 velocity integration plan
- [M9 nowcast → impact pipeline](docs/M9_NOWCAST_IMPACT.md) — persistence-driven flood impact projection, road impact, routing, API/dashboard integration
- [M10 real-pilot data foundation](docs/M10_REAL_PILOT_FOUNDATION.md) — real data contracts, DEM validation+normalization, drainage audit+entity mapping (spatial re-baseline + CRS provenance resolution 2026-08-23: 13/13 RD gates PASS; DEM VALIDATED+NORMALIZED; drainage VALIDATED via authoritative external CRS provenance; entity mapping executed; evidence-backed RD gate matrix inside)
- [M11 real-pilot model integration](docs/M11_REAL_PILOT_INTEGRATION.md) — real terrain + real drainage geometry integrated through explicit adapters over the unchanged M4 engine; HYDRAULIC_NETWORK_READY=False; 12/12 M11 gates PASS; evidence-backed gate matrix inside

## Milestones

```text
M1  Data + spatial foundation              done
M2  Landlab surface-flow spike             done, PASSED
M3  SWMM coupling spike                    done, PASSED (M3-01…M3-15)
M4  Coupled flood model                    done, PASSED (M4-01…M4-15; 81 tests)
M5  Scenario engine                        done, CONDITIONAL PASS (D-016 PREPARED, human review required)
                                           (S1-S4 suite; see docs/M5_SCENARIO_ENGINE.md)
M6  GIS dashboard                          done, PASS (dashboard + API; see docs/M6_DASHBOARD.md)
M7  Road impact + flood-aware routing       done, PASS (interactive flood UI; see docs/M7_ROAD_IMPACT_ROUTING.md)
M8  Rainfall ingestion + nowcasting         done, PASS (provider-independent, persistence baseline,
                                             NOT_REAL_TIME; 188 tests; see docs/M8_NOWCAST.md)
M9  Nowcast → impact pipeline               done, PASS (persistence-based flood impact projection,
                                             road impact, routing, API/dashboard; see docs/M9_NOWCAST_IMPACT.md)
M10 Real-pilot data foundation              REAL-PILOT VALIDATION PASS
                                             (spatial re-baseline + CRS provenance
                                             resolution 2026-08-23; 13/13 RD gates
                                             PASS; DEM VALIDATED+NORMALIZED;
                                             drainage VALIDATED via external CRS
                                             provenance; entity mapping executed;
                                             docs/M10_REAL_PILOT_FOUNDATION.md)
M11 Real-pilot model integration             REAL-PILOT MODEL INTEGRATION PASS
                                             (real terrain + real drainage geometry
                                             integrated through explicit adapters
                                             over the unchanged M4 engine;
                                             HYDRAULIC_NETWORK_READY=False;
                                             12/12 M11 gates PASS; real/synthetic
                                             separation intact; mass conservation
                                             7.8e-08; docs/M11_REAL_PILOT_INTEGRATION.md)
M12 Final SIH demonstration
```

## Current claim boundary

UFNS now implements a real flood model, scenario API/dashboard, M8 rainfall nowcast,
and an M9 **persistence-based flood impact projection** pipeline. The claim boundary
remains strict: no accuracy, real-time, validation, operational, or production-readiness
claim is made. All demo/fixture data is labelled `SIMULATED`/`SYNTHETIC`; assumed
parameters are labelled `ASSUMED`; and no synthetic data is presented as observed or live.

M9 is implemented as a **demonstration / architectural capability**:

```text
implemented:
    rainfall provider architecture (provider-independent interface)
    nowcast baseline (persistence; NOWCAST-PERSISTENCE-V1)
    forecast rainfall frames derived from M8 nowcast records
    M4 flood projection driven by explicit nowcast rainfall fields
    M7 road impact + routing on projected future flood states
    API (observations, nowcast, projections, providers, cache, verification)
    dashboard integration (projection mode + lead selector + projected routing)
    tests
not implemented / not claimed:
    NOT_REAL_TIME (no verified live rainfall feed; providers are SYNTHETIC/FIXTURE)
    no advection / no intensity evolution / no ML (nowcast is persistence-only)
    no validated forecast skill (verification = NOT_EVALUATED)
    no operational flood forecasting
    no flood-state data assimilation beyond the configured synthetic initial state
    D-016 unchanged (PREPARED — human review required)
    B02 CRS provenance RESOLVED (MoHUA/TCPO/NRSC authoritative external;
        embedded CRS absent; human acceptance of full audit still open; see M10 doc §3/§13)
    B13 unchanged (PROVISIONAL DEMONSTRATION; depth-only demo policy)
```

**M11** integrates the validated Bagjola/Kolkata real pilot into the existing
model through explicit adapters over the **unchanged** M4 engine (real terrain
from the real DEM; real drainage geometry mapped + reprojected EPSG:4326→32645).
The strict claim boundary is preserved:

```text
implemented (M11):
    REAL_TERRAIN integrated through the coupled engine (MODE B, real ROI)
    REAL_DRAINAGE_GEOMETRY mapped + reprojected to the pilot grid (MODE A)
    explicit hydraulic readiness contract (5 required attrs MISSING by source)
    deeply immutable real-pilot provenance; mass conservation (7.8e-08)
    truthful API inspection (/api/v1/pilot/real{,...})
not implemented / not claimed (M11):
    NOT a real hydraulic drainage network (HYDRAULIC_NETWORK_READY=False:
        diameter/invert/Manning/capacity MISSING by source — MODE B uses an
        explicitly-labelled SYNTHETIC/ASSUMED fixture, never REAL_DATA)
    NOT real-time, NOT a validated forecast (D-016 PREPARED; rainfall PROVISIONAL)
    NOT operational flood forecasting; NOT certified road safety
    real DEM vertical datum UNVERIFIED (synthetic fixture datum anchored to
        the real ROI basin for coupling only)
```

## Quick start (M1)

```bash
python3 -m venv .venv            # or: pip install --user --break-system-packages -r requirements.txt
. .venv/bin/activate
pip install -r requirements.txt -r requirements-spikes.txt   # spikes: landlab, pyswmm
make demo-data                   # builds data/demo bundle (synthetic fixtures + manifest)
make test                        # runs the test suite
python scripts/run_m11_real_pilot_validation.py   # M11 real-pilot integration gate matrix
```

## Dashboard (M7 / M9)

```bash
. .venv/bin/activate
python3 scripts/run_dashboard.py   # http://127.0.0.1:8000
```

The dashboard supports both:

- the precomputed M5 historical scenarios (M6/M7 mode), and
- the M9 **persistence projection** mode that runs the nowcast-driven flood-impact
  pipeline once per observation/configuration and serves the cached projection.

It adds an interactive flood map (pan/zoom, layer toggles, hover/click inspection),
a timeline (play/pause/step/speed), time-dependent road impact, and normal-vs-
flood-aware routing. The road network is a SYNTHETIC demo fixture (`NOT REAL ROAD
GEOMETRY`); the B13 passability policy is `PROVISIONAL DEMONSTRATION`. All outputs
are labelled `SYNTHETIC`/`SIMULATED`/`PROVISIONAL` and are `NOT FOR OPERATIONAL USE`.
