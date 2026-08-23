# M5 — Scenario Engine on the Validated Coupled Flood Model

**Status:** CONDITIONAL PASS — D-016 REVIEW REQUIRED
**Date:** 2026-08-21
**Scope:** Deterministic four-scenario suite executed on the unmodified M4 coupled model.

---

## 1. Objective

Build a deterministic scenario engine that executes the validated M4 coupled model under a documented, comparable scenario suite. Prove that UFNS can compare flooding outcomes under controlled, reproducible rainfall and drainage conditions.

Target flow:

```
Scenario definition
      ↓
Validated rainfall profile
      ↓
Drainage condition
      ↓
M4 coupled simulation (unchanged scientific semantics)
      ↓
Time-indexed flood snapshots
      ↓
Scenario metrics
      ↓
Cross-scenario comparison
      ↓
Provenance + acceptance evidence
```

## 2. Scope

**In scope (M5):**
- Typed scenario schema and registry
- Rainfall-profile governance with explicit review status
- Drainage-condition governance (NORMAL / BLOCKED)
- Four-scenario suite: S1 Normal, S2 Heavy, S3 Extreme, S4 Extreme+Blocked
- Per-scenario execution on the M4 engine (clean initial state per run)
- Time-indexed flood snapshots, mass ledger, metrics
- S3/S4 paired blockage comparison
- Deterministic visual diagnostics (labelled SYNTHETIC/SIMULATED/PROVISIONAL)
- 18-gate test matrix (M5-01 … M5-16 plus regression guards)

**Out of scope (M6+):** production dashboard, road routing, rainfall nowcasting, live data integration, real-pilot calibration. No new surface/drainage/coupling solver.

## 3. M4 Foundation Reused

Every M5 scenario runs on the unmodified M4 engine (`services/simulation/engine.py`):

| Component | M4 Implementation |
|---|---|
| Rainfall | 15-minute fields (spatially variable), convective-cell pattern, deterministic seed |
| Losses | Micro-depression store (2 mm) + per-cell Horton (f0=25, fmin=2 mm/h, k=1/1800 s⁻¹) |
| Surface | Landlab OverlandFlow (de Almeida et al. 2012), adaptive dt, 1 s sub-steps within 5 s coupling stride |
| Drainage | EPA SWMM 5.2.4 dynamic wave via PySWMM 2.1; exact-exchange synthetic fixture (ST1→C1→V1→C2→O1); 16 rim inlets + vent cell |
| Coupling | Signed head-driven orifice (Cd=0.6, Ao=0.002 m²/inlet); capture + return; engine-exact per-stride ledger; causally ordered |
| Domain | Synthetic 134×134 DEM @ 30 m, ~4×4 km, EPSG:32645, SYNTHETIC_LOCAL_DATUM |
| Coupling dt | 5 s (integer, pyswmm stride requirement) |
| Snapshots | Every 5 minutes for 180 minutes → 37 snapshots per scenario (lead 0…180) |

No scientific constants, sign conventions, coupling order, loss parameters or timestep semantics were altered in M5.

## 4. Scenario-Engine Architecture

```
services/scenarios/
├── __init__.py        # module version
├── profiles.py        # RainfallProfileRecord + governance (§6)
├── drainage.py        # DrainageCondition + governance (§7)
├── registry.py        # ScenarioRecord + M5_SCENARIOS registry (§5, §8)
├── runner.py          # run_scenario / run_all_scenarios + ScenarioResult (§10, §13)
├── comparison.py      # ScenarioComparison + S3/S4 paired diff (§11)
└── diagnostics.py     # Visual diagnostic renderers (§16)

scripts/run_m5_diagnostics.py   # end-to-end driver
```

Execution: `ScenarioRecord` → `RunConfig` (M4) → `CoupledFloodModel.run()` → `ScenarioResult` (typed, fingerprinted, ledger-audited). Scenario behavior is data, not engine conditionals.

## 5. Scenario Schema

Every scenario is a typed `ScenarioRecord` with:

| Field | Description |
|---|---|
| `scenario_id` | Canonical ID (S1…S4) |
| `display_name` | Human-readable title |
| `description` | Scenario intent |
| `rainfall_profile` | `RainfallProfileRecord` (full provenance) |
| `rainfall_status` | PROVISIONAL / APPROVED / SIMULATED / INVALID |
| `drainage_condition` | `DrainageCondition` (NORMAL or BLOCKED) |
| `duration_minutes` | 180 (fixed) |
| `start_time` | UTC issue time |
| `initial_condition_policy` | Clean: film-scale depth, zero wetting clocks, zero microstore, SWMM dry |
| `coupling_timestep_s` | 5 |
| `snapshot_interval_minutes` | 5 |
| `surface_config_fingerprint` | Hash of surface/loss/exchange constants |
| `swmm_fixture_fingerprint` | Hash of the SWMM INP bytes |
| `assumptions` | Per-scenario + shared assumption list |
| `limitations` | Per-scenario + shared limitations |
| `provenance_note` | Audit trail string |
| `fingerprint` | Scenario identity hash (16 hex chars) |

## 6. Rainfall-Profile Governance

Three profiles are defined using the alternating-block construction (Chow, Maidment & Mays 1988, ch. 14) from a provisional depth-duration curve `P(d) = P60·(d/60)^0.4`:

| Profile | Total (mm) | Peak (mm/h) | Mean (mm/h) | Intervals | Status | D-016 |
|---|---|---|---|---|---|---|
| P_NORMAL | 20 | ~29.6 | ~6.7 | 12×15 min | PROVISIONAL | PENDING |
| P_HEAVY | 45 | ~66.6 | ~15.0 | 12×15 min | PROVISIONAL | PENDING |
| P_EXTREME | 90 | ~133.2 | ~30.0 | 12×15 min | PROVISIONAL | PENDING |

Each `RainfallProfileRecord` carries: profile ID, derivation citation, temporal resolution, duration, total depth, peak intensity, spatial policy (convective-cell, deterministic seed 20260821), alternating-block ordering note, units, review status, D-016 status, explicit limitations, and a content fingerprint.

Severity labels are defined in code (see `SEVERITY_DEFINITIONS` in `profiles.py`) — no undocumented "normal/heavy/extreme" string is used.

**D-016 status:** PENDING. Until a hydrologist approves a derived design storm (candidate: published WB/Kolkata IDF or documented historical event), every profile remains PROVISIONAL and is labelled NOT FOR OPERATIONAL USE. The engine runs and reports results regardless (M5 spec §6 permits implementation and output before D-016 closure), but the acceptance decision is CONDITIONAL PASS.

## 7. Drainage-Condition Governance

Two conditions on the synthetic SWMM fixture:

### NORMAL (D_NORMAL)
- M4 clean INP (`data/demo/drainage_synthetic_m4.inp`)
- C1 conduit diameter = 0.30 m
- Full-bore Manning capacity ≈ 97 L/s (analytically verified)
- No surcharge expected in S1–S3; drainage stays in capture regime

### BLOCKED (D_BLOCKED)
- M4 blocked INP (`data/demo/drainage_synthetic_m4_blocked.inp`)
- C1 conduit diameter = 0.12 m (capacity ratio ≈ (0.12/0.30)^(8/3) ≈ 0.087)
- Full-bore capacity ≈ 8.4 L/s (~11.5× conveyance loss)
- Blockage is a real hydraulic capacity reduction in the SWMM INP, not a depth multiplier or visualization adjustment
- Affected asset: link C1 (single-conduit constriction; pumps/gates/tide out of scope)

Each `DrainageCondition` carries: condition ID, display name, status, INP path, INP fingerprint, affected asset list, C1 diameter, C1 full-bore capacity, capacity ratio to normal, reason, physical mechanism, assumptions, limitations, parameter status.

## 8. Required Scenario Definitions

| ID | Display Name | Rain | Drain | Blockage | Duration | dt_c | Snap |
|---|---|---|---|---|---|---|---|
| S1 | Normal Rainfall + Normal Drainage | P_NORMAL (20 mm) | D_NORMAL | — | 180 min | 5 s | 5 min |
| S2 | Heavy Rainfall + Normal Drainage | P_HEAVY (45 mm) | D_NORMAL | — | 180 min | 5 s | 5 min |
| S3 | Extreme Rainfall + Normal Drainage | P_EXTREME (90 mm) | D_NORMAL | — | 180 min | 5 s | 5 min |
| S4 | Extreme Rainfall + Blocked Drainage | P_EXTREME (90 mm) | D_BLOCKED | C1 D=0.12 m (from t=0) | 180 min | 5 s | 5 min |

**Comparability (§8):** DEM, grid, surface parameters, rainfall forcing (for paired comparison), initial surface state, initial drainage state, simulation duration, coupling timestep, snapshot cadence, and model versions are identical across scenarios. S3 vs S4 differs **only** in C1 diameter.

## 9. Initial-State Policy

Per scenario, fresh state:
- Surface depth = h_init (1e-6 m, film scale only)
- Horton wetting clocks = 0
- Micro-depression store = 0
- SWMM nodes/links dry (initial depth/flow = 0 per INP)
- Simulation clock = 0
- Each scenario constructs a new `CoupledFloodModel` instance (M5-10 verifies no cross-run leakage; M5-13 verifies byte-identical reruns)

## 10. Run and Output Contracts

Each completed scenario produces a `ScenarioResult` with:

```
scenario metadata          scenario_id, display_name, description
run_id                     unique per run (timestamped)
config_fingerprint         64-char SHA-256 of RunConfig
input_manifest             dem_shape, cell_size, CRS, INP paths & FPs, seed, parameters
rainfall_summary           profile_id, total mm, peak mm/h, total volume, units
loss_summary               Horton m3, microstore final m3, parameters
surface_storage_summary    initial/final/Δ storage m3, boundary outflow m3
drainage_storage_summary   initial/final/Δ storage m3 (identity & readback), outfall m3, routing error %
exchange_summary           S2D m3, D2S m3, flood export m3, net exchange m3
boundary_summary           surface outflow m3, drainage outfall m3, external inflow m3
peak_depth_m               maximum water depth over the run
mean_depth_m               mean core-cell depth at final snapshot
max_flooded_area_m2        max area where depth > 0.05 m
time_to_peak_min           lead time of first peak
max_drainage_surcharge_m   max(0, ST1_head − vent_ground_elev) over run
mass_ledger                surface/drainage/combined/absolute/relative residuals, tolerance, PASS/FAIL
wall_seconds               wall-clock runtime
cpu_seconds                CPU time
peak_rss_mb                peak resident set size
snapshot_inventory         per-snapshot: lead, max/mean depth, flooded cells/area, storage, ST1 head, outfall, S2D, D2S, surcharged flag, asset URI
acceptance                 per-gate PASS/FAIL + overall
limitations                per-scenario limitations
run_fingerprint            hash of scenario identity + key outputs (for reproducibility checks)
labels                     ["SYNTHETIC","SIMULATED","PROVISIONAL"]
d016_status                "PENDING"
```

All units are explicit. No metric is fabricated, rounded to conceal instability, or inferred from visuals.

## 11. Comparison Methodology

`ScenarioComparison` (see `comparison.py`) produces a deterministic JSON artifact containing:

1. **Per-scenario row:** scenario_id, rainfall total, rainfall status, drainage condition, peak depth, max flooded area, time to peak, max surcharge, S2D, D2S, outfall, combined residual, runtime, acceptance.
2. **S3/S4 paired comparison:**
   - δ peak depth (m)
   - δ flooded area (m²)
   - δ surface storage change (m³)
   - δ max surcharge (m)
   - Capture reduction (S3 S2D − S4 S2D, m³)
   - Additional spill (S4 D2S − S3 D2S, m³)
   - Outfall reduction (S3 outfall − S4 outfall, m³)
   - Physical interpretation (observation-based, not predictive)
3. **Comparability controls:** suite-wide fixed parameters + S3/S4 pairwise control booleans.

## 12. Mass Accounting

The M4 coupled ledger is reused without modification. For every scenario the following are reported separately:

```
surface_residual_m3     rain − losses − surf_out − S2D + D2S + flood_export − ΔS_s − microstore
drainage_residual_m3    ext + S2D − D2S − flood_export − outfall − ΔS_d    (~0 by engine identity)
combined_residual_m3    rain + ext − losses − surf_out − outfall − ΔS_s − ΔS_d − microstore
absolute_residual_m3    |combined_residual|
relative_residual       |combined_residual| / max(|rain|+|ext|, 1e-6)
configured_tolerance    0.01 (1%, M4 gate)
gate                    PASS if relative ≤ tolerance
```

Exchange terms (S2D, D2S, flood_export) appear with opposite signs in the two subsystem ledgers and **cancel in the combined ledger**. They are never double-counted as external rainfall, inflow, loss, or outflow. This is explicitly asserted by test M5-11.

## 13. Test Matrix

All tests in `tests/test_m5_scenarios.py` (plus the full M4 regression suite, 81 → 99 total):

| Test | Gate | Result |
|---|---|---|
| M5-01 | scenario schema validation | PASS |
| M5-02 | required scenario IDs & metadata | PASS |
| M5-03 | rainfall-profile provenance & status | PASS |
| M5-04 | normal scenario execution (S1) | PASS |
| M5-05 | heavy scenario execution (S2) | PASS |
| M5-06 | extreme scenario execution (S3) | PASS |
| M5-07 | extreme + blockage execution (S4) | PASS |
| M5-08 | paired-comparison control variables | PASS |
| M5-09 | blockage sensitivity (physical direction) | PASS |
| M5-10 | independent scenario isolation | PASS |
| M5-11 | per-scenario mass conservation | PASS |
| M5-12 | cross-scenario snapshot determinism | PASS |
| M5-13 | complete-suite reproducibility | PASS |
| M5-14 | invalid-configuration handling | PASS |
| M5-15 | output manifest and fingerprinting | PASS |
| M5-16 | scenario-summary consistency | PASS |
| + regression | M4 heavy baseline reproduced by S2 | PASS |
| + regression | M4 engine unchanged (DT_C_DEFAULT, MODEL_VERSION) | PASS |
| **M4 full regression** | 81 pre-M5 tests still pass | PASS |

**Full suite: 99 / 99 passing.**

## 14. Results

All four scenarios were executed on the 2 vCPU sandbox.

### Per-scenario metrics

| Metric | S1 Normal | S2 Heavy | S3 Extreme | S4 Extreme+Blocked |
|---|---|---|---|---|
| Rain total (mm) | 20 | 45 | 90 | 90 |
| Drainage | Normal | Normal | Normal | Blocked (C1 D=0.12) |
| Peak depth (m) | 0.243 | 0.471 | 0.614 | 0.615 |
| Max flooded area (km²) | 0.234 | 1.792 | 4.577 | 4.579 |
| Time to peak (min) | 180 | 180 | 180 | 180 |
| Max ST1 surcharge (m) | 0.000 | 0.000 | 0.000 | 0.301 |
| S2D capture (m³) | 313.6 | 495.7 | 858.5 | 293.2 |
| D2S spill (m³) | 0.0 | 0.0 | 0.0 | 136.9 |
| Outfall (m³) | 308.6 | 488.3 | 847.7 | 138.9 |
| Surface Δ storage (m³) | ~448 | ~1,673 | ~4,745 | ~5,444 |
| Relative residual | ~5.3e-6 | ~1.6e-4 | ~2.1e-4 | ~2.0e-4 |
| Mass gate | PASS | PASS | PASS | PASS |
| Wall time (s) | ~17 | ~17 | ~18 | ~18 |

### S3 → S4 paired blockage differences (identical rainfall, only C1 diameter changes)

| Metric | Δ (S4 − S3) |
|---|---|
| Capture (S2D) | −565.3 m³ (−66%) |
| Drainage surcharge return (D2S) | +136.9 m³ (0 → 137) |
| Outfall | −708.8 m³ (−84%) |
| Max ST1 surcharge above vent ground | +0.301 m |
| Surface Δ storage | +699.2 m³ (+15%) |
| Max flooded area | +2,700 m² (+0.06%) |
| Global peak depth | +0.002 m (+0.4%) |

**Physical interpretation (PHYSICALLY CONSISTENT):** Reducing C1 to 0.12 m cuts conduit capacity by ~11.5×, preventing captured stormwater from draining to outfall. Storage node ST1 pressurizes; head rises 0.30 m above vent ground level, the return orifice activates and spills ~137 m³ onto the surface at the vent cell. Inlet capture is throttled by 66% (backwater), outfall drops 84%, and ~699 m³ of additional water is retained on the surface — a combination of suppressed capture and vent return. The global peak depth change is small (2 mm) because the basin's deepest point is determined primarily by terrain and direct rainfall volume (90 mm falls in both scenarios); the vent cell is a single rim cell and the additional ponding there does not dominate the basin-wide maximum. The mass-ledger, surcharge, capture throttling, outfall reduction, and surface-storage increase together demonstrate an unambiguous, hydraulically interpretable blockage response on the flow path.

## 15. Runtime

Measured on the 2 vCPU / 3.9 GiB sandbox:

| Scenario | Wall (s) | CPU (s) |
|---|---|---|
| S1 | ~17 | ~50 |
| S2 | ~17 | ~50 |
| S3 | ~18 | ~52 |
| S4 | ~18 | ~51 |
| **Suite total** | **~71** | **~203** |

Throughput: ≈ 610× real-time per 3-hour coupled scenario on two vCPUs. Peak RSS ~270 MB per run (M4-13 baseline). No real-time operational claim is made from these numbers; M9/M10 will re-measure on the pilot pipeline.

## 16. Visual Diagnostics

Generated under `data/demo/m5/`:

```
m5_summary_table.png                       Scenario summary table (labelled)
m5_comparison.json                         Deterministic comparison artifact
m5_results.json                            Per-scenario result summaries
s1/
  S1_rainfall_peak.png                    Rainfall preview (peak interval)
  S1_peak_depth_t180.png                  Peak-depth map
  S1_max_flood_extent.png                 Flood-extent map (h > 0.05 m)
  S1_depth_timeline.png                   Peak depth + flooded area vs lead
  S1_drainage_timeline.png                ST1 head / S2D / D2S / outfall vs lead
  depth_t000…t180.tif                     37 GeoTIFF snapshots (provenance tagged)
s2/, s3/, s4/                              (same structure)
s3s4_comparison/
  S3_peak_depth.png
  S4_peak_depth.png
  S4_minus_S3_depth_diff.png              Depth difference (diverging ramp)
  flooded_area_difference.png             Area vs lead for both scenarios
  drainage_surcharge_comparison.png       ST1 head / D2S vs lead for both
```

Every image carries a visible banner with one or more of the labels **SYNTHETIC**, **SIMULATED**, **PROVISIONAL**. Outputs are explicitly NOT presented as observations or street-scale truth (30 m resolution is clearly noted in the labelling). Rendering is deterministic: same inputs → byte-identical PNGs (modulo timestamp metadata stripped by Pillow).

## 17. Scientific Limitations

1. **Synthetic fixture only** — results represent no real location, network, or event.
2. **PROVISIONAL rainfall** — profiles are illustrative alternating-block hyetographs, not calibrated to gauge records, return periods, or published IDF curves (D-016 pending).
3. **PROVISIONAL loss parameters** — f0, fmin, k, and microstore capacity are literature/illustrative values, not fitted.
4. **ASSUMED orifice parameters** — Cd=0.6 and Ao=0.002 m²/inlet are textbook/fixture values.
5. **Single-blockage model** — one conduit (C1) constricted statically from t=0; distributed inlet blockage, pump failure, gate/tide effects, and progressive blockage are out of scope.
6. **Single-pipe synthetic network** — 16 inlets → ST1 → C1 → V1 → C2 → O1; real drainage networks have thousands of assets and 2D interactions beyond this fixture.
7. **30 m resolution limit** — street-scale processes (curb flow, inlet hydraulics, building tailwater) are not resolved; outputs are not street-scale truth.
8. **Landlab film bias** — h_init=1e-6 m creates a bounded virtual-water source (~0.02–0.04% of rainfall); quantified in residuals, never silently absorbed.
9. **SWMM storage readback quirk** — node.volume readback under-reports ~10–15% mid-run under dynamic wave (M3 doc §8); ledger uses SWMM's own engine identity (engine-exact); readback kept as diagnostic only.
10. **No real calibration or validation** — no observed event is reproduced; flood magnitudes are physically plausible on the synthetic fixture but not validated against measurements.

## 18. D-016 Status

**PENDING.**

D-016 (hyetograph-derivation review) remains open. Until a hydrologist approves a design-storm derivation (published IDF for the pilot region or a documented historical event), all M5 rainfall profiles are PROVISIONAL. The engine, tests, scenarios, diagnostics, and documentation all record this status explicitly. No claim is made that the 20/45/90 mm totals represent real return-period events.

## 19. Human-Review Requirements

The following human reviews are required or already recorded:

| Review | Status | Evidence |
|---|---|---|
| M2 surface-adapter accounting (residual outflow, film bound, clamp) | Recorded as closed in M4 review; re-affirmed here | `docs/AI_REVIEW.md` |
| M3 coupling semantics and M3-09 conservation | Recorded as closed | `docs/M3_SWMM_COUPLING.md` |
| M4 coupled model acceptance | **PASS** (2026-08-21) | `docs/M4_COUPLED_MODEL.md`; 81/81 tests |
| M4 visual review (DEM, rain, clean/blocked flood, difference, timelines) | **UNSUPPORTED / REMOVED** | — |
| D-016 hyetograph approval | **PENDING** | This doc §18; profiles labelled PROVISIONAL |
| B02 WB AMRUT drainage-data audit | Open (partial audit recorded) | `docs/DATA_AUDIT_WB_AMRUT.md` |
| Vehicle passability thresholds (B13) | Deferred to M7 | — |

## 20. Acceptance Decision

```text
CONDITIONAL PASS — D-016 REVIEW REQUIRED
```

### Acceptance checklist (M5 spec §20)

| Gate | Status |
|---|---|
| M4 remains green (81 → 99 total, all passing) | ✅ |
| Four required scenario classes implemented (S1–S4) | ✅ |
| Scenario schema validated (M5-01) | ✅ |
| Rainfall profiles have documented provenance and status (PROVISIONAL) | ✅ |
| Drainage conditions are explicit and hydraulically real (0.30 m vs 0.12 m C1) | ✅ |
| Every scenario runs from a clean initial state (M5-10) | ✅ |
| Every scenario produces snapshots and summaries (37 snapshots per scenario) | ✅ |
| Every scenario passes mass-accounting gates (M5-11, all ≤1% relative) | ✅ |
| Exchange cancels in combined ledgers (M5-11 asserts) | ✅ |
| S3/S4 paired comparison is controlled and interpretable (PHYSICALLY CONSISTENT) | ✅ |
| Scenario isolation passes (M5-10) | ✅ |
| Full-suite reproducibility passes (M5-13) | ✅ |
| Invalid-configuration handling passes (M5-14) | ✅ |
| Comparison artifacts generated (`m5_comparison.json`) | ✅ |
| Visual diagnostics generated and labelled (§16) | ✅ |
| Documentation complete (this document) | ✅ |
| AI_REVIEW and AGENT_STATE consistent | ✅ |
| D-016 status honestly recorded (PENDING) | ✅ |

The conditional gate is D-016. Upon hydrologist approval of the rainfall-profile derivation, the profile statuses move from PROVISIONAL to APPROVED, and the acceptance decision may be upgraded to PASS. No code change is required for that upgrade — only metadata updates on the `RainfallProfileRecord` entries and a re-run of the diagnostics script.

**No hard-stop conditions (M5 spec §19) were triggered:** no M4 regression, no mass-conservation failure, no state leak, no hidden change to M3 coupling semantics, no non-finite or negative physical states, no fabricated provenance.

**M6+ (dashboard, routing, nowcasting, pilot integration) remain out of scope and are not started.**
