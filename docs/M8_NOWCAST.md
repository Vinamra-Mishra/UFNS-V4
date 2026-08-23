# M8 — Rainfall Ingestion + Nowcasting

> **Status:** M8 PASS — TECHNICAL (NOT_REAL_TIME; persistence baseline demonstration)
> **Date:** 2026-08-22
> **Tests:** 176 M8 tests + 330 total (154 M1–M7 + 176 M8)
> **Note:** as-of-M8 historical snapshot. As of M9.1.1 the file `tests/test_m8_nowcast.py`
> contains 188 tests (M9.1/M9.1.1 added frontend + error-code tests); current totals: see
> `docs/AI_REVIEW.md` §10.
> **Scientific status:** PROVISIONAL (persistence baseline; no real data)
> **Real-time status:** NOT_REAL_TIME — providers are SYNTHETIC/FIXTURE; no verified live rainfall feed

---

## 1. Summary

M8 implements the rainfall ingestion and nowcasting layer for UFNS. It provides:

1. **Provider-independent rainfall ingestion** — an abstract `RainfallProvider` interface with concrete synthetic and fixture implementations
2. **Data quality validation** — freshness, units, completeness, and spatial checks
3. **Persistence-baseline nowcast** — the scientifically simplest nowcast, holding the latest observed field constant over a conservative 0–60 min horizon
4. **Typed nowcast contract** (`NowcastRecord`) with full provenance
5. **API endpoints** for rainfall observations, nowcast forecasts, provider management, and verification status
6. **Dashboard integration** showing rainfall/nowcast status with explicit data source labelling
7. **M9 integration point** — as of M9, these nowcast records are also adapted into explicit forecast rainfall frames that drive the flood-impact/routing pipeline (see `docs/M9_NOWCAST_IMPACT.md`)

## 2. Governance

### Non-negotiable rules (all satisfied)

| Rule | Status | Evidence |
|------|--------|----------|
| No fabricated real-time data | ✅ | Default provider is SYNTHETIC |
| No fabricated API responses | ✅ | All responses carry source_type |
| No fake "LIVE" badge | ✅ | Labels: SYNTHETIC/DEMONSTRATION/PERSISTENCE_BASELINE |
| No fake forecast confidence | ✅ | Uncertainty = NOT PROVIDED |
| Every source has provenance | ✅ | source_type, source_name, source_provider_id |
| Every forecast identifies method | ✅ | method = NOWCAST-PERSISTENCE-V1 |
| Fails visibly when data unavailable | ✅ | Returns UNAVAILABLE status, not stale data |
| No silent fallback to synthetic | ✅ | Source type is explicit, never inferred |

### Governance items unchanged

- **D-016:** PREPARED — HUMAN REVIEW REQUIRED (unchanged)
- **B02:** NOT AUDITED (unchanged)
- **B13:** PROVISIONAL DEMONSTRATION (unchanged)

## 3. Architecture

```text
                    ┌─────────────────────────┐
                    │    RainfallProvider      │  (abstract interface)
                    │  fetch_latest()          │
                    │  fetch_observation(t)    │
                    │  health()                │
                    │  metadata()              │
                    └────────┬────────────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
   ┌──────────▼──┐  ┌───────▼──────┐  ┌───▼──────────┐
   │  SYNTHETIC   │  │   FIXTURE    │  │    REAL      │
   │  Provider    │  │   Provider   │  │  Provider    │
   │  (M8 active) │  │  (test/demo) │  │  (M10+)      │
   └──────────────┘  └──────────────┘  └──────────────┘
              │
              ▼
   ┌──────────────────────┐
   │  Data Quality Check  │  (validate_observation)
   │  FRESH/STALE/MISSING │
   └──────────┬───────────┘
              │
              ▼
   ┌──────────────────────┐
   │  Persistence Nowcast │  (NOWCAST-PERSISTENCE-V1)
   │  forecast(t+Δt) =    │
   │    latest_observed   │
   └──────────┬───────────┘
              │
              ▼
   ┌──────────────────────┐
   │  NowcastRecord       │  (typed contract)
   │  init_time, valid,   │
   │  lead, rate, status, │
   │  fingerprint, proven │
   └──────────────────────┘
```

## 4. Provider Interface

```python
class RainfallProvider(ABC):
    provider_id: str           # machine-readable ID
    source_type: SourceType    # REAL | SYNTHETIC | FIXTURE
    source_name: str           # human-readable description

    fetch_latest() -> Optional[RainfallObservation]
    fetch_observation(t) -> Optional[RainfallObservation]
    health() -> ProviderHealth
    metadata() -> dict[str, Any]
```

### Registered providers

| Provider ID | Source Type | Purpose |
|-------------|-------------|---------|
| synthetic-v1 | SYNTHETIC | Default demo provider; generates deterministic fields |
| fixture-extreme-v1 | FIXTURE | Precomputed M5 S3 Extreme scenario replay |

## 5. Data Quality

Every observation passes validation:

| Check | Error if failed |
|-------|----------------|
| Timestamp timezone-aware | INVALID |
| Units = mm/h | INVALID |
| No NaN/Inf | INVALID |
| No negative rainfall | INVALID |
| Grid shape matches | WARNING |
| Freshness ≤ threshold | FRESH |
| Freshness > threshold | STALE |
| Very old | MISSING |

### Freshness thresholds (configurable)

- FRESH: ≤ 30 minutes
- STALE: ≤ 120 minutes
- MISSING: > 240 minutes

## 6. Nowcast Method

**NOWCAST-PERSISTENCE-V1:**
- forecast(t + Δt) = latest_observed_field
- Lead times: 0, 15, 30, 45, 60 minutes
- Conservative horizon based on literature (Germann & Zawadzki 2002)
- Deterministic, transparent, no training data required
- Uncertainty: NOT PROVIDED

## 7. API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/rainfall/latest` | GET | Latest observation from active provider |
| `/api/v1/rainfall/status` | GET | Overall rainfall system status |
| `/api/v1/rainfall/observation?time=` | GET | Observation at specific time |
| `/api/v1/nowcast/latest` | GET | Latest nowcast (all lead times) |
| `/api/v1/nowcast/status` | GET | Overall nowcast system status |
| `/api/v1/nowcast/{lead}` | GET | Nowcast for specific lead time |
| `/api/v1/nowcast/providers` | GET | List all providers |
| `/api/v1/nowcast/providers/{id}` | GET | Provider detail |
| `/api/v1/nowcast/verification` | GET | Verification status (NOT_EVALUATED) |
| `/api/v1/nowcast/cache` | GET | Cache statistics |

## 8. Test Matrix

| Test ID | Description | Status |
|---------|-------------|--------|
| M8-01 | Provider contract | ✅ PASS |
| M8-02 | Source identification | ✅ PASS |
| M8-03 | Timestamp validation | ✅ PASS |
| M8-04 | Units enforcement | ✅ PASS |
| M8-05 | Stale-data detection | ✅ PASS |
| M8-06 | Missing-data handling | ✅ PASS |
| M8-07 | Persistence determinism | ✅ PASS |
| M8-08 | Nowcast contract | ✅ PASS |
| M8-09 | Fingerprint determinism | ✅ PASS |
| M8-10 | API rainfall/latest | ✅ PASS |
| M8-11 | API nowcast/latest | ✅ PASS |
| M8-12 | Invalid requests | ✅ PASS |
| M8-13 | Provenance | ✅ PASS |
| M8-14 | Caching | ✅ PASS |
| M8-15 | Forecast/observation separation | ✅ PASS |
| M8-16 | Dashboard status | ✅ PASS |
| M8-17 | Synthetic-provider labelling | ✅ PASS |
| M8-18 | Provider failure | ✅ PASS |
| M8-19 | Regression M1-M7 | ✅ PASS |
| M8-20 | Verification behaviour | ✅ PASS |
| M8-21+ | Additional tests | ✅ PASS |

**Total: 176 tests, all passing.** (Additional coverage includes: health-endpoint
degradation on UNAVAILABLE rainfall, invalid-observation status gating, cache
integration + immutability + thread safety, the nowcast lead-time invariant, the
complete-field fingerprint, and the fixture no-future-timestamp regression.)

## 9. Dashboard Changes

The M8 dashboard adds:
- **Rainfall + Nowcast panel** (sidebar) showing source, health, freshness, method, uncertainty, verification status
- Explicit warning: "⚠ PERSISTENCE BASELINE — NOT an operational forecast"
- All existing M7 functionality preserved

## 10. Performance

Measured on 2 vCPU sandbox:
- `/api/v1/rainfall/latest`: <5 ms
- `/api/v1/nowcast/latest`: <10 ms
- `/api/v1/nowcast/0`: <5 ms
- Cache operations: <1 ms

## 11. Failure Modes

| Failure | Behaviour |
|---------|-----------|
| No observation available | Returns UNAVAILABLE, not stale data |
| Provider unhealthy | Returns provider health status |
| Invalid timestamp | Returns 400 with structured error |
| Invalid lead time | Returns 400 with valid leads list |
| Unknown provider | Returns 404 |

## 12. Known Limitations

1. **No real-time data feed** — default provider is SYNTHETIC (D-017 in force)
2. **Persistence is the simplest possible nowcast** — no storm evolution prediction
3. **Conservative 0–60 min horizon** — based on literature, not site-specific validation
4. **Verification = NOT_EVALUATED** — no paired (forecast, observation) data exists
5. **Uncertainty = NOT PROVIDED** — deterministic method does not quantify uncertainty

## 13. Files Changed

### New files
- `services/nowcast/__init__.py`
- `services/nowcast/providers/__init__.py` (RainfallProvider, RainfallObservation, etc.)
- `services/nowcast/providers/synthetic_provider.py`
- `services/nowcast/providers/fixture_provider.py`
- `services/nowcast/quality.py`
- `services/nowcast/nowcast_record.py`
- `services/nowcast/engine.py`
- `services/nowcast/cache.py`
- `services/nowcast/verification.py`
- `apps/api/rainfall_api.py`
- `tests/test_m8_nowcast.py` (176 tests)
- `docs/M8_NOWCAST.md`
- `docs/M8_SCIENTIFIC_REVIEW.md`
- `docs/M8_INDEPENDENT_REVIEW.md`
- `docs/M8_VELOCITY_INTEGRATION.md`

### Modified files
- `apps/api/app.py` (M8 endpoints, health/version updated)
- `apps/web/index.html` (rainfall/nowcast status panel)
- `tests/test_m6_dashboard.py` (app name ufns-m7 → ufns-m8)
- `docs/DECISIONS.md` (D-024)
- `docs/AGENT_STATE.md` (M8 progress log)
- `docs/AI_REVIEW.md` (M8 status)
- `README.md` (M8 entry)
