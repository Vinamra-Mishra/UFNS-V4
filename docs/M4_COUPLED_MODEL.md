# M4 — Coupled Flood Model on the Validated Synthetic Fixture

**Status:** COMPLETE — **M4 PASS**
**Date:** 2026-08-21
**Scope:** first complete coupled UFNS flood simulation on the synthetic fixture; NOT the production flood model, NOT the real pilot.

---

## 1. Objective

Convert the validated M2 (Landlab surface) and M3 (SWMM↔surface coupling) spikes into one coherent simulation proving: rainfall can drive runoff, surface water can interact with drainage, drainage can surcharge back to the surface, and the complete system produces physically interpretable flood-depth snapshots while maintaining water accounting.

## 2. Scope

The validated synthetic fixture only (134×134 @ 30 m, EPSG:32645, SYNTHETIC DEM; synthetic SWMM network). Provisional rainfall (D-016). No dashboard, no routing, no ML, no live data — all deferred to M5+.

## 3. Existing validated components

- M1: contracts, CRS/time policy, synthetic DEM, provisional alternating-block hyetographs, provenance manifests, mass ledger.
- M2: Landlab `OverlandFlow` adapter (de Almeida et al. 2012), spatial rainfall, Horton losses, exact residual boundary-outflow accounting, film diagnostics, fail-fast negatives.
- M3: SWMM 5.2.4 dynamic wave (PySWMM 2.1), signed head-driven orifice exchange, engine-exact per-stride drainage identity, 15/15 gate tests.

## 4. Coupled architecture

```
Rainfall fields (15-min, spatial)
   -> micro-depression store (2 mm, PROVISIONAL)
   -> Horton infiltration (per-cell wetting clocks, PROVISIONAL)
   -> Landlab surface routing (1 s sub-steps, adaptive internally)
   <-> multi-inlet capture + vent return (signed head-driven orifices, M3 laws)
   <-> SWMM dynamic wave (ST1 -> C1 -> V1 -> C2 -> O1, datum-shifted)
   -> time-indexed FloodSnapshots (5 min) + coupled mass ledger
```

Engine: `services/simulation/engine.py` (`CoupledFloodModel`, `RunConfig`, `RunLedger`, `M4RunResult`).

## 5. Time ordering (explicit, causal; identical to M3 per stride)

1. read SWMM state at t_{i+1} (post-stride); 2. export completed-stride flooding; record stride outfall; 3. update ΔS_d via SWMM's own per-stride identity; 4. final read-only stride ends the loop; 5. apply rainfall (bucket of the stride start) → microstore fill → Horton on core cells; 6. advance surface routing (dt_c / surface_substeps); 7. compute signed exchange from aligned states (multi-inlet capture, vent return, availability caps); 8. drive SWMM for the next stride (generated_inflow at ST1); 9. record ledger; snapshot if scheduled. Never uses future state (M3-13 regression re-encoded).

## 6. Initial conditions

Per run, clean state: surface depth 0 (film only), Horton wetting clocks 0, microstore 0, SWMM dry, t=0. No state may leak between runs (M4-09 verifies bitwise).

## 7. Rainfall forcing

Provisional alternating-block hyetographs (Chow et al. 1988; PROVISIONAL P60/exponent, D-016 review before M5). M4 scenarios: zero; uniform 10 mm/h; spatial convective cell 20 mm/h; heavy profile (45 mm/3 h, convective pattern); heavy + blockage (identical forcing). Fields rendered per 15-min interval by the M2 renderer (seeded, deterministic).

## 8. Loss model

Micro-depression store (0.002 m capacity, PROVISIONAL) filled from rainfall before it reaches the surface, then per-cell Horton capacity f = fmin + (f0−fmin)e^(−kt) (f0=25, fmin=2 mm/h, k=1/1800 s⁻¹, PROVISIONAL), removal capped by available water. Both ledger-accounted (rain includes the microstore share; microstore appears on the output side of the identity — MODEL_ASSUMPTIONS §8).

## 9. Surface model

M2 adapter unchanged. M4 addition: the surface advance is sub-stepped at 1 s within each 5 s coupling stride (30 m cells at dt=5 s can trip the M2 wet-dry-front fail-fast on sharp convective gradients; 1 s sub-steps stay inside the documented clamp band — a configuration choice, not a solver change; `surface_substeps=1` reproduces M3 bitwise).

## 10. SWMM model

Exact-exchange fixture, datum-shifted +10 m onto the synthetic DEM's local datum (B08; constant shift preserves every slope/invert exactly — M3 tests at offset 0 verify the baseline). M4 variants: clean (C1 D=0.3, full-bore 97 L/s) and blocked (C1 D=0.12, capacity 8.4 L/s, ratio (0.4)^(8/3)=0.087). Fixture END_TIME extended to 6 h so the final coupling stride is yielded (see §Failures).

## 11. Exchange mechanism

M3's per-site laws, generalized to multiple sites (the generalization the M3 doc anticipated):

- **Capture (16 inlet cells):** each inlet is an independent signed head-driven orifice Q = Cd·Ao·√(2g·(η_s − H_d)) (Cd=0.6; Ao=0.002 m²/inlet, ASSUMED), clipped to ≥0, capped by the water physically available in the cell; suspended while the downstream vent floods (M3 rule).
- **Return (1 vent cell):** Q = Cd·Ao_v·√(2g·(H_d − η_v)) (Ao_v = 0.032 m², ASSUMED), capped by ST1's available volume; placed on the vent cell.
- Both legs may be active in the same stride (inlets keep admitting while the manhole spills) — the physical multi-site behaviour the single-point M3 driver could not represent. The M4 equivalence test proves the single-inlet configuration reproduces M3's results (Δ ≤ 1e-3 m³, float32 field representation).

**Fixture geometry (documented tuning, SYNTHETIC):** inlet cells sit on the basin rim at beds 22.10–22.30 m — ABOVE the basin's peak flood line (~22.05 m) — so the blocked-drainage equilibrium head (~22.0 m, set by capture throttling at the lowest inlet) rises above the vent ground (21.89 m) and the flood water surface, producing a real spill. Vent at the rim (95,79).

## 12. Mass ledger

M3 identities + microstore (RunLedger):

```
Surface:   rain − losses − surf_out − S2D + D2S + flood − ΔS_s − microstore = ε_s
Drainage:  ext + S2D − D2S − flood − outfall − ΔS_d = ε_d (~0 by engine identity)
Combined:  rain + ext − losses − surf_out − outfall − ΔS_s − ΔS_d − microstore = ε_t
```

Exchange appears with opposite signs in the two subsystem ledgers and cancels in the combined ledger (no double counting — asserted in M4-06). ΔS_d via SWMM's own per-stride identity (engine-exact; M3 §8). Dry runs pass within the documented M2 film bound. Results: heavy rel 1.6e-4, uniform 6.6e-6, spatial 1.3e-4 — all ≤ 1% gate.

## 13. Flood-depth calculation

h = max(0, η − z) directly from the solver state; no visualization transformations. Fail-fast on material negatives (M2 policy).

## 14. Flood extent definition

flooded = depth > ε with ε = 0.05 m (configurable, recorded in every snapshot and artifact; a visualization/demonstration threshold, explicitly NOT a safety threshold).

## 15. Scenario definitions

All five scenarios share every parameter except the labelled difference (zero: RainfallSpec(kind="zero"); uniform: 10 mm/h; spatial: convective 20 mm/h; heavy: provisional profile; heavy_blocked: identical heavy forcing + blocked INP). Seeded, deterministic, fingerprinted (configuration fingerprint hashes DEM bytes, INP bytes, all parameters, model version).

## 16. Tests (M4-01 … M4-15 + equivalence)

`tests/test_m4_coupled.py` — all pass. Full suite: **81/81** (M1 50 + M3 15 + M4 16).

| Test | Result | Key evidence |
|---|---|---|
| M4-01 zero rainfall | PASS | max depth = film scale (2e-6 m), no flooding, no exchange, dry-run ledger pass |
| M4-02 uniform rainfall | PASS | peak 0.330 m, S2D 639 m³, outfall 631 m³, losses+microstore accounted, rel 6.6e-6 |
| M4-03 spatial rainfall | PASS | convective cell: west > east at lead 15; heterogeneous depth; drainage participates; rel 1.2e-4 |
| M4-04 heavy rainfall | PASS | peak 0.471 m > uniform 0.319 m; area 1.792 km² ≥ 1.319 km² |
| M4-05 heavy + blockage | PASS | D2S 0 → 100.8 m³ (spill); S2D 496 → 190 m³ (capture throttled); outfall 488 → 73 m³; ST1 head 20.47 → 21.97 m (above vent ground 21.89 = surcharge); surface storage +406 m³; flooded area +3,000 m²; vent depth 0.021 → 0.028 m |
| M4-06 mass conservation | PASS | combined = surface residual (exchange cancels); ε_d ≈ 0; all terms ≤ 1% gate |
| M4-07 non-negative depth | PASS | every snapshot of every scenario ≥ −1e-12 m, finite |
| M4-08 snapshot determinism | PASS | leads 0,5,…,180 (37); UTC aware, monotonic; identical rerun stats |
| M4-09 scenario isolation | PASS | interleaved scenario does not perturb a rerun (bitwise) |
| M4-10 timestep halving | PASS | dt 10→5 s: storage drift 0.156% (≤5%), exchange drift 1.19% (≤20%), peak within 0.2% |
| M4-11 drainage sensitivity | PASS | Ao 0.002→0.004: S2D up, surface storage down (physical direction) |
| M4-12 output provenance | PASS | GeoTIFF snapshots with provenance tags + threshold; summary manifest; stable & sensitive fingerprints |
| M4-13 runtime | PASS | 3 h coupled run in ~18 s (≈600× real-time; cpu ~50 s; RSS ~270 MB) on the 2 vCPU sandbox |
| M4-14 invalid configuration | PASS | 13 invalid configs raise explicit CouplingError (incl. non-finite DEM, naive timestamps) |
| M4-15 reproducibility | PASS | two runs: bitwise-identical final depths, ledger, fingerprints |
| M3 equivalence | PASS | engine with 1 inlet reproduces the M3 spike driver (Δ ≤ 1e-3 m³, 0.015% of S2D) |

## 17. Results (canonical diagnostics run)

| Scenario | peak depth (m) | flooded area (km²) | S2D (m³) | D2S (m³) | outfall (m³) | max ST1 head (m) | rel. residual | mass gate |
|---|---|---|---|---|---|---|---|---|
| zero | 0.000 | 0.000 | 0.0 | 0.0 | 0.0 | 20.00 | — (film-bound rule) | pass |
| uniform | 0.330 | 1.319 | 638.9 | 0.0 | 631.3 | 20.25 | 6.6e-6 | pass |
| spatial | 0.504 | 2.770 | 754.2 | 0.0 | 745.8 | 20.29 | 1.2e-4 | pass |
| heavy | 0.471 | 1.792 | 495.7 | 0.0 | 488.3 | 20.47 | 1.6e-4 | pass |
| heavy_blocked | 0.471 | 1.795 | 189.8 | **100.8** | **73.1** | **21.97** | 1.6e-4 | pass |

The blockage story (identical forcing): the blocked drain pressurizes to ground level and stops accepting water during the peak (capture −62%), spills ~101 m³ back onto the street (D2S), and discharges 6.7× less at the outfall; the surface keeps +406 m³ and floods +3,000 m² more. Clean drainage never surcharges (head 20.47 < vent ground).

## 18. Runtime

Measured on the 2 vCPU / 3.9 GiB sandbox: ~18 s wall per 3-hour coupled run (≈600× real-time; zero 15 s, uniform 16.5 s, spatial 18.0 s, heavy 18.3 s, blocked 18.4 s; peak RSS ~270 MB; 2160 coupling strides × 5 surface sub-steps). No real-time claim is made from these numbers; M9/M10 will re-measure the forecast pipeline end-to-end.

## 19. Visual diagnostics

`scripts/run_m4_diagnostics.py` → `data/demo/m4/`: m4_dem.png, m4_rain_peak.png, m4_flood_clean_peak.png, m4_flood_blocked_peak.png, m4_diff_blocked_clean.png, m4_depth_timeline.png, m4_drainage_state.png, m4_summary.json, plus per-snapshot GeoTIFF artifacts (clean/, blocked/) with provenance tags. Every output is labelled SYNTHETIC / SIMULATED / PROVISIONAL. **Human visual review of these PNGs is required (M4 spec §30)** — the AI has no vision in this session; structural checks were done programmatically.

## 20. Scientific limitations

1. Synthetic fixture only — no real-terrain, real-network or real-event claims.
2. Rainfall hyetographs PROVISIONAL (D-016 review before M5).
3. Loss parameters (f0, fmin, k, microstore) PROVISIONAL literature values.
4. Orifice parameters (Cd, Ao, vent area) ASSUMED; real inlet/manhole geometry replaces them in the pilot.
5. Exchange mapped to storage nodes (exact volumes); the M4 pilot adapter will map to actual inlets/manholes (M3 doc §12).
6. h_init film creation ~0.02–0.04% of rainfall, quantified and reported in the residual (M2 doc §5.4), never absorbed.
7. Blocked fixture uses a single conduit blockage; pumps/gates/tide remain out of scope.
8. dt_c must be an integer number of seconds (pyswmm 2.1).
9. Flood extent threshold 0.05 m is a demonstration threshold, not a safety standard.

## 21. AI-generated risk review

| Risk | Evidence | Mitigation | Remaining uncertainty |
|---|---|---|---|
| 1. Does the coupling create water? | Combined residual +85.6 m³ (1.6e-4 rel) on heavy — surface-solver film creation, not the coupling (closed-domain control: +196 m³ with zero drainage) | Film mechanism documented (M2); residual reported; gate ≤1% | Film bound per wetting event is domain-specific |
| 2. Does the coupling destroy water? | ε_d ≈ 0; the negative-inlet extraction bug (destroyed water with no ledger entry) was FOUND by the equivalence test and fixed | Capture leg clipped ≥0; vent is the only reverse path; regression tests | None known |
| 3. Does SWMM storage readback corrupt total storage? | Readback kept as diagnostic only; ΔS_d via engine identity (M3 §8); SWMM flow routing error 0.0% every run | Fill-drain probe (M3); M4-06 asserts ε_d ≈ 0 | Engine-internal slot storage still opaque (bounded by ε_d) |
| 4. Does the surface model retain the M2 film bias? | Yes — quantified (−85.6 to −196 m³ ≈ 0.02–0.04% of rain), reported in the residual | Documented; never silently absorbed; gates unaffected | Accumulation across many wetting events |
| 5. Does drainage blockage actually affect the surface solution? | M4-05: D2S 0→101 m³, capture −62%, outfall ÷6.7, storage +406 m³, area +3,000 m², head above ground | Hard-gate test; fixture geometry documented | Magnitude is fixture-specific by design |
| 6. Can flood depth be wrong from mismatched elevation references? | Drainage datum shifted +10 m onto the DEM datum (B08); constant shift preserves slopes; vent ground read from the DEM itself | Single-datum discipline; documented in fixtures | Real-pilot datum audit still pending (B08) |
| 7. Can output interpolation make flooding look more precise than 30 m? | No interpolation anywhere; snapshots are native 30 m cells; extent threshold stored per artifact | Resolution labelling policy | — |
| 8. Can an AI-generated visualization hide an incorrect physical result? | PNGs carry provenance banners; mass gate and diagnostics are printed in the same summary; human visual review required (M4 §30) | Labelling + required human review | — |

## 22. Acceptance decision

```text
M4 PASS
```

All 26 M4 acceptance-gate items are satisfied (pipeline works end-to-end; zero/uniform/spatial/heavy/heavy+blockage pass; depth and extent generated; surcharge represented; blockage produces a measurable interpretable effect; surface/drainage/combined mass balances pass with no double counting; non-negative depths; timestep, isolation, reproducibility, failure handling, provenance, runtime, diagnostics, limitations, and the AI risk review are all recorded). The success criterion is met:

**Given a known rainfall field and known synthetic drainage conditions, UFNS can simulate the evolution of surface water while accounting for infiltration/losses, surface routing, drainage capture, drainage surcharge and resulting flood depth.**

M5 (scenario engine) may begin.
