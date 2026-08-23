# SIH26085 (UFNS) — Phase 0 Approval Matrix

**Status:** APPROVED — human team granted implementation approval on 2026-08-21.
**Created:** 2026-08-21 (independent Phase 0 audit; see [`PHASE0_AUDIT.md`](PHASE0_AUDIT.md))
**Authority record:** [`IMPLEMENTATION_SPEC.md`](IMPLEMENTATION_SPEC.md) §0 (human decision table) and §2 (approved architecture). Implementation baseline follows that specification; approved decisions may not be replaced without explicit human approval.

## How statuses were recorded

Every status below was set by the **human team's approval record** (the decision table in `IMPLEMENTATION_SPEC.md` §0, dated 2026-08-21), not by the AI. "APPROVED WITH CONDITIONS" marks items the human team kept but explicitly made conditional on a defined audit/verification step.

## Matrix

| Item | Status | Date | Reviewer | Decision reference |
|---|---|---|---|---|
| Architecture | APPROVED | 2026-08-21 | Human team | IMPLEMENTATION_SPEC §2 (modular monolith; no unnecessary microservices) |
| Data sources | APPROVED WITH CONDITIONS | 2026-08-21 | Human team | Spec §4 B02: WB AMRUT audit required before pilot acceptance; synthetic fallback approved |
| Data policy | APPROVED WITH CONDITIONS | 2026-08-21 | Human team | Spec §3 (labels, no fake science, security §22); specific dataset licences verified during audits |
| Pilot area | APPROVED WITH CONDITIONS | 2026-08-21 | Human team | Spec §2/§4: West Bengal AMRUT candidate kept, subject to the defined data audit |
| Spatial resolution | APPROVED | 2026-08-21 | Human team | Spec §2/§3.3: 30 m / ~4×4 km for physics; no artificial upsampling |
| Temporal resolution | APPROVED | 2026-08-21 | Human team | Spec §12/M6: 15-min forcing, 5-min outputs, timeline NOW/+15/+30/+60/+120/+180 |
| Rainfall methodology | APPROVED | 2026-08-21 | Human team | Spec §2/§16: baseline first, strengthen nowcast layer; ML only on measurable benefit |
| Runoff methodology | APPROVED | 2026-08-21 | Human team | Spec §2 "Keep": microstore + Horton with ledger accounting (Phase 0 baseline) |
| Surface routing | APPROVED | 2026-08-21 | Human team | Spec §2/§4 B06: Landlab OverlandFlow + explicit spatial-rainfall adapter |
| Drainage model | APPROVED | 2026-08-21 | Human team | Spec §2: EPA SWMM Dynamic Wave; real+assumed+synthetic parameter policy |
| Hydraulic methodology | APPROVED | 2026-08-21 | Human team | Spec §4 B05: two-way coupling must be experimentally demonstrated |
| Validation methodology | APPROVED | 2026-08-21 | Human team | Spec §2 "Keep" (physics + conservation + benchmarks + scenario tests); M11 |
| Demo strategy | APPROVED | 2026-08-21 | Human team | Spec §13/M5: 4 scenarios, deterministic and reproducible; scenario 4 = primary coupling demo |
| Computational budget | APPROVED | 2026-08-21 | Human team | Spec §2 "Keep for physics"; one-worker student-scale profile unchanged |

## Decision-log items resolved by the human approval

- **D-016 (design-storm derivation):** APPROVED — spec §4 B03 requires a documented derivation for every demo hyetograph.
- **D-017 (live-mode gate):** APPROVED — spec §2/§15: live data is a later phase; no silent fallback to synthetic data.
- **D-018 (DEM licensing posture):** APPROVED IN DEFAULT FORM — Copernicus DEM primary; FABDEM remains internal-only (no redistribution) unless the team decides otherwise later.
- **D-019 (Landlab spatial-rainfall adapter):** APPROVED — spec §4 B06 + M2 mandate the adapter and its tests.
- D-001…D-015: APPROVED via the umbrella entry D-020 (see `DECISIONS.md`).

## Phase 0 status

Phase 0 is **CLOSED**. Implementation is **APPROVED** under `IMPLEMENTATION_SPEC.md`. The audit verdict (CONDITIONALLY READY) is superseded by the human approval; the conditions became the milestone gates (M2/M3 spikes, WB AMRUT audit, D-016 derivation) recorded in the specification.
