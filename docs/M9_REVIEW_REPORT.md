# M9 FINAL ENGINEERING REPORT

> Scope note: this session received a set of four CodeRabbit findings to verify and
> resolve against the current `main` M8 baseline (`5f475e5`). It did **not** implement
> the full M9 depth+velocity milestone (Landlab OverlandFlow velocity extraction,
> hazard bands, API, dashboard, routing policy). The M9 code work remains ahead of this
> report. This report records the four findings, their verification, the resulting
> changes, and the authoritative test evidence.

## 1. Verdict

**CONDITIONAL PASS**

The four requested findings were verified as still-valid, fixed, and validated with
tests. No M1–M8 code path was modified. The full suite currently reports **328 passed /
2 failed**, and the two failures are **pre-existing, time-dependent baseline defects**
that were present at the checkout **before** any change was made (identical two tests
fail on the untouched checkout). They are not regressions introduced by this work (see
§6, §7).

## 2. What Was Implemented

| Finding | File | Change |
|---|---|---|
| 1. EN DASH `0–60 min` + targeted `noqa` | `tests/test_m8_nowcast.py` | Kept the EN DASH literal; added `# noqa: RUF003` to the comment line and `# noqa: RUF001` to the string-literal assertion line. HTML assertions and expected strings untouched. |
| 2. Ruff F821 in `_stale_observation` | `tests/test_m8_nowcast.py` | Added a module-scope `TYPE_CHECKING` import of `RainfallObservation` so the `-> "RainfallObservation"` return annotation resolves; the runtime-local import is preserved (the method still constructs an instance at runtime). |
| 3. Stale M8 capability statement | `README.md` | Moved the persistence baseline out of the `not implemented / not claimed` list; the `implemented` list already carries `nowcast baseline (persistence; NOWCAST-PERSISTENCE-V1)`. The `no advection / no intensity evolution / no ML` limitation is retained as a stated limitation rather than as a claim that persistence is unimplemented. |
| 4. Test-count reconciliation | `docs/AI_REVIEW.md` | Reconcile the 14-test discrepancy: added the omitted `D-016 derivation: 13 passed` row to the Test Status block, corrected the M6 count `17 → 18`, and updated the M7 Executive Summary figure `153/153 → 154/154 (M1–M7 cumulative)`. |

No other files were modified. No scientific code paths, routing policy, cache, or
hydrology were touched.

## 3. Scientific Verification

This work is documentation/tests-only; it changed **no** scientific computation. The
existing M8 velocity baseline (`v = q/h`, `q` unit-width discharge in m²/s, zero/
near-zero/negative/invalid depth handling) is unchanged. No new scientific claim is made.

## 4. Hazard Model

No hazard model was changed or added. The existing M8 velocity hazard-band and B13
provisional governance (`B13-DEMO-V1`, `approved=false`) remain exactly as they were.

## 5. Routing

No velocity-aware routing was implemented (not in scope of these findings). M7 routing
semantics and `NO_SAFE_ROUTE` behaviour are unchanged.

## 6. Test Results

Authoritative count from actual `pytest` execution on the `arena/01a029cc-ufns` checkout:

```text
Total:    330
Passed:   328
Failed:   2
Skipped:  0
```

Post-collection per-file breakdown (used for the doc reconciliation) —
as-of-M9 historical snapshot (176 M8 / 330 total); as of M9.1.1 the full
suite is 418 tests, see `docs/AI_REVIEW.md` §10:

```text
test_bundle.py: 4            test_m7_api.py: 9
test_contracts.py: 7         test_m7_road_impact.py: 8
test_crs.py: 4               test_m7_routing.py: 7
test_d016_rainfall.py: 13    test_m8_nowcast.py: 176
test_dem_fixture.py: 5       test_rainfall.py: 6
test_landlab_spike.py: 9     test_reproducibility.py: 3
test_ledger.py: 6            test_swmm_spike.py: 15
test_m4_coupled.py: 16       test_time.py: 6
test_m5_scenarios.py: 18
test_m6_dashboard.py: 18
```

Milestone grouping: **M1–M7 = 154** (50 M1/M2 unit + 31 M3/M4 integration + 18 M5 +
13 D-016 + 18 M6 + 24 M7) and **M8 = 176**, for a total of **330**.

The two failures are:

- `tests/test_m8_nowcast.py::TestRainfallAPIModule::test_fetch_observation_at_returns_available`
- `tests/test_m8_nowcast.py::TestAppEndpointsExtended::test_rainfall_observation_valid_time_returns_200`

Both hardcode `2026-08-22T12:00:00Z` and assert `AVAILABLE`. They fail whenever the run
clock is more than ~120 minutes after 12:00 UTC (the quality service marks a >120-minute
observation `STALE` → `UNAVAILABLE`). Because the sandbox clock was ~14:19 UTC at run
time, these two tests deterministically fail on that absolute timestamp. This is a
**pre-existing time-dependent test-quality defect**, not a code or scientific issue, and
not a regression: it reproduces identically on the untouched checkout.

## 7. M8 Regression Gate

Each gate item reflects the state after the four findings were applied. Nothing in the
M8 implementation was modified.

- Health endpoint: **PASS** (untouched)
- Invalid observation handling: **PASS** (untouched; the two failures are the inverse — a
  correct stale `UNAVAILABLE` that a hardcoded test asserts should be `AVAILABLE`)
- Cache integration: **PASS** (untouched)
- Cache immutability: **PASS** (untouched)
- Cache thread safety: **PASS** (untouched)
- Lead-time invariant: **PASS** (untouched)
- Complete fingerprints: **PASS** (untouched)
- Fixture timestamp clamping: **PASS** (untouched)
- Frontend lead-time fix: **PASS** (the assertion that guards `ncs.lead_times_minutes` and
  the EN-DASH `0–60 min` fallback is now lint-clean and test-green)
- NOT_REAL_TIME boundary: **PASS** (untouched)
- UNAVAILABLE contract: **PASS** (untouched)
- Velocity q/h baseline: **PASS** (untouched)
- Hazard-band baseline: **PASS** (untouched)
- B13 governance: **PASS** (untouched, `approved=false`)
- M1–M7 compatibility: **PASS** for the changed files (documentation-only plus two
  no-op/lint test changes; the M1–M7 code paths are unmodified)

## 8. CodeRabbit Findings

1. **EN DASH `0–60 min` with `noqa RUF003/RUF001`** — **Fixed.** Verified with
   `.venv/bin/ruff check tests/test_m8_nowcast.py --select F821,RUF001,RUF003` (now
   clean). The literal retains `–` (U+2013); `# noqa: RUF003` on the comment and
   `# noqa: RUF001` on the string-literal assertion suppress the ambiguous-unicode
   rules while the HTML assertions/strings are unchanged.
2. **F821 `RainfallObservation` in `_stale_observation` return annotation** — **Fixed.**
   Added a module-scope `if TYPE_CHECKING: from services.nowcast.providers import
   RainfallObservation`. The runtime-local import remains inside the method (needed to
   construct the object). Verified with Ruff (`--select F821` clean); `TestInvalidObservationNotAvailable`
   (5 tests) passes.
3. **README stale M8 capability statement** — **Fixed.** Persistence baseline removed
   from `not implemented / not claimed`; API and dashboard are already listed under
   `implemented`; the no-advection/no-ML limitation is preserved as a limitation.
4. **AI_REVIEW test-count reconciliation** — **Fixed.** Added the omitted D-016 row and
   corrected M6 `17 → 18`, making the Test Status block sum to 330 and matching the
   authoritative per-file counts; updated the M7 summary to `154/154 (M1–M7 cumulative)`.

**Intentionally skipped:** the two pre-existing time-dependent failures described in §6.
They are not among the findings, were present before this work, and changing their
hardcoded timestamps would be a test change outside the requested scope. Recording them
here as a known baseline defect; recommend a follow-up to make those assertions relative
to `datetime.now(timezone.utc)`.

## 9. Scientific Limitations

Unchanged and still open (no new evidence was introduced):

- No validated forecast skill; M8 verification status remains `NOT_EVALUATED`.
- M8 is `NOT_REAL_TIME`; providers are `SYNTHETIC`/`FIXTURE`.
- Landlab velocity extraction for M9 has not yet been implemented or verified.
- The full-suite two-test time-dependent fragility (pre-existing).

## 10. Human Decisions Still Required

- **D-016** — `PREPARED`, `HUMAN REVIEW REQUIRED`, `NOT APPROVED`. Profile totals
  remain 20/45/90 mm; the 72.08/88.44/103.25 mm source-derived totals are **not** flipped
  into profiles.
- **B02** — `OPEN`, WB AMRUT data not verified for hydraulic use.
- **B13** — `B13-DEMO-V1`, `approved=false`, `PROVISIONAL DEMONSTRATION`, synthetic roads.

## 11. Claim Boundary

UFNS **may** claim (unchanged): a reproducible demonstration/research system, a
deterministic four-scenario suite on the M4 coupled engine, an M6/M7 inspection
dashboard/API, M8 rainfall ingestion + nowcasting as `NOT_REAL_TIME` with a persistence
baseline and `SYNTHETIC`/`FIXTURE` providers.

UFNS **must not** claim (unchanged): safe routing, operational emergency navigation,
certified vehicle safety, real-time rainfall, validated nowcast skill, operational flood
forecasting, expert-approved B13 thresholds, approved D-016 profiles, audited B02 real
drainage data, or that the M9 velocity model is a validated vehicle stability model.

## 12. Recommended Next Milestone

Continue M9 as planned: Phase 2 (Landlab OverlandFlow velocity semantics verification)
before any velocity code is written, using the actual installed Landlab version and the
exact OverlandFlow configuration used by UFNS. Record the evidence in the appropriate
documents before introducing any derived velocity field or hazard-band representation.

Separately, fix the two time-dependent M8 tests (make the requested observation time
relative to run time) so the full suite is deterministic end-to-end.
