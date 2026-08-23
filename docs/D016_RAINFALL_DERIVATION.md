# D-016 — Scientific Rainfall Derivation (Scenario Rainfall Profiles)

**Decision ID:** D-016 / B03
**Status:** PREPARED — HUMAN REVIEW REQUIRED (scientifically prepared; NOT approved)
**Date:** 2026-08-21
**Option:** Option A — published WB/Kolkata IDF parameters with hydrologist sign-off

> Every statement below is labelled with one of:
> **SOURCE FACT** (verbatim from a cited source), **DERIVED VALUE** (computed from
> source facts by a documented formula), **ASSUMPTION** (an explicitly chosen,
> non-source parameter), **AI INFERENCE** (a reasoned recommendation requiring a
> human decision), or **HUMAN DECISION** (an action only a human can take).

---

## 1. Decision ID

- **ID:** D-016 (also tracked as B03 "demo hyetograph derivation" in Phase 0).
- **Decision:** Establish a traceable scientific basis for the M5 scenario rainfall
  profiles (P_NORMAL / P_HEAVY / P_EXTREME), replacing the provisional
  "illustrative" storm totals (20 / 45 / 90 mm per 3 h) with published-IDF-derived
  values once a hydrologist approves the derivation.

## 2. Decision Objective

Resolve D-016 using **Option A** from the project review: *"Published WB/Kolkata
IDF parameters with hydrologist/scientific sign-off."* The goal is a
**deterministic, source-traceable** derivation of the three 3-hour scenario
hyetographs, with every parameter, formula, unit, assumption and limitation
recorded — without fabricating any human approval.

## 3. Existing Provisional Profile

**SOURCE FACT** (repository state at M5): the profiles shipped at M5 are built by
the alternating-block method (Chow, Maidment & Mays 1988, ch. 14) from a
provisional depth-duration curve `P(d) = P60·(d/60)^0.4` anchored to totals:

| Profile | Total (mm / 3 h) | Mean (mm/h) | Status |
|---|---|---|---|
| P_NORMAL | 20 | ~6.7 | PROVISIONAL |
| P_HEAVY | 45 | ~15.0 | PROVISIONAL |
| P_EXTREME | 90 | ~30.0 | PROVISIONAL |

**SOURCE FACT**: these totals were explicitly documented in the code as
"illustrative fixture-scale design storms … NOT calibrated to any gauge record,
return period, or IDF curve." They establish software behaviour only; they do not
establish that the depths are appropriate for the real study area.

## 4. Source Selection

**SOURCE FACT** — selected published, peer-reviewed source:

> Kumar, A., & Remesan, R. (2026). *Integrating Revised Intensity-Duration-Frequency
> Curves with Coupled 1D-2D MIKE+ Modelling for Urban Flood Hazard Assessment Under
> CMIP6 Projections.* Water Resources Management, 40(3), 115.
> DOI: [10.1007/s11269-026-04514-5](https://doi.org/10.1007/s11269-026-04514-5)

**SOURCE FACT** — this study develops observed (1980–2023) IDF curves for the
**Bagjola Canal basin, Kolkata Metropolitan Area** from the **IMD Alipur gauge
station**, using the Generalized Extreme Value (GEV) distribution (selected via
chi-square, Kolmogorov–Smirnov, and Anderson–Darling goodness-of-fit tests), and
applies 2-, 5-, and 10-year return periods following CPHEEO (2019) urban-drainage
guidelines.

**AI INFERENCE** — this is the most appropriate published IDF basis available
because (a) it is geographically specific to the pilot region (West Bengal /
Kolkata), (b) it is peer-reviewed and recent (2026), and (c) it uses the return
periods (2/5/10-year) that Indian urban-drainage design guidance (CPHEEO 2019)
uses. It was already identified in-repo as the candidate source.

## 5. Source Credibility

**SOURCE FACT**:
- Journal: *Water Resources Management* (Springer), peer-reviewed, indexed.
- Authors: Aman Kumar and Renji Remesan, School of Water Resources, IIT Kharagpur.
- Published 12 February 2026.
- Data: IMD Alipur gauge, 1980–2023 (44 years), analysed with GEV (L-moments).

**AI INFERENCE** — peer-reviewed, institution-affiliated, data-period adequate
(>40 years). Limitation: the article body is subscription-access; the intensity
values below were transcribed from the publicly visible abstract/full-text
preview and must be re-verified against the final published PDF before any
operational adoption (recorded as a HUMAN DECISION item).

## 6. Geographic Applicability

**SOURCE FACT** — the IDF applies to the **Bagjola Canal basin, Kolkata
Metropolitan Area** (a tidally influenced drainage basin in West Bengal).

**AI INFERENCE / HUMAN DECISION** — this is a *candidate-pilot-region* IDF, NOT a
statement that the current **synthetic 134×134 @30 m UFNS fixture** represents that
basin. The synthetic fixture geometry remains SYNTHETIC. The rainfall magnitudes
are transferable to the pilot region to the extent the IDF represents it; the
fixture's terrain/drainage geometry are not. This distinction is preserved
everywhere in the UI and docs.

## 7. IDF / Depth-Duration Data

**SOURCE FACT** — published GEV rainfall intensities (mm/h) for the 2-year and
100-year return periods (Bagjola Canal basin, Alipur gauge, 1980–2023):

| Duration (h) | 2-yr intensity (mm/h) | 100-yr intensity (mm/h) |
|---|---|---|
| 1 | 45.05 | 105.20 |
| 2 | 28.40 | 66.27 |
| 6 | 18.05 | 45.24 |
| 12 | 12.15 | 28.70 |
| 24 | 7.90 | 18.22 |
| 48 | 5.30 | 12.03 |

**SOURCE FACT** — the source also reports 2-h intensities (28.40 → 66.27 mm/h
between 2-yr and 100-yr) and that the GEV 1-h intensity ranges 45.05–105.20 mm/h
(2-yr to 100-yr). Only the 2-yr and 100-yr endpoints are tabulated in the
accessible text; intermediate return periods (5, 10-year) are presented graphically
in the source and are derived here by a documented scaling (Section 9).

## 8. Scenario Mapping

**HUMAN DECISION (required) / AI INFERENCE (recommended)** — the demo labels are
NOT automatically equated to return periods. The recommended mapping follows the
return periods the source itself uses for urban-drainage design (CPHEEO 2019):

| Scenario label | Recommended return period | Rationale |
|---|---|---|
| NORMAL | 2-year | frequent design storm (minor drainage) |
| HEAVY | 5-year | intermediate design storm (minor drainage) |
| EXTREME | 10-year | major drainage design storm |

**AI INFERENCE** — "NORMAL" here means a *2-year design storm* (an annual-maximum
statistical extreme), which is materially more intense than a "typical moderate
shower". This is an intentional semantic change from the old provisional labels and
is exactly why the mapping requires human sign-off.

## 9. Mathematical Derivation

### 9.1 Depth conversion

**DERIVED VALUE** — depth from intensity: `D(d, T) = i(d, T) · d` (mm).

### 9.2 Return-period scaling (Sherman 1931 form)

**DERIVED VALUE** — between the two published anchors (2-yr, 100-yr):

```
i(d, T) = i(d, 2) · (T/2)^α(d)
α(d)    = ln( i(d,100) / i(d,2) ) / ln(50)
```

Per-duration exponents (DERIVED VALUE):

| Duration (h) | α(d) |
|---|---|
| 1 | 0.21679 |
| 2 | 0.21660 |
| 6 | 0.23487 |
| 12 | 0.21972 |
| 24 | 0.21361 |
| 48 | 0.20953 |

### 9.3 Duration interpolation to 3 hours

**DERIVED VALUE** — the 3-hour scenario duration lies between the published 2-h and
6-h nodes; depth is interpolated by log-log (power-law) interpolation:

```
D(3h, T) = exp( ln(D2) + (ln(D6) − ln(D2)) · (ln 3 − ln 2)/(ln 6 − ln 2) )
```

### 9.4 Derived 3-hour depths

**DERIVED VALUE** (unrounded → rounded):

| Scenario | T (yr) | D(3h) unrounded (mm) | D(3h) rounded (mm) | Mean intensity (mm/h) |
|---|---|---|---|---|
| NORMAL | 2 | 72.0761 | **72.08** | 24.03 |
| HEAVY | 5 | 88.4442 | **88.44** | 29.48 |
| EXTREME | 10 | 103.2531 | **103.25** | 34.42 |

**DERIVED VALUE (rounding rule)** — totals are rounded to 2 decimals (0.01 mm);
the alternating-block hyetograph is then normalised to the rounded total so the
15-minute series sums exactly to the stated total.

## 10. 15-minute Hyetograph Construction

**ASSUMPTION / DERIVED VALUE** — the alternating-block method (Chow et al. 1988)
is retained: the largest depth increment is placed at storm centre (interval 7 of
12) and the remaining increments alternate outward. The intra-storm shape exponent
`0.4` is retained as an **ASSUMPTION** governing only the temporal shape (peakiness);
the total depth is fixed by Section 9 and is unaffected by the shape exponent.

**DERIVED VALUE** — 15-minute intensities (mm/h), one per interval:

| Interval | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| NORMAL (72.08 mm) | 34.09 | 20.20 | 15.37 | 12.75 | 11.06 | 9.86 | **106.71** | 10.42 | 11.83 | 13.90 | 17.35 | 24.79 |
| HEAVY (88.44 mm) | 41.83 | 24.78 | 18.86 | 15.64 | 13.57 | 12.10 | **130.93** | 12.78 | 14.51 | 17.05 | 21.28 | 30.42 |
| EXTREME (103.25 mm) | 48.84 | 28.93 | 22.01 | 18.26 | 15.85 | 14.13 | **152.85** | 14.92 | 16.94 | 19.91 | 24.85 | 35.51 |

**DERIVED VALUE** — 15-minute depth increments (mm), sum = total:

| Interval | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | Σ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| NORMAL | 8.524 | 5.049 | 3.842 | 3.188 | 2.765 | 2.466 | **26.677** | 2.604 | 2.957 | 3.474 | 4.336 | 6.198 | 72.08 |
| HEAVY | 10.458 | 6.195 | 4.714 | 3.911 | 3.393 | 3.025 | **32.732** | 3.195 | 3.628 | 4.263 | 5.321 | 7.605 | 88.44 |
| EXTREME | 12.210 | 7.232 | 5.503 | 4.566 | 3.961 | 3.532 | **38.214** | 3.730 | 4.235 | 4.977 | 6.212 | 8.878 | 103.25 |

## 11. Final Rainfall Totals

**DERIVED VALUE** (recommended, subject to human approval):

| Scenario | Total (mm / 3 h) | Peak 15-min intensity (mm/h) |
|---|---|---|
| NORMAL | 72.08 | 106.71 |
| HEAVY | 88.44 | 130.93 |
| EXTREME | 103.25 | 152.85 |

## 12. Unit Conversions

**SOURCE FACT / DERIVED VALUE** — all source intensities are mm/h; depths are mm.

- depth (mm) = intensity (mm/h) × duration (h).
- 15-min interval depth (mm) = intensity (mm/h) × 0.25 h.
- No further unit conversion is required (the UFNS solver consumes mm/h intensities
  and converts internally to m/s, unchanged from M1–M5).

## 13. Assumptions

**ASSUMPTION** (explicit, each labelled):
1. Return-period scaling between the published 2-yr and 100-yr anchors follows the
   Sherman (1931) power form with the per-duration exponents in §9.2.
2. The 3-hour depth is obtained by log-log interpolation between the published 2-h
   and 6-h nodes (§9.3).
3. Intra-storm temporal shape uses the alternating-block method with exponent 0.4
   (Chow 1988) — a shape assumption only, not affecting totals.
4. The recommended scenario→return-period mapping (§8) is a design choice pending
   human approval.
5. The published intensities are transcribed from the accessible text/preview and
   must be re-verified against the final PDF (HUMAN DECISION item).

## 14. Limitations

1. **Return periods ≥ 2 years only** — the source is an annual-maxima analysis;
   sub-2-year ("typical" rainfall) is out of scope. "NORMAL" therefore means a
   2-year design storm, not a common shower.
2. **Single gauge** — Alipur station; spatial variability across the basin is not
   captured by these point IDF values.
3. **Stationary climate** — the observed (1980–2023) curve is used; the source's
   climate-adjusted (CMIP6 SSP) curves are intentionally NOT used for these
   baseline scenarios.
4. **Synthetic fixture** — the derived rainfall is applied to the synthetic 134×134
   fixture, which represents no real location.
5. **Duration interpolation** — 3 h is interpolated, not directly tabulated.
6. **No validation against an observed flood event** — the totals are design-storm
   magnitudes, not calibrated to a measured flood.

## 15. Deterministic Fingerprint

**DERIVED VALUE** — the derivation is deterministic. `services/rainfall/idf.py`
computes a SHA-256 fingerprint over the source anchors, duration nodes, mapping,
interval/duration and shape exponent:

```
derivation_fingerprint() = af90bd1bd82b13acc442c883922d853d6e93df18cea91923cd54015eb805682c
```

Same inputs → same depths → same hyetographs → same fingerprint. Verified by
`tests/test_d016_rainfall.py` (D016-04, D016-08).

## 16. Comparison with Old Provisional Values

**DERIVED VALUE vs SOURCE FACT**:

| Scenario | Old provisional (mm) | Source-derived (mm) | Change |
|---|---|---|---|
| NORMAL | 20 | 72.08 | +260% |
| HEAVY | 45 | 88.44 | +97% |
| EXTREME | 90 | 103.25 | +15% |

**AI INFERENCE** — the old "NORMAL = 20 mm" was a *moderate-shower* magnitude, not
a design storm; the source-derived 2-year storm is much larger. The old totals do
not correspond to any documented return period and should be replaced by the
source-derived values **upon human approval**. The values have **not** been forced
to fit the old numbers.

**HUMAN DECISION** — the live M5 profiles are intentionally **not** changed in this
session: (a) D-016 is gated on human approval; (b) flipping the totals would break
the M4-heavy regression guard (`test_m5_m4_heavy_baseline_reproduced` is tied to the
45 mm heavy baseline) and would require regenerating all precomputed results and
diagnostics; (c) the magnitude change for NORMAL/HEAVY warrants explicit human
review of the mapping before any re-run. The exact flip (a one-line change to
`PROFILE_DEFS` totals, or wiring `services/rainfall/idf.py` into
`build_profile_record`) is documented as the approval action.

## 17. Scientific Recommendation

**AI INFERENCE** — **PREPARE FOR APPROVAL**. The evidence is strong (peer-reviewed,
geographically specific, adequate record length, deterministic reproduction of
published anchors). Recommended action on human sign-off:
1. Approve the scenario→return-period mapping (§8).
2. Approve the derived 3-hour totals (72.08 / 88.44 / 103.25 mm).
3. Flip `PROFILE_DEFS` totals to the source-derived values and re-run the M5 suite,
   updating the M4-heavy regression guard to compare at equal rainfall.

## 18. Human Approval Requirement

**HUMAN DECISION** — a hydrologist (or authorized scientific reviewer) must approve:
- the source choice and transcription,
- the return-period → scenario-label mapping,
- the derived totals and hyetographs.

Until that approval is recorded in the repository, D-016 remains **PREPARED — HUMAN
REVIEW REQUIRED** and every profile stays **PROVISIONAL / NOT FOR OPERATIONAL USE**.
**No human approval is fabricated.**

## 19. Exact Acceptance Criteria

**HUMAN DECISION** — D-016 becomes APPROVED only when an actual human reviewer
records (in this file or `PHASE0_APPROVAL.md`-style matrix) that:
1. The source (Kumar & Remesan 2026) is correct and applicable to the pilot region.
2. The scenario→return-period mapping is accepted.
3. The derived totals (72.08 / 88.44 / 103.25 mm) are accepted.
4. The transcribed intensity table matches the final published text.

On approval: profile statuses flip PROVISIONAL → APPROVED; M5 acceptance becomes
PASS; the M5 suite is re-run with the approved totals and the regression baseline
updated with documentation.

## 20. Decision Status

```text
D-016:  PREPARED — HUMAN REVIEW REQUIRED
M5:     CONDITIONAL PASS (unchanged)
```

- Evidence strength: **strong** (published, peer-reviewed, region-specific).
- Human review: **required and outstanding** (not fabricated).
- Live profile status: **PROVISIONAL** (unchanged; not flipped without approval).

---

### Provenance traceability (source → derivation → data)

```text
SOURCE          Kumar & Remesan 2026, Water Resources Management 40(3):115
                (DOI 10.1007/s11269-026-04514-5)
  └─ FACT        GEV intensities 2-yr / 100-yr at 1/2/6/12/24/48 h (Alipur, 1980-2023)
DERIVATION      services/rainfall/idf.py (deterministic, fingerprinted)
  └─ VALUE       3-hour depths 72.08 / 88.44 / 103.25 mm (2/5/10-yr)
  └─ VALUE       12×15-min alternating-block hyetographs
DATA            candidate M5 profile totals (PROVISIONAL until approved)
```
