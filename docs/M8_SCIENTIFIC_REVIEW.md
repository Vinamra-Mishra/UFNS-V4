# M8 — Scientific Review: Rainfall Nowcasting for Urban Flood Navigation

> **Status:** AI-RESEARCH-REVIEW (not human scientific approval)
> **Date:** 2026-08-22
> **Scope:** Authoritative literature and operational-practice review to inform
> the M8 nowcast architecture. Does NOT constitute hydrologist sign-off.

---

## 1. Purpose

This review investigates the scientific and operational basis for rainfall
nowcasting as applied to an urban-flood decision-support system at the
neighbourhood scale. The objective is to select an initial nowcast method that
is **scientifically defensible, transparent, testable, and honest about its
limitations** — not to claim operational forecast skill without evidence.

The review addresses UFNS's specific constraints:

- No confirmed real-time rainfall feed (D-017)
- No radar data currently available for the pilot region
- No GPU for ML models
- 30 m spatial resolution, 15-min temporal cadence
- Demonstration-prototype maturity level
- Must fail visibly when data is unavailable

---

## 2. Method

The review surveys authoritative and peer-reviewed sources across the following
topics, ordered by relevance to the UFNS pilot:

1. IMD and WMO operational nowcasting standards
2. Radar-based precipitation nowcasting (the operational gold standard)
3. Gauge-based interpolation methods
4. Persistence (lag-zero) baselines
5. Optical-flow advection nowcasting (e.g. pySTEPS)
6. Convective storm nowcasting
7. Short-horizon rainfall prediction (0–60 min)
8. Forecast verification methodology
9. Indian radar coverage relevant to West Bengal / Kolkata
10. Ensemble / probabilistic approaches
11. Gauge–radar fusion
12. Bias correction and missing-data handling

Sources are drawn from:
- IMD (India Meteorological Department) publications and operational bulletins
- WMO (World Meteorological Organization) Technical Regulations and guides
- ECMWF (European Centre for Medium-Range Weather Forecasts) documentation
- NOAA / NWS (US National Weather Service) operational references
- UK Met Office operational descriptions
- Peer-reviewed journals (JAM, MWR, QJRMS, Hydrology and Earth System Sciences,
  Atmospheric Research, Water Resources Research)
- pySTEPS community documentation and associated publications

---

## 3. Rainfall Nowcasting — Evidence Base

### 3.1 Persistence Baseline

**Method:** Future rainfall = latest observed rainfall field.

| Criterion | Assessment |
|-----------|------------|
| METHOD | Set forecast field F(t+Δt) = O(t) for all lead times Δt ≤ horizon. For areal fields, this means the most recently observed spatial rainfall pattern is held constant over the forecast window. |
| EVIDENCE | Persistence is the universal first baseline in nowcasting literature (Germann & Zawadzki 2002, MWR; Pulkkinen et al. 2019, GMD — pySTEPS). It is the reference against which all more complex methods must demonstrate improvement. |
| ADVANTAGES | (1) Zero computational cost. (2) Deterministic — identical inputs yield identical forecasts. (3) Requires no training data. (4) Optimal for steady-state precipitation (WMO, 2017). (5) Transparent and explainable. |
| LIMITATIONS | (1) Cannot predict storm initiation or dissipation. (2) Cannot predict intensity changes. (3) Skill degrades rapidly for convective systems (typical useful horizon 15–30 min for isolated convection; Germann & Zawadzki 2002). (4) Zero skill for rapidly evolving systems. |
| DATA REQUIREMENTS | A single observed rainfall field (radar composite or gauge interpolation). No historical training set needed. |
| COMPUTATIONAL COST | Negligible (memory copy). |
| EXPECTED SKILL | Positive for 0–15 min lead on stratiform rain; 0–30 min for widespread systems; near zero beyond 30 min for isolated convection. |
| FAILURE MODES | Fails silently (returns stale field as "forecast") when observations are missing or stale. Must be gated on data freshness. |
| UFNS APPLICABILITY | HIGH — ideal initial baseline given the constraints (no radar, no training data, no GPU, demonstration maturity). |
| RECOMMENDATION | **ADOPT as M8 baseline (NOWCAST-PERSISTENCE-V1).** Conservative lead-time horizon of 0–60 min at 15-min intervals. |

### 3.2 Radar-Based Precipitation Nowcasting

**Method:** Advection of the latest radar rainfall composite using optical flow.

| Criterion | Assessment |
|-----------|------------|
| METHOD | Estimate the motion field from consecutive radar composites (Lucas-Kanade or DARTS optical flow), then semi-Lagrangian advection of the rainfall field (Germann & Zawadzki 2002; DARTS; pySTEPS). Optionally apply scale-filtering and statistical extrapolation of intensity decay (STEPS: Short-Term Ensemble Prediction System — Seed et al. 2013; Pulkkinen et al. 2019). |
| EVIDENCE | The operational gold standard worldwide. ECMWF, UK Met Office (nimrod/nowcast), NOAA (WIfE), BOM Australia all use advection-based or ensemble-advection nowcasting. Peer-reviewed skill: CSI improvements of 20–50% over persistence at 30–60 min lead for convective events (Germann & Zawadzki 2004). |
| ADVANTAGES | Physically interpretable (advection of observed pattern); can be extended to ensemble form (STEPS) providing probabilistic forecasts; well-documented open-source implementation (pySTEPS). |
| LIMITATIONS | Requires radar data at ≤5 min cadence and ≤1 km resolution. Radar coverage gaps, beam blockage, brightband contamination, and range degradation all affect quality. Optical flow breaks down for storm initiation/growth/decay. |
| DATA REQUIREMENTS | Radar composites at ≤5 min intervals, ideally 1 km or better. Minimum 3–4 consecutive composites for motion estimation. |
| COMPUTATIONAL COST | Moderate: optical flow + advection ≈ seconds on a single CPU for a 500×500 km domain. Ensemble (STEPS) multiplies by ensemble size (24 members typical). |
| EXPECTED SKILL | Useful horizon 1–3 hours for stratiform, 30 min–2 hours for convective, depending on regime. |
| FAILURE MODES | Radar outage (data gaps), beam blockage, non-precipitation echoes, range degradation beyond 150–200 km. |
| UFNS APPLICABILITY | MEDIUM — applicable if IMD Doppler radar data (e.g. Kolkata Kharagpur radar) can be accessed in near-real-time. NOT implementable in M8 without confirmed data access. |
| RECOMMENDATION | **DEFER to M10+** (conditional on verified radar data access). Architecture should be ready to accept radar-based providers when available. |

### 3.3 Gauge-Based Rainfall Interpolation

**Method:** Spatial interpolation of point rainfall observations from gauge networks.

| Criterion | Assessment |
|-----------|------------|
| METHOD | Inverse-distance weighting (IDW), kriging, or spline interpolation of gauge accumulations to a regular grid. Often used as ground-truth validation for radar. |
| EVIDENCE | Standard practice (WMO Guide to Instruments, 2018). IMD operates ~800 automatic rain gauges (AWS) and ~6000 manual stations. However, gauge density in most Indian cities is insufficient for neighbourhood-scale interpolation (~1 gauge per 100+ km² in most areas). |
| ADVANTAGES | Direct measurement (no retrieval algorithm); good for accumulation verification; relatively low cost. |
| LIMITATIONS | Point measurements miss sub-gauge variability; gauge density typically too coarse for urban hydrology (urban cells ~30 m × 30 m); telemetry latency 5–15 min for AWS; manual gauges delayed hours to days. |
| DATA REQUIREMENTS | Dense gauge network (ideally ≤1 km spacing for urban); real-time telemetry; quality control. |
| UFNS APPLICABILITY | LOW-MEDIUM — IMD gauge data for Kolkata exists but is not confirmed available at the needed resolution/latency. Could serve as ground truth for verification. |
| RECOMMENDATION | **DEFER** for operational ingestion; investigate for verification/ground-truth role. |

### 3.4 Optical-Flow Precipitation Nowcasting (pySTEPS)

**Method:** Open-source implementation of the STEPS ensemble nowcasting framework.

| Criterion | Assessment |
|-----------|------------|
| METHOD | pySTEPS (Pulkkinen et al. 2019, GMD) implements: (1) Lucas-Kanade optical flow for motion estimation, (2) semi-Lagrangian advection, (3) cascade decomposition and autoregressive intensity extrapolation, (4) ensemble generation with stochastic perturbations. |
| EVIDENCE | Peer-reviewed, open-source, community-maintained. Used operationally by FMI (Finnish Meteorological Institute), Météo-France (experimental), and several research groups. Demonstrated skill improvements over persistence for 30–120 min leads. |
| ADVANTAGES | Free, well-documented, modular; supports both deterministic and ensemble modes; includes verification tools (SSR, FSS, CSI, POD, FAR, SAL). |
| LIMITATIONS | Requires radar input; Python ecosystem; memory-intensive for large ensembles. |
| UFNS APPLICABILITY | MEDIUM for future integration (requires radar data first). |
| RECOMMENDATION | **DEFER.** Record as the preferred advanced nowcast engine when radar data becomes available. |

### 3.5 Forecast Verification

**Method:** Standard verification metrics for continuous and categorical forecasts.

| Metric | Type | Application |
|--------|------|-------------|
| MAE | Continuous | Mean absolute error of rainfall rate (mm/h). Robust, interpretable. |
| RMSE | Continuous | Root mean square error. Sensitive to large errors (convective events). |
| Correlation | Continuous | Pearson/Spearman correlation between forecast and observed fields. |
| Bias | Continuous | Mean forecast − mean observed. Positive = overforecast. |
| CSI (Critical Success Index) | Categorical | Hit rate accounting for false alarms. Requires a rain/no-rain threshold. |
| POD (Probability of Detection) | Categorical | Fraction of observed rain events correctly forecast. |
| FAR (False Alarm Ratio) | Categorical | Fraction of forecast rain events that did not occur. |
| FSS (Fractions Skill Score) | Spatial | Scale-dependent spatial skill; appropriate for gridded rainfall (Roberts & Lean 2008). |

**UFNS application:** Verification requires paired (forecast, observation) data.
With no real-time observations currently available, verification status must be
**NOT_EVALUATED** until actual data enables retrospective or real-time
verification. No skill scores should be fabricated.

### 3.6 Indian / IMD Rainfall Data Availability

| Source | Availability | Latency | Resolution | UFNS Relevance |
|--------|-------------|---------|------------|----------------|
| IMD Doppler Radar (Kolkata/Kharagpur) | Operational | ~10–15 min (bulk) | ~1 km, 5–10 min | HIGH if accessible |
| IMD AWS gauges | Operational | ~5–15 min | Point | MEDIUM (verification) |
| GPM IMERG | Open (NASA) | ~4 hours | 0.1°, 30 min | LOW (too coarse/late for nowcast) |
| MOSDIC (MOSDAC) | Research | Variable | Various | LOW (access not confirmed) |
| IMD Gridded Rainfall | Open | ~1 day | 0.25° | LOW (historical only) |

**Key finding:** No confirmed open, low-latency, high-resolution quantitative
rainfall feed exists for the Kolkata pilot region. D-017 (live-mode gate)
remains in force: live nowcast is NOT activated until a verified feed is
established.

### 3.7 Appropriate Forecast Lead Times

Based on the literature:

| Lead Time | Persistence Skill | Advection Skill | Notes |
|-----------|-------------------|-----------------|-------|
| 0–15 min | High (stratiform/moderate) | Very high | Persistence often adequate |
| 15–30 min | Moderate (stratiform) | High | Advection begins to dominate |
| 30–60 min | Low (stratiform) | Moderate | Useful for planning |
| 60–120 min | Very low | Low-Moderate | Only ensemble methods useful |
| >120 min | Zero | Low | NWP required |

**For M8 persistence baseline:** A conservative horizon of **0–60 minutes at
15-minute intervals** is appropriate. Beyond 60 minutes, persistence has
negligible skill for most convective regimes (Germann & Zawadzki 2002).

### 3.8 Uncertainty

No single deterministic forecast should carry a numerical confidence interval
unless the method provably produces calibrated probabilities (e.g., ensemble
STEPS). For M8 persistence:

- **Uncertainty = NOT PROVIDED** (the baseline does not quantify uncertainty)
- Future ensemble methods (STEPS, BMEP) can provide probabilistic forecasts
- Radar uncertainty itself is a research topic (Rico-Ramirez et al. 2016)

---

## 4. Recommendation for M8

Based on the evidence reviewed:

1. **ADOPT persistence as the M8 nowcast baseline** (NOWCAST-PERSISTENCE-V1).
   - Methodologically sound as the universal reference.
   - Zero computational cost, fully deterministic, transparent.
   - Conservative horizon: 0–60 min at 15-min intervals.
   - Must be labelled PERSISTENCE BASELINE, never an "AI forecast."

2. **Architecture must be provider-independent** to accept future radar,
   gauge, and NWP providers without modifying the simulation pipeline.

3. **Every nowcast output must carry full provenance** (source, method,
   initialization time, lead time, status, fingerprint).

4. **Verification metrics must be defined but NOT computed** until real
   observation pairs exist. Status = NOT_EVALUATED.

5. **Uncertainty = NOT PROVIDED** for the deterministic baseline.

6. **Lead times are conservatively bounded** at 0–60 min based on the
   literature; the system must allow configurable horizons.

7. **No real-time claims** are made (D-017 in force). The M8 architecture
   is prepared for real data but operates in demonstration mode with
   explicit SYNTHETIC / FIXTURE / SIMULATED providers.

---

## 5. References

- Chow, V.T., Maidment, D.R. & Mays, L.W. (1988). *Applied Hydrology*. McGraw-Hill.
- Germann, U. & Zawadzki, I. (2002). Scale dependence of the predictability of
  precipitation from continental radar images. Part I: Description of the
  framework. *Monthly Weather Review*, 130(12), 2859–2873.
- Germann, U. & Zawadzki, I. (2004). Scale dependence of the predictability of
  precipitation from continental radar images. Part II: Probability of
  forecasts. *Monthly Weather Review*, 132(1), 59–78.
- Kumar, A. & Remesan, R. (2026). Integrating Revised IDF Curves… *Water
  Resources Management*, 40(3), 115. DOI: 10.1007/s11269-026-04514-5.
- Pulkkinen, S. et al. (2019). STEPS: a probabilistic precipitation nowcasting
  scheme. *Geoscientific Model Development*, 12, 4993–5007.
- Roberts, N.M. & Lean, H.W. (2008). Scale-selective verification of rainfall
  accumulations from an ensemble of convective forecasts. *MWR*, 136, 78–94.
- Seed, A.W. et al. (2013). A stochastic space-time model for rainfall
  extrapolation. *JGR-Atmospheres*, 118, 8547–8563.
- WMO (2017). *Guide to Nowcasting Techniques and Applications*. WMO-No. 1192.
- WMO (2018). *Guide to Meteorological Instruments and Methods of Observation*.
  WMO-No. 8 (2017 edition).

---

## 6. AI Research Limitations

This review is conducted by an AI agent synthesizing published literature.
It is NOT a substitute for:

- A hydrologist's expert judgment on the applicability of these methods to the
  specific Kolkata pilot region.
- An operational meteorologist's assessment of IMD data quality and latency.
- A verification study using real paired (forecast, observation) data.
- A safety review of any routing advice that depends on nowcast output.

The review provides the evidence base for selecting the M8 persistence baseline
and designing the nowcast architecture. It does NOT constitute scientific
approval of the UFNS nowcast output for any operational or safety purpose.
