# M8 — Independent AI Research Review

> **Status:** AI RESEARCH REVIEW (not human scientific approval)
> **Date:** 2026-08-22
> **Reviewer:** Independent AI agent (second opinion, distinct from implementation)
> **Scope:** M8 nowcast architecture, scientific defensibility, honesty guarantees

---

## 1. Review Questions

The independent reviewer was asked to answer:

1. Is the nowcast scientifically defensible?
2. Are the assumptions explicit?
3. Are the lead times justified?
4. Is persistence an appropriate baseline?
5. Are real-time claims justified?
6. Is the data provenance adequate?
7. Are uncertainty claims honest?
8. Could a user mistake forecast output for observation?
9. Could a user mistake modelled routing for safe routing?

## 2. Answers

### Q1: Is the nowcast scientifically defensible?

**YES — with caveats.**

The persistence baseline is the universal first nowcast in the literature
(Germann & Zawadzki 2002; WMO 2017; pySTEPS documentation). It is
scientifically defensible as:
- A reference baseline against which future methods must demonstrate improvement
- An appropriate choice for steady-state or slowly-evolving precipitation
- A transparent, testable, zero-cost method

**Caveat:** Persistence is NOT a production nowcast. It cannot predict storm
evolution and has near-zero skill for convective systems beyond ~30 minutes.
The M8 documentation makes this explicit.

### Q2: Are the assumptions explicit?

**YES.**

Every assumption is documented:
- Method = "PERSISTENCE" (not "AI forecast" or "advanced nowcast")
- Status = "PROVISIONAL" (not approved)
- Uncertainty = "NOT PROVIDED" (not fabricated confidence)
- Verification = "NOT_EVALUATED" (no fake skill scores)
- Source type = "SYNTHETIC" (not "REAL")
- Lead time justification cites literature (Germann & Zawadzki 2002)

### Q3: Are the lead times justified?

**YES — conservatively.**

The 0–60 min horizon at 15-min intervals is supported by the literature:
- Persistence skill is positive for 0–15 min on stratiform rain
- Persistence skill drops to near-zero beyond 30 min for convective systems
- The 60-min maximum is a conservative upper bound

The system allows configurable horizons (NowcastConfig.lead_times_minutes),
so future methods can extend or reduce the horizon as evidence warrants.

### Q4: Is persistence an appropriate baseline?

**YES.**

Persistence is the universally accepted first baseline in nowcasting. No
more complex method should be evaluated without first demonstrating
improvement over persistence. The M8 architecture correctly:
- Implements persistence first
- Labels it as "PERSISTENCE BASELINE" (not an advanced method)
- Leaves the architecture open for future methods (optical flow, ML, ensemble)

### Q5: Are real-time claims justified?

**NO — and this is correctly handled.**

M8 does NOT claim to be real-time. The documentation states:
- "No verified live feed exists" (D-017 in force)
- Default provider is SYNTHETIC
- Labels include "NOT_REAL_TIME" and "DEMONSTRATION"
- No "LIVE" badge anywhere in the UI

The architecture is **prepared** for real-time data (provider-independent
interface) but does not claim real-time capability.

### Q6: Is the data provenance adequate?

**YES.**

Every observation and nowcast record carries:
- `source_type` (REAL / SYNTHETIC / FIXTURE)
- `source_name` (human-readable description)
- `source_provider_id` (machine-readable ID)
- `fingerprint` (deterministic hash)
- `quality_flags` (list of quality indicators)

The API always exposes source_type — it is never inferred by the frontend.

### Q7: Are uncertainty claims honest?

**YES.**

M8 explicitly states uncertainty = "NOT PROVIDED" because:
- The persistence method does not quantify uncertainty
- No ensemble or probabilistic method is implemented
- No numerical confidence intervals are fabricated

The scientific review (M8_SCIENTIFIC_REVIEW.md) documents future options
for uncertainty quantification (ensemble STEPS, radar uncertainty, etc.).

### Q8: Could a user mistake forecast output for observation?

**NO — the design prevents this.**

The UI and API clearly separate:
- Observations (`/api/v1/rainfall/latest`) — the latest observed field
- Forecasts (`/api/v1/nowcast/latest`) — the nowcast at each lead time

Each carries its own `source_type` and method. The dashboard panel labels
the nowcast as "PERSISTENCE BASELINE — NOT an operational forecast."

### Q9: Could a user mistake modelled routing for safe routing?

**NO — this is prevented by M7's design.**

The M7 routing continues to use:
- "MODELLED ROUTE" / "MODELLED UNSUITABLE" wording (not "SAFE ROUTE")
- B13-DEMO-V1 PROVISIONAL DEMONSTRATION policy
- `approved=false` on the policy
- Permanent disclaimers in the UI

M8 does not alter the routing or the B13 policy in any way.

## 3. Recommendations

| # | Recommendation | Classification | Justification |
|---|---------------|----------------|---------------|
| R1 | Add radar-based provider when IMD data becomes available | ACCEPT | Scientific review identifies this as the gold standard |
| R2 | Implement gauge-based verification when data exists | ACCEPT | Required for honest forecast evaluation |
| R3 | Add ensemble (STEPS) nowcast when radar is available | ACCEPT WITH AMENDMENT | Requires radar data first; defer to M10+ |
| R4 | Reduce max lead time to 30 min for convective regimes | DEFER | Site-specific tuning requires real data; current 60 min is conservative but defensible |
| R5 | Add FSS (Fractions Skill Score) for spatial verification | ACCEPT | Appropriate for gridded rainfall; implement when data available |
| R6 | Document persistence failure modes more explicitly in the UI | ACCEPT | Already documented in API labels; UI warning added |
| R7 | Consider bias correction for future radar/gauge fusion | DEFER | No real data currently available; premature to implement |
| R8 | Add WebSocket for real-time nowcast updates | DEFER | Architecture supports this but it is not needed for demonstration |
| R9 | Integrate velocity-based hazard classification | DEFER | Documented in M8_VELOCITY_INTEGRATION.md; requires M4 velocity export |
| R10 | Request independent human scientific review of the nowcast methodology | ACCEPT | AI review is not human approval; this should be done before any operational claim |

## 4. Overall Assessment

**The M8 implementation is scientifically honest and architecturally sound.**

Strengths:
- Provider-independent design enables future real-data integration
- Persistence baseline is the correct first step
- Full provenance in every output
- No fabricated data, scores, or claims
- Clear separation of observation and forecast
- Verification correctly marked NOT_EVALUATED

Weaknesses (documented, not hidden):
- No real-time data (D-017 in force)
- Persistence has limited skill for convective systems
- No uncertainty quantification
- No verification possible until real data exists

The M8 implementation correctly identifies itself as a demonstration
prototype at LEVEL 1 maturity. It does not claim operational capability.

## 5. Scientific Limitations

1. Persistence cannot predict storm evolution
2. No site-specific validation is possible without real data
3. The 0–60 min horizon is based on general literature, not Kolkata-specific studies
4. No bias correction (requires gauge/radar pairs)
5. No ensemble/probabilistic forecast (requires radar + STEPS implementation)
6. No verification scores (requires paired forecast/observation data)

## 6. Human Review Required

The following items require human/expert review before any operational use:

1. **Hydrologist approval** of the nowcast methodology for the pilot region
2. **Meteorologist review** of the persistence lead-time assumptions
3. **IMD data access** for real-time rainfall observations
4. **Domain expert review** of any future velocity-based hazard classification
5. **Safety review** before any routing advice depends on nowcast output

---

*This review is conducted by an independent AI agent. It is NOT a substitute
for human expert review. No scientific approval is claimed or fabricated.*
