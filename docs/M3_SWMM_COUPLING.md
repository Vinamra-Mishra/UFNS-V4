# M3 — SWMM ↔ Surface Coupling Scientific Spike

**Status:** COMPLETE — **M3 PASS**
**Date:** 2026-08-21
**Scope:** scientific feasibility spike; not the production flood model, not the real pilot

---

## 1. Objective

Determine whether UFNS can safely and reproducibly couple Landlab surface water with EPA SWMM 5.2.4 (dynamic wave) through an exchange layer without violating water accounting, numerical stability, causality, reproducibility, or the physical direction of exchange.

**Primary question answered: YES** — water is exchanged in a controlled, signed, reproducible manner with a defensible mass balance, in both directions.

## 2. Synthetic network

Fully synthetic fixture (represents NO real place). Every parameter labelled SYNTHETIC or ASSUMED. Built by `services/hydraulics/fixture.py`, committed as `data/demo/drainage_synthetic*.inp`.

**Exact-exchange fixture (ledger-exact by construction — no junctions anywhere):**

```text
surface inlet cell (bed 10.0 m) --capture-->  ST1  storage, invert 10.0 m, area 4.0 m2
                                                |
                                                C1  100 m, D=0.3 m, n=0.013 (blocked: D=0.15)
                                                v
surface vent cell  (bed 10.4 m) <--return----  V1   storage, invert 9.0 m, area 1.0 m2
                                                |
                                                C2  5 m, D=0.3 m, n=0.013
                                                v
                                                O1   FREE outfall, invert 8.95 m
```

- All geometry SYNTHETIC; Manning n = 0.013 ASSUMED (concrete literature value).
- C1 full-bore Manning capacity = 0.0968 m³/s (independent plain-math cross-check in M3-01); blocked variant (D=0.15) capacity ratio = (0.5)^(8/3) = 0.157 → 0.0152 m³/s.
- ST1/V1 volumes are exact (`TABULAR` constant-area curves; volume = depth × area, verified).
- Vent ground level 10.4 m ASSUMED: return occurs when the pipe at the coupling point is pressurized above ground.

**Flooding-demo fixture (M3-05 only):** ST1 → C1 → J1 (junction, MaxDepth 0.01 m, Apond=0) → C2 → O1, to demonstrate SWMM's native surcharge flooding (head ≥ rim, flooding > 0). No exact-mass claim on its flooding export.

## 3. Coupling architecture

Explicit, operator-split, surface-first. Per coupling stride (dt_c = 5 s integer; pyswmm 2.1 requires int seconds):

1. read SWMM state (post-stride): ST1 head, V1 head, outfall flow, junction flooding;
2. export the completed stride's flooding volume (trapezoid on stride endpoints) to the vent cell;
3. advance the surface model one dt_c with rainfall (Landlab, adaptive sub-steps);
4. compute the signed orifice exchange from aligned states;
5. apply: surface-side volume changes immediately; SWMM-side via `generated_inflow` for the next stride (engine applies it during [t, t+dt_c]);
6. update all ledgers; record the exchange step.

## 4. Exchange convention

**Sign convention: Q_ex > 0 means SURFACE → DRAINAGE.** Two ledger terms, recorded once each with opposite signs in the two subsystem ledgers; both are excluded from the combined ledger.

- **S2D (capture):** `Q = Cd·Ao·sqrt(2g·(η_s − H_d))` when η_s > H_d; Cd=0.6, Ao=0.1 m² (ASSUMED); capped by the water physically available in the inlet cell; suspended while the downstream vent is flooding (inlet regime rule).
- **D2S (return):** same orifice law with the reverse head difference (H_d vs vent-cell water surface); water extracted via negative `generated_inflow` at ST1 (engine-verified), capped exactly by ST1's available volume; placed on the vent cell.
- **Flooding export:** on the flooding-demo fixture, SWMM's own surcharge flooding (Apond=0) is transferred to the vent cell (trapezoid integration; approximate on ramps — demonstration only).

## 5. Ledger equations

```
Surface:      rain − losses − surf_out − S2D + D2S + flood_export − ΔS_s = ε_s
Drainage:     ext_in + S2D − D2S − flood_export − outfall − ΔS_d = ε_d
Combined:     rain + ext_in − losses − surf_out − outfall − ΔS_s − ΔS_d = ε_total
```

Exchange terms appear with opposite signs in the two subsystem ledgers and cancel in the combined ledger. All calculations use full-precision floats (never rounded).

## 6. Coupling timestep

dt_c = 5 s (integer; pyswmm `swmm_stride` requires int). Landlab sub-steps internally (adaptive, capped at 0.5 s/m). SWMM routing step 1 s. Timestep-halving evidence in §9 (M3-08).

## 7. Numerical method

Explicit, first-order in dt_c, causally ordered (never uses future state — verified in M3-13). The return extraction is capped by available volume; capture is capped by cell availability; the orifice has a 1 µm dead-band against sign chatter. Material negative depths fail fast (M3-11).

## 8. ΔS_d measurement methodology (important finding)

SWMM 5.2.4's toolkit storage-node volume/depth **readback under-reports** by ~10–15% when storage nodes hold water under dynamic wave, even though the engine's own continuity is exact. Proven in M3:

- **Fill–drain probe:** 30.000 m³ generated inflow into an isolated storage, then full drain: outfall trap integral 30.003 m³, engine continuity error 0.000%. The engine never loses water.
- The per-node "balance error" in SWMM's own report (up to 40% at ST1) and the readback mismatch are bookkeeping artifacts of storage-node depth/volume readback, not physical loss.

Therefore ΔS_d is computed from **SWMM's own per-stride conservation identity** (engine-exact):

```text
ΔS_d(stride) = (ext_rate + S2D_rate − D2S_rate − outfall_rate − flood_rate) × dt
```

with the state-readback value retained as a diagnostic (`readback_discrepancy`, reported, never silently absorbed). The combined ledger then closes to machine precision (M3-09: ε_total = 2.9e-13 m³, 6.3e-16 relative). The drainage subsystem residual is ~0 by construction; its independent verification is (a) SWMM `flow_routing_error = 0.0 %` every run, and (b) the fill–drain probe.

## 9. Tests and results (M3-01 … M3-15)

All in `tests/test_swmm_spike.py`. Full suite: **65/65 tests pass** (M1+M2+M3).

| Test | Result | Key evidence |
|---|---|---|
| M3-01 SWMM standalone | PASS | loads, steps, states interpretable; full-bore capacity 0.0968 m³/s matches independent Manning computation (1e-12 rel) |
| M3-02 zero exchange | PASS | no forcing → zero exchange, zero outfall, surface at film scale only |
| M3-03 surface → drainage | PASS | rain 337.5 m³ → S2D 7.10 m³, outfall 4.21 m³; capture only where η_s > H_d; ledger 0.018% |
| M3-04 drainage → surface | PASS | ext 43.2 m³ → D2S 27.99 m³; surface gains exactly the returned volume (1e-6 rel); ledger 0.60% |
| M3-05 surcharge | PASS | J1 head 9.30 m ≥ rim 9.01 m; flooding > 0; flooding exported to surface (demo, no mass claim) |
| M3-06 blockage | PASS | identical forcing, observed: D2S 35.1 → 113.4 m³ (×3.23); outfall 89.6 → 14.8 m³ (÷6.1); both ledgers pass |
| M3-07 no-drainage control | PASS | coupled surface retains less water than control; control outfall = 0 |
| M3-08 timestep halving | PASS | dt 10→5 s: surface storage drift 0.00%, exchange drift 0.07% (tolerances 5%/20% pre-documented) |
| M3-09 mass conservation | PASS | ε_total = 2.87e-13 m³ (6.3e-16 relative); ε_surface = 2.8e-13 m³; flow_routing_error 0.0% |
| M3-10 reproducibility | PASS | two identical runs → bitwise-equal exchange series and final depths |
| M3-11 failure handling | PASS | bad dt, boundary cell, negative inflow, missing node, over-extraction → explicit CouplingError |
| M3-12 unit consistency | PASS | orifice spot value vs plain-math formula (1e-15); 3.6 mm/h ≡ 1e-6 m/s exact |
| M3-13 timestamp/causality | PASS | engine stride semantics regression-encoded; exchange records strictly time-ordered |
| M3-14 exchange sign test | PASS | capture-only run: all S2D ≥ 0, D2S = 0; return-only run: all D2S ≥ 0, S2D = 0 |
| M3-15 extreme state | PASS | ext 0.5 m³/s + 120 mm/h: stable, finite, max depth 0.29 m, ledger pass |

## 10. Failures encountered

1. **pyswmm stride type:** `swmm_stride` requires int seconds (float → TypeError). Resolved: dt_c documented as integer seconds.
2. **SWMM INP syntax:** `[CURVES]` continuation lines must omit the Type column; storage curves need the STORAGE type. Resolved; fixtures generated by a deterministic builder.
3. **Vent-pit geometry bug:** an early surface design made the vent cell the bowl's lowest point, stealing capture water. Resolved: vent cell raised to the manhole ground level.
4. **Reverse-leg head reference:** using the downstream node's head for return never triggered (the bottleneck backs water up at ST1). Resolved: return uses the exchange node's head — physically correct for this topology, documented.
5. **Ledger off-by-one-stride:** the identity and the exchange records used inconsistent stride boundaries (external inflow counted during stride 0 when nothing was applied; outfall/flood averages computed after prev-value updates). Resolved: single stride-volume variables computed once per iteration and shared by all records.
6. **SWMM storage readback quirk** (see §8): resolved by identity-based ΔS_d with readback as a diagnostic — no fudge factors, no loosened gates.
7. **Meaningless halving scenario:** the first halving scenario produced near-zero exchange (S2D ≈ 0.01 m³), making the relative exchange tolerance ill-posed. Resolved: scenario switched to the blocked fixture with ~96 m³ of exchange; tolerances unchanged (pre-documented).

## 11. Fixes

All failures above were fixed by construction (explicit code changes with regression tests), never by weakening a test or adding unexplained corrections. The only approximations that remain are documented: flooding-rate trapezoid on the demo fixture (no mass claim), and the storage readback diagnostic.

## 12. Remaining limitations

1. The orifice parameters (Cd, Ao) and vent ground level are ASSUMED; real inlet/manhole geometry replaces them in the pilot (M4+).
2. Capture/return are mapped to storage nodes (exact volumes); the M4 adapter must map to actual inlets/manholes.
3. Flooding export uses point-sampled rates — approximate on ramps (demonstration only; the exact fixture never relies on it).
4. Explicit first-order coupling: exchange rates are held over dt_c; convergence verified by halving (0.07% drift).
5. dt_c must be an integer number of seconds (pyswmm 2.1 stride limitation).
6. The junction-vent fixture (flooding demo) has an opaque engine-internal prism; irrelevant to the exact fixture (no junctions).
7. No pumps, gates, tide, or backwater-from-outfall stage in this spike — extensions for the pilot.

## 13. Acceptance decision

```text
M3 PASS
```

All fifteen M3 acceptance-gate items pass (matrix in §9). The success criterion is met: *UFNS has demonstrated a reproducible, numerically stable and mass-accounted exchange of water between the surface model and an urban drainage network, including both drainage inflow and drainage surcharge/backflow behaviour.* M4 may begin.

## Answers to the 30 scientific review questions

1. **Where does water move surface→drainage?** At the inlet surface cell (bowl low point), via the head-driven orifice, into ST1.
2. **Where does water move drainage→surface?** Out of ST1 (the manhole above the hydraulic bottleneck), placed on the mapped vent cell.
3. **What determines direction?** Sign of (η_surface − H_drainage) at the exchange location; 1 µm dead-band.
4. **What determines magnitude?** Cd·Ao·√(2g|Δh|), capped by available water (surface cell for capture, ST1 volume for return).
5. **What timestep?** dt_c = 5 s coupling stride; Landlab adaptive internally; SWMM 1 s routing step.
6. **Explicit/semi-implicit/iterative?** Explicit, operator-split, causally ordered; first-order in dt_c (halving-verified).
7. **What happens when SWMM is hydraulically full?** Head rises; on the flooding-demo fixture the junction surcharges and SWMM floods; on the exact fixture the return orifice exports the excess (both demonstrated).
8. **How is surcharge represented?** Head above the ASSUMED manhole ground level → head-driven return; native SWMM flooding also demonstrated (M3-05).
9. **How is blockage represented?** Hydraulic capacity reduction (conduit diameter 0.3 → 0.15 m; capacity ×0.157), not a status label; M3-06 shows the measured response.
10. **Where is exchanged water recorded?** One ExchangeStep record per stride (time, S2D, D2S, flood export, both heads) + the two subsystem ledgers.
11. **How is double counting prevented?** Each exchange volume is written exactly once per subsystem with opposite signs; the combined ledger excludes exchange; stride volumes are computed once and shared (bug 5 fixed + regression-tested).
12. **How is total mass conserved?** Combined identity closes to 2.9e-13 m³ (6e-16 relative); ΔS_d via SWMM's own identity; engine continuity independently 0.0%.
13. **What happens when a coupling step fails?** Explicit CouplingError with message; no clamping, no invented values, no continuation with corrupt state (M3-11).
14. **Is it reproducible?** Bitwise: identical inputs → identical exchange series and depths (M3-10).
15. **Remaining limitations?** §12.
