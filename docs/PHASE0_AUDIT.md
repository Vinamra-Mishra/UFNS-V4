# SIH26085 (UFNS) — Phase 0 Independent Audit

**Auditor:** Independent review board (no implementation authority)
**Date:** 2026-08-21
**Scope:** All Phase 0 documentation and the repository state behind it
**Status of this document:** Review record; findings require human action. No approval gate is marked APPROVED anywhere in this audit or in `PHASE0_APPROVAL.md`.

---

## 1. Method and evidence base

Reviewed in full:

- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/DATA_SOURCES.md`
- `docs/MODEL_ASSUMPTIONS.md`
- `docs/ROADMAP.md`
- `docs/DECISIONS.md`
- `docs/AGENT_STATE.md`

Inspected beyond the files:

- Git history, including both parents of the merge commit `4a40fab` (via GitHub API): the pre-Phase-0 `main` contained exactly one 80-byte `README.md`, confirming the documented "repository started empty apart from this README" claim.
- GitHub repository state: 1 merged PR (`#1`, from branch `arena/01a024f6-ufns`), **no issues**, **no CI workflows**, **no dependency manifests**, **no LICENSE file**, no data files.
- Independent spot-verification (web) of the riskiest external claims:
  - **FABDEM v1.2 licence** — confirmed CC BY-NC-SA 4.0 (University of Bristol dataset page / licence text; commercial enquiries via Fathom). Vertical reference EGM2008 stated in the product readme.
  - **Copernicus DEM GLO-30 licence** — confirmed free for the general public with mandatory DLR/Airbus/Copernicus attribution; GLO-30 "Public" coverage is not worldwide-complete (some country tiles withheld) — pilot coverage must be checked at ingestion.
  - **`india-geodata` aggregator** — repo exists; the "Urban Water" collection contains `WB_AMRUT_Stormwater_drains` (~15 MB Parquet) and `WB_AMRUT_Stormwater_vents` (~0.4 MB Parquet) plus SBM layers; repo licence CC BY 4.0; **primary provenance of the underlying government data still requires verification**.
  - **Landlab `OverlandFlow`** — confirmed it implements the de Almeida et al. (2012) stabilised storage-cell algorithm on a structured raster grid with D4 link flow, adaptive timestep, `alpha` (default 0.7), `theta` (default 0.8), and a **uniform scalar `rainfall_intensity` input** (see blocker B06).
  - **PySWMM coupling primitives** — confirmed (`step_advance`, `node.generated_inflow`, `node.flooding`, outfall stage control); community evidence confirms bi-directional 1-D/2-D coupling at each SWMM time step is feasible, **and** that SWMM's reported flooding rate is an unrestricted mass imbalance that can cause double-counting if misused (justifies the proposed spike + ledger).
  - **UK Environment Agency benchmark Tests 8A/8B** — confirmed to exist in the public SC120002 report (Néelz & Pender, "Benchmarking the latest generation of 2D hydraulic modelling packages"); the report PDF is publicly downloadable; the test input datasets themselves must be located/requested or reconstructed from the published specifications at implementation time.
- Not verifiable from the repository: the official **SIH26085 problem-statement text**. The docs cite prompt values (e.g., the 30-second coupling value, example severity bands, 0–180 min horizon). The board recommends the human team commit the official problem-statement PDF (or a stable URL plus a requirements summary) to `docs/` so every cited requirement is traceable (blocker B11).

The board created no application code, models, datasets, or simulations, and marked no gate as passed. Only Phase 0 documentation was created or modified.

---

## 2. Architecture assessment

### 2.1 Internal consistency

**Verdict: consistent, with four documented open seams.**

The chain `sources → ingest/align → rainfall → losses → 2-D surface → 1-D drainage → impacts → platform` is closed-loop and each link has a data contract. Cross-checks performed:

- Rainfall → losses → surface flow → exchange → drainage → surcharge → depth → road impact: all stages have defined inputs/outputs and units (`ARCHITECTURE.md` §7–8, `MODEL_ASSUMPTIONS.md` §2–10).
- The mass ledger (rain, losses, storages, boundary outflow, outfall, exchange cancellation) is defined once and reused in contracts, run sequence, tests, and UI. Consistent.
- Provenance classes are used consistently across ingestion, contracts, UI labels, and the "no synthetic-as-real" test. Consistent.
- CRS/time/grid policy is stated once (`ARCHITECTURE.md` §6) and enforced in contracts. Consistent.
- No contradiction found between README claims and the Phase 0 documents.

Open seams (all of them are **explicitly declared** in the docs, not hidden):
1. Pilot area undecided (deliberately; audit order proposed).
2. Inlet/surcharge exchange formulation is a "design direction, not yet an approved inlet model".
3. Demo rainfall scenario definitions (normal/heavy/extreme hyetographs) are not yet defined from any named design storm or historical event.
4. Vehicle passability / closure thresholds are TBD pending an expert reviewer.

### 2.2 Service boundaries

**Verdict: justified.**

The modular monolith (FastAPI + bounded simulation worker + PostGIS + artifact store; static frontend) matches the measured hardware (2 vCPU, 3.8 GiB RAM, no GPU, no Docker preinstalled) and the student-scale target. Keeping `rainfall`, `hydrology`, `hydraulics`, `simulation`, `routing` as typed modules with one deployable process is the right cost/rigor trade-off. The one boundary worth enforcing hardest in code review is `hydrology`/`hydraulics` versus `simulation` (no hidden cross-module state), because it is where silent mass errors would appear.

### 2.3 Data contracts

**Verdict: sufficient for implementation start; four gaps to close in Phase 1.**

Well specified: `DataLineage`, `GridSpec`, `RainfallGrid`, `TerrainBundle`, `FloodSnapshot`, `FloodCell`, `DrainageNode/Link/State`, `RoadSegmentRisk`, `RouteRequest/Option`, `SimulationRun`, `MassBalance`.

Gaps (close before the consumers start, per the roadmap's contract-freeze rule):

1. **No `ScenarioDefinition` contract.** Scenario ID, rainfall hyetograph fields, blockage overrides, parameters, and their provenance are referenced but not typed. This is the single biggest contract gap because scenarios are the demo's scientific core.
2. **DEM conditioning report** is referenced by URI but has no schema (required fields: operations, parameters, affected cells, before/after checksums, volume change, reviewer).
3. **Alert contract** is described in prose only (rule id, thresholds version, prediction id, valid time, entity, provenance need a schema).
4. **Inlet capture definition** is `object | null` — acceptable now, but must become a typed union (weir/orifice/rating-curve + regime flags) before Phase 4.

### 2.4 Inputs and outputs

**Verdict: clearly defined**, including units (`mm/h` external vs `m/s` solver), `valid_from/valid_to` interval semantics, lead time, and the explicit rule that `flood_probability` is null in deterministic runs. Output snapshots are defined with depth/velocity/extent threshold/mass balance fields.

### 2.5 Timestamps

**Verdict: handled correctly.**

UTC RFC 3339 storage/exchange, separate IANA local display, distinct issue/valid/lead-time fields, forcing interval vs output interval vs numerical step separated. Rainfall fields carry `[valid_from, valid_to)` interval semantics. Edge cases the board adds to the test list: 30-min source buckets mapped onto 15-min forcing (conservative remapping of accumulation, never duplication), forecast rollover at day boundaries, and stale-source behaviour (see red-team G/H).

### 2.6 CRS / projection assumptions

**Verdict: explicit and correct.**

Dual-CRS policy (EPSG:4326 lon/lat for interchange, per-pilot projected metric CRS for numerics), explicit vertical-reference policy, fail-fast on missing/implausible CRS, no silent guessing. The Kolkata (`EPSG:32645`) / Bengaluru (`EPSG:32643`) examples are correct UTM zones. One addition recommended: a mandatory **axis-order test fixture** (lat/lon swapped inputs are the most common real-world CRS bug) — the red-team matrix mentions "wrong axis" but it should be a Phase 1 unit test, not just a Phase 9 item.

### 2.7 Spatial and temporal resolutions

**Verdict: justified and honest.**

30 m native (Copernicus GLO-30), 4 km × 4 km domain (~18,000 cells — arithmetic checks out: ~133×134), 15-min forcing, 5-min output, adaptive seconds-scale solver steps. The refusal to present upsampled 30 m as 10 m terrain is scientifically correct. 15-min forcing is defensible for a screening model given available sources; a 10-min radar product, if access is ever granted, would fit the same contract.

### 2.8 Failure modes

**Verdict: identified unusually thoroughly for Phase 0.**

Run rejection rules (NaN, material negative depth, failed solver, continuity breach), no silent live→simulation fallback, missing-source → unavailable/stale (never zero), worker isolation, cancellation/timeout, database/artifact failure tests, red-team matrix in Phase 9. See §16 for the board's scenario walkthroughs.

### 2.9 Realism for student-scale infrastructure

**Verdict: realistic.**

The compute budget (one concurrent worker, 2 vCPU/3.8 GiB, goal "faster than the simulated horizon") is plausible for a 30 m local-inertial solver, and the SQLite/no-Docker fallback profile is a sensible hedge. PostGIS is the heaviest dependency; it is optional at demo time. No GPU, no Kubernetes, no paid services are required. The riskiest assumption (SWMM Python interface on this environment) is correctly scheduled as the first spike with a stop-and-review condition.

---

## 3. Data audit

Every source below is audited on all thirteen required attributes. For static (non-time-series) datasets, temporal attributes are recorded as N/A rather than omitted. Classification legend:

| Code | Meaning |
|---|---|
| `VERIFIED` | Availability + terms confirmed by this board (anonymous download/access exists) |
| `LIKELY AVAILABLE` | Download exists (often confirmed); provenance/terms need primary-source verification |
| `REQUIRES ACCESS` | Registration, credentials, or institutional approval required |
| `UNCERTAIN` | Machine access, content, or licence not confirmable at Phase 0 |
| `UNAVAILABLE` | Not currently obtainable |

### 3.1 Rainfall

#### S01 — India Meteorological Department (IMD) APIs
- Purpose: preferred live observation/forecast/warning input
- Spatial resolution: product-specific; endpoint-level audit required
- Temporal resolution: product-specific; endpoint-level audit required
- Format: per IMD public API reference
- Coverage: India
- Historical availability: via other IMD products (see S03); API archive unclear
- Near-real-time availability: intended; not confirmed until access is granted
- Access mechanism: official request via IMD nodal officer (not anonymous)
- Licence/access restrictions: IMD terms; interested organizations must contact IMD
- Expected latency: unknown until endpoint audit
- Reliability: unknown
- Fallback source: demo scenarios; Open-Meteo (labelled external NWP)
- **Classification: `REQUIRES ACCESS`** — policy: `REQUIRES HUMAN VERIFICATION` (team must request access; do not block the demo on it)

#### S02 — IMD radar services
- Purpose: high-value current rainfall/echo input
- Spatial resolution: station/product-specific
- Temporal resolution: ~10–15 min typical for Doppler products; unconfirmed for a machine feed
- Format: imagery/products
- Coverage: Indian radar network stations
- Historical availability: archive access unclear
- Near-real-time availability: browse pages are public; a stable licensed machine feed is **not confirmed**
- Access mechanism: web pages only
- Licence/access restrictions: machine-use rights unconfirmed
- Expected latency: unknown
- Reliability: unknown
- Fallback source: none quantitative (this is the core gap for live nowcasting)
- **Classification: `UNCERTAIN`** — policy: `REQUIRES HUMAN VERIFICATION`. Images ≠ quantitative rain-rate grids; georeferencing/calibration/rights unconfirmed.

#### S03 — IMD daily gridded rainfall (0.25°)
- Purpose: climatology, event totals, coarse baseline context
- Spatial resolution: 0.25° (~25 km)
- Temporal resolution: daily
- Format: NetCDF/GRD, yearly files
- Coverage: India, 1901–2024 per the official page
- Historical availability: excellent (century-scale)
- Near-real-time availability: none
- Access mechanism: anonymous download from the official IMD Pune page
- Licence/access restrictions: official download with required citation; check stated terms at download
- Expected latency: N/A (historical)
- Reliability: high (official product)
- Fallback source: ERA5-Land
- **Classification: `VERIFIED`** — policy: attribution required. Fitness: **never** to be downscaled and presented as high-resolution forcing (the docs state this correctly).

#### S04 — MOSDAC access policy (general)
- Purpose: ISRO satellite products incl. precipitation
- Spatial resolution: product-specific
- Temporal resolution: product-specific
- Format: product-specific
- Coverage: India/regional
- Historical availability: tier-dependent
- Near-real-time availability: tiered — anonymous: metadata/images; registered general: limited data with 3-day latency; privileged: NRT
- Access mechanism: MOSDAC SSO registration/tiers
- Licence/access restrictions: tiered terms; non-commercial limits likely
- Expected latency: tier-dependent (3 days for general users)
- Reliability: official ISRO service; tier-limited
- Fallback source: IMERG (delayed), ERA5-Land
- **Classification: `REQUIRES ACCESS`** — policy: `REQUIRES HUMAN VERIFICATION` (apply for a suitable tier early).

#### S05 — MOSDAC open data
- Purpose: historical research inputs
- Spatial resolution: product-specific
- Temporal resolution: product-specific
- Format: product-specific (HDF5/GeoTIFF common)
- Coverage: India/regional
- Historical availability: product archives
- Near-real-time availability: limited (open tier)
- Access mechanism: MOSDAC SSO requested for download
- Licence/access restrictions: free/open for non-commercial use
- Expected latency: N/A (research)
- Reliability: official; product-specific
- Fallback source: IMERG/ERA5-Land
- **Classification: `REQUIRES ACCESS`** — policy: non-commercial restriction + per-product redistribution check.

#### S06 — MOSDAC GSMaP-ISRO Rain
- Purpose: historical rainfall sequence, coarse evaluation baseline
- Spatial resolution: 0.1° (~10 km)
- Temporal resolution: hourly
- Format: HDF5
- Coverage: March 2000 onward (Level 3, gauge-adjusted, **beta**)
- Historical availability: 2000–present
- Near-real-time availability: no (research product)
- Access mechanism: MOSDAC SSO
- Licence/access restrictions: registration + product terms; beta status
- Expected latency: N/A (historical)
- Reliability: gauge-adjusted but beta; ~10 km cannot resolve urban convective cells
- Fallback source: IMERG Final
- **Classification: `REQUIRES ACCESS`** — policy: registration + non-commercial terms; beta status must be displayed in any use.

#### S07 — MOSDAC Heavy Rain Nowcast
- Purpose: contextual alert overlay only
- Spatial resolution: city-level alert product
- Temporal resolution: alert cadence, unconfirmed
- Format: public alert page
- Coverage: covered cities
- Historical availability: unclear
- Near-real-time availability: public page; no machine contract confirmed
- Access mechanism: web page
- Licence/access restrictions: unconfirmed
- Expected latency: unknown
- Reliability: unknown
- Fallback source: none (not a quantitative input)
- **Classification: `UNCERTAIN`** — policy: an alert is **not** a quantitative rain grid; it cannot force hydraulics.

#### S08 — NASA GPM IMERG (Early/Late/Final)
- Purpose: historical sequences, delayed estimates, benchmark source
- Spatial resolution: 0.1° (~10 km)
- Temporal resolution: 30 min
- Format: HDF5/NetCDF
- Coverage: global
- Historical availability: 2000–present
- Near-real-time availability: Early ~4 h latency (exceeds any nowcasting cycle)
- Access mechanism: NASA Earthdata login (GES DISC); AWS-hosted Early products may ease access — confirm at ingestion
- Licence/access restrictions: NASA open-data policy; product-specific terms; attribution
- Expected latency: Early ~4 h; Late ~12–14 h; Final ~3.5 months
- Reliability: high for a satellite product; urban-coarse
- Fallback source: GSMaP-ISRO, ERA5-Land
- **Classification: `REQUIRES ACCESS`** — policy: honest use is delayed estimation/benchmark only, never nowcasting.

#### S09 — ERA5-Land
- Purpose: historical forcing and climatological comparison
- Spatial resolution: ~9 km
- Temporal resolution: hourly
- Format: GRIB/NetCDF
- Coverage: global
- Historical availability: 1950–present
- Near-real-time availability: ~5 days latency (not nowcasting)
- Access mechanism: Copernicus CDS account + licence acceptance
- Licence/access restrictions: CDS terms; Copernicus licence
- Expected latency: N/A (historical)
- Reliability: high; reanalysis, urban-coarse
- Fallback source: IMERG
- **Classification: `REQUIRES ACCESS`** — policy: reanalysis is not an observation or a nowcast; label accordingly.

#### S10 — Open-Meteo forecast API
- Purpose: optional external NWP context; resilient demo adapter
- Spatial resolution: native model ~9 km (e.g., ECMWF IFS)
- Temporal resolution: hourly
- Format: JSON
- Coverage: global
- Historical availability: archive API exists
- Near-real-time availability: yes (forecast product)
- Access mechanism: anonymous HTTPS; no key for non-commercial use
- Licence/access restrictions: attribution + fair-use terms; API data CC BY 4.0
- Expected latency: seconds (hosted API)
- Reliability: good; third-party aggregator of NWP models
- Fallback source: none needed (context layer only)
- **Classification: `VERIFIED`** — policy: non-commercial use + attribution; display native model/run time; never call it measured rain or a high-resolution nowcast.

#### S11 — Demo hyetographs (internal)
- Purpose: guaranteed deterministic demonstration forcing
- Spatial resolution: pilot grid (spatially variable supported by contract)
- Temporal resolution: 15 min
- Format: scenario definition (contract gap — see §2.3)
- Coverage: pilot domain
- Historical availability: N/A
- Near-real-time availability: N/A
- Access mechanism: generated by UFNS from committed seeded definitions
- Licence/access restrictions: internal
- Expected latency: N/A
- Reliability: deterministic (seed + fingerprint)
- Fallback source: N/A (this is the fallback for all live sources)
- **Classification: `VERIFIED` (internal fixture)** — policy: always `SIMULATED_SCENARIO`; intensities must be derived from a named design storm or documented event (proposed D-016), not invented ad hoc.

### 3.2 Terrain

#### S12 — Copernicus DEM GLO-30 (Planetary Computer STAC)
- Purpose: preferred first pilot terrain
- Spatial resolution: 30 m (DSM incl. buildings/vegetation)
- Temporal resolution: N/A (static, single release)
- Format: Cloud-Optimized GeoTIFF
- Coverage: global, but **GLO-30 "Public" has country-level gaps — verify pilot tile coverage at ingestion**
- Historical availability: N/A (current product)
- Near-real-time availability: N/A
- Access mechanism: programmatic STAC discovery + signed asset URLs
- Licence/access restrictions: free for the general public; mandatory DLR/Airbus/Copernicus attribution notices
- Expected latency: N/A (one-time subset fetch)
- Reliability: high; vertical reference EGM2008 — confirm in metadata and record
- Fallback source: ALOS AW3D30
- **Classification: `VERIFIED`** — policy: attribution mandatory; vertical datum must be carried into the bundle manifest.

#### S13 — ALOS AW3D30
- Purpose: alternative/cross-check DSM
- Spatial resolution: 30 m
- Temporal resolution: N/A (static, versioned releases)
- Format: GeoTIFF tiles
- Coverage: global
- Historical availability: current version + prior versions on request
- Near-real-time availability: N/A
- Access mechanism: JAXA registration (EORC)
- Licence/access restrictions: JAXA terms — inspect current policy at registration
- Expected latency: N/A (tile download after registration)
- Reliability: high; voids/artifacts in steep terrain require audit
- Fallback source: Copernicus DEM GLO-30
- **Classification: `REQUIRES ACCESS`** — policy: registration + terms check.

#### S14 — FABDEM v1.2
- Purpose: bare-earth cross-check / sensitivity (buildings+forests removed)
- Spatial resolution: 30 m (resampled uniform 1″)
- Temporal resolution: N/A (static, v1.2 Jan 2023)
- Format: GeoTIFF tiles
- Coverage: global (60°S–80°N)
- Historical availability: v1.0 and v1.2 published
- Near-real-time availability: N/A
- Access mechanism: University of Bristol data repository (registration)
- Licence/access restrictions: **CC BY-NC-SA 4.0 — confirmed by this board**; commercial licence separate (Fathom)
- Expected latency: N/A (tile download)
- Reliability: high; model-derived bare-earth correction is not survey/LiDAR; vertical ref EGM2008
- Fallback source: Copernicus DEM GLO-30
- **Classification: `REQUIRES ACCESS`** — policy: `REQUIRES HUMAN VERIFICATION` — non-commercial + ShareAlike: any derived terrain redistributed with the SIH demo inherits NC-SA. Default: internal sensitivity use only (proposed D-018).

#### S15 — ISRO/Bhuvan CartoDEM
- Purpose: India-specific alternative DEM
- Spatial resolution: product-dependent (unverified)
- Temporal resolution: N/A (static)
- Format: product-dependent
- Coverage: India
- Historical availability: unclear
- Near-real-time availability: N/A
- Access mechanism: Bhuvan account
- Licence/access restrictions: Bhuvan product terms; machine access and redistribution unconfirmed
- Expected latency: unknown
- Reliability: unknown
- Fallback source: Copernicus DEM GLO-30
- **Classification: `UNCERTAIN`** — policy: audit before selection.

#### S16 — Municipal/survey LiDAR or DTM
- Purpose: required upgrade for defensible curb/street-scale hydraulics
- Spatial resolution: <1 m potential
- Temporal resolution: N/A (static survey)
- Format: point clouds/DTM rasters
- Coverage: city-specific
- Historical availability: survey-dependent
- Near-real-time availability: N/A
- Access mechanism: municipal/academic partnership required
- Licence/access restrictions: institutional agreements
- Expected latency: N/A
- Reliability: high if surveyed; currently unobtainable
- Fallback source: Copernicus DSM with explicit limitations
- **Classification: `UNAVAILABLE`** — this is the single most valuable dataset to obtain for the project's credibility.

### 3.3 Land cover, imperviousness, soils

#### S17 — ESA WorldCover 2021 v200
- Purpose: land-cover classes → roughness/loss-parameter zones
- Spatial resolution: 10 m
- Temporal resolution: N/A (2021 epoch, v200)
- Format: COG
- Coverage: global
- Historical availability: 2020 (v100) and 2021 (v200) epochs
- Near-real-time availability: N/A
- Access mechanism: anonymous direct/AWS download
- Licence/access restrictions: CC BY 4.0, attribution
- Expected latency: N/A
- Reliability: high; a class is not a measured Manning/infiltration parameter (docs state this correctly)
- Fallback source: Dynamic World (optional)
- **Classification: `VERIFIED`**

#### S18 — Dynamic World
- Purpose: optional newer land-cover sensitivity and uncertainty
- Spatial resolution: 10 m
- Temporal resolution: ~5 days (Sentinel-2 cadence)
- Format: probabilistic per-class rasters
- Coverage: global
- Historical availability: 2015–present (GEE catalog)
- Near-real-time availability: near-real-time via GEE
- Access mechanism: Google Earth Engine account
- Licence/access restrictions: CC BY 4.0 data; GEE platform terms
- Expected latency: days (image-dependent)
- Reliability: cloud-dependent class probabilities
- Fallback source: ESA WorldCover
- **Classification: `REQUIRES ACCESS`** (GEE account; avoidable for MVP).

#### S19 — HYSOGs250m
- Purpose: optional soil-group prior
- Spatial resolution: ~250 m
- Temporal resolution: N/A (static product)
- Format: GeoTIFF
- Coverage: global
- Historical availability: single release
- Near-real-time availability: N/A
- Access mechanism: ORNL DAAC anonymous download
- Licence/access restrictions: product terms + required citation
- Expected latency: N/A
- Reliability: high; coarse for the pilot, not a local infiltration measurement
- Fallback source: literature soil maps
- **Classification: `LIKELY AVAILABLE`** (terms check at download; prior only).

#### S20 — Field/municipal impervious and soil surveys
- Purpose: calibration/upgrade of loss parameters
- Spatial resolution: survey-dependent
- Temporal resolution: N/A (static)
- Format: survey products
- Coverage: city-specific
- Historical availability: unknown
- Near-real-time availability: N/A
- Access mechanism: municipal/field partnership
- Licence/access restrictions: institutional
- Expected latency: N/A
- Reliability: high if obtained
- Fallback source: literature-labelled assumptions + sensitivity runs
- **Classification: `UNAVAILABLE`** — initial parameters remain literature-derived and assumption-labelled.

### 3.4 Drainage and water infrastructure (highest-risk category)

#### S21 — Bhuvan Store urban products (NUIS/AMRUT)
- Purpose: primary-source discovery/comparison
- Spatial resolution: NUIS urban land use 1:10,000; AMRUT data listed at 1:4,000 for 232 towns
- Temporal resolution: N/A (static layers)
- Format: WMS/WMTS services
- Coverage: 232 AMRUT towns; NUIS cities
- Historical availability: current layers
- Near-real-time availability: N/A
- Access mechanism: official ISRO/NRSC web services
- Licence/access restrictions: service terms unverified; layer schema unverified
- Expected latency: N/A
- Reliability: official but unverified content
- Fallback source: `india-geodata` mirror (secondary)
- **Classification: `UNCERTAIN`** — a map-service layer is not necessarily downloadable or hydraulically attributed; schema/terms unverified.

#### S22 — `india-geodata` urban water collection (WB AMRUT drains + vents, SBM)
- Purpose: fast candidate for pilot data audit
- Spatial resolution: vector linework/points (1:4,000 per source programme)
- Temporal resolution: N/A (static extract)
- Format: Parquet/PMTiles/compressed GeoJSONL (WB drains ~15 MB, vents ~0.4 MB Parquet — verified by this board)
- Coverage: West Bengal AMRUT towns (drains + **vent points** — the reason WB is the preferred audit order); SBM stormwater layers
- Historical availability: current extract only
- Near-real-time availability: N/A
- Access mechanism: GitHub releases, anonymous (a previous download attempt returned EOF — retryable)
- Licence/access restrictions: aggregator states India Open Government Licence, cites MoHUA/AMRUT/SBM; **primary provenance unverified**
- Expected latency: N/A
- Reliability: unknown until inspected; geometry does not imply diameters, inverts, connectivity, capacity, pumps, or outlets
- Fallback source: Bengaluru OpenCity linework; OSM drains
- **Classification: `LIKELY AVAILABLE`** — policy: **`REQUIRES HUMAN VERIFICATION`** — secondary 2026 aggregator; primary provenance, attributes, coverage, and licence must be verified against the issuing programme before any public display.

#### S23 — Bengaluru Stormwater Drains (OpenCity)
- Purpose: alternate pilot plan geometry (primary/secondary/tertiary/combined)
- Spatial resolution: vector linework (2022)
- Temporal resolution: N/A (static KML, 2022)
- Format: KML
- Coverage: Bengaluru
- Historical availability: current release
- Near-real-time availability: N/A
- Access mechanism: public download
- Licence/access restrictions: dataset-specific licence; primary authority must be checked
- Expected latency: N/A
- Reliability: official publication; expect missing dimensions/inverts/inlets/outlets and possibly disconnected geometry
- Fallback source: OSM drains; synthetic fixture
- **Classification: `LIKELY AVAILABLE`** — policy: licence/authority check; treat as plan geometry only.

#### S24 — OpenStreetMap drains via Overpass
- Purpose: supplement and topology comparison
- Spatial resolution: vector (`waterway=drain`, culverts, manholes/inlets where mapped)
- Temporal resolution: N/A (extract frozen at download)
- Format: OSM XML/GeoJSON via Overpass
- Coverage: global, completeness highly variable; underground systems commonly missing
- Historical availability: full history API
- Near-real-time availability: N/A
- Access mechanism: anonymous Overpass (public fair-use limits)
- Licence/access restrictions: ODbL 1.0, attribution + share-alike database obligations
- Expected latency: N/A
- Reliability: variable; not a capacity model
- Fallback source: none (supplement only)
- **Classification: `VERIFIED`** — policy: freeze extracts for reproducibility; attribution required.

#### S25 — Human-supplied SWMM `.inp` / municipal asset GIS
- Purpose: best path to real drainage hydraulics
- Spatial resolution: asset-level
- Temporal resolution: N/A (static assets)
- Format: SWMM `.inp`, GIS
- Coverage: city-specific
- Historical availability: unknown
- Near-real-time availability: N/A
- Access mechanism: municipal/academic partnership (team must actively seek)
- Licence/access restrictions: institutional; sensitive-infrastructure constraints
- Expected latency: N/A
- Reliability: high if validated; must check CRS/vertical datum, units, connectivity, calibration
- Fallback source: audited open linework + assumed parameters; synthetic fixture
- **Classification: `UNAVAILABLE`**

#### S26 — Deterministic synthetic network fixture (internal)
- Purpose: solver verification + guaranteed four-scenario demo
- Spatial resolution: fully parameterised nodes/links
- Temporal resolution: N/A (static design)
- Format: generated from committed seed/design
- Coverage: small synthetic urban catchment
- Historical availability: N/A
- Near-real-time availability: N/A
- Access mechanism: generated by UFNS
- Licence/access restrictions: internal
- Expected latency: N/A
- Reliability: deterministic; documented design
- Fallback source: N/A (this is the fallback for all real drainage data)
- **Classification: `VERIFIED` (internal fixture)** — policy: always `SIMULATED_SCENARIO`; automated prohibition of synthetic-as-real labels.

### 3.5 Roads, buildings, facilities

#### S27 — OSM via OSMnx
- Purpose: pilot road graph, buildings, POIs
- Spatial resolution: vector (road-level)
- Temporal resolution: N/A (extract frozen at download)
- Format: OSM PBF → graph
- Coverage: global; completeness varies
- Historical availability: full history
- Near-real-time availability: N/A
- Access mechanism: anonymous Overpass/OSMnx (fair-use limits)
- Licence/access restrictions: ODbL with attribution; OSMnx speed imputation is not observed traffic — flag it
- Expected latency: N/A
- Reliability: high geometry quality; speed/access tags incomplete
- Fallback source: `india-geodata` road centerlines (cross-check)
- **Classification: `VERIFIED`** — policy: versioned freeze; attribution; imputed speeds flagged in UI.

#### S28 — `india-geodata` urban roads
- Purpose: cross-check or alternative centerlines
- Spatial resolution: vector (AMRUT/Bhuvan NUIS/Telangana CDMA)
- Temporal resolution: N/A (static extracts)
- Format: Parquet/PMTiles/GeoJSONL (large assets)
- Coverage: national/select cities
- Historical availability: current extracts
- Near-real-time availability: N/A
- Access mechanism: GitHub releases, anonymous
- Licence/access restrictions: aggregator cites source-specific licences; actual asset licences must be verified
- Expected latency: N/A
- Reliability: unknown; topology/routing attributes unverified
- Fallback source: OSM
- **Classification: `LIKELY AVAILABLE`** — policy: primary licence verification before use.

#### S29 — Municipal emergency facilities
- Purpose: reviewed route destinations and vulnerability overlays
- Spatial resolution: point facilities
- Temporal resolution: N/A (static registry)
- Format: GIS registry
- Coverage: city-specific
- Historical availability: unknown
- Near-real-time availability: N/A
- Access mechanism: municipal/authority cooperation
- Licence/access restrictions: institutional
- Expected latency: N/A
- Reliability: authoritative if obtained
- Fallback source: OSM facilities (reference only, not authoritative)
- **Classification: `UNAVAILABLE`** (OSM proxy is a labelled reference, as the docs already state).

### 3.6 Historical flood reference / evaluation

#### S30 — NRSC flood products / NDEM
- Purpose: event discovery, broad extent comparison
- Spatial resolution: product-dependent
- Temporal resolution: event-based
- Format: public map products
- Coverage: major Indian flood events
- Historical availability: archive of events
- Near-real-time availability: current event products
- Access mechanism: public pages; layer-level access unconfirmed
- Licence/access restrictions: layer-level audit required
- Expected latency: event-dependent
- Reliability: official; often fluvial/regional rather than pluvial street flooding
- Fallback source: Sentinel-1 derived extent
- **Classification: `UNCERTAIN`**

#### S31 — India Flood Inventory (hydrosenselab)
- Purpose: select historical events; document impacts/causes
- Spatial resolution: event polygons (not time-resolved depth)
- Temporal resolution: event-based (1960s–2020)
- Format: GitHub-hosted GIS
- Coverage: 1,006 multi-source Indian flood events
- Historical availability: 1960s–2020
- Near-real-time availability: N/A
- Access mechanism: anonymous GitHub
- Licence/access restrictions: CC BY 4.0 per repository metadata
- Expected latency: N/A
- Reliability: multi-source inventory; not urban water-depth truth
- Fallback source: NRSC products
- **Classification: `VERIFIED`** — policy: inventory ≠ time-resolved urban water depth truth.

#### S32 — Sentinel-1 GRD (Copernicus Data Space / Planetary Computer)
- Purpose: independent historical extent derivation
- Spatial resolution: 10 m (post-processing)
- Temporal resolution: 6–12 day revisit (orbit-dependent)
- Format: GRD/SLC → derived masks
- Coverage: global
- Historical availability: 2014–present
- Near-real-time availability: NRT data access possible with registration
- Access mechanism: free registration (CDS) or signed STAC assets (MPC)
- Licence/access restrictions: Copernicus full/open terms, attribution
- Expected latency: hours–days for derived maps
- Reliability: urban double-bounce/layover/permanent-water complications; derived masks are not depth observations
- Fallback source: Sentinel-2 (cloud-limited)
- **Classification: `LIKELY AVAILABLE`**

#### S33 — Sentinel-2
- Purpose: cloud-free extent/land-cover context
- Spatial resolution: 10 m
- Temporal resolution: ~5 day revisit
- Format: optical imagery
- Coverage: global
- Historical availability: 2015–present
- Near-real-time availability: NRT with registration
- Access mechanism: free registration (CDS) or signed STAC assets (MPC)
- Licence/access restrictions: Copernicus full/open terms, attribution
- Expected latency: N/A (historical)
- Reliability: monsoon cloud and revisit timing often prevent peak-flood observation
- Fallback source: Sentinel-1
- **Classification: `LIKELY AVAILABLE`**

#### S34 — Field flood marks / gauges / CCTV / crowdsourced depth
- Purpose: calibration/validation of depth predictions
- Spatial resolution: point observations
- Temporal resolution: timestamped events
- Format: surveys/images
- Coverage: city-specific
- Historical availability: unknown
- Near-real-time availability: potential (crowdsourced)
- Access mechanism: field campaigns / partnerships
- Licence/access restrictions: institutional
- Expected latency: N/A
- Reliability: must verify location, datum, time, uncertainty
- Fallback source: none (this is the missing ground truth)
- **Classification: `UNAVAILABLE`** — the absence of timestamped depth observations is the reason no flood metric may be reported; the docs state this correctly.

### 3.7 Classification summary

| Code | Sources |
|---|---|
| `VERIFIED` | S03, S10, S11, S12, S17, S24, S26, S27, S31 |
| `LIKELY AVAILABLE` | S19, S22, S23, S28, S32, S33 |
| `REQUIRES ACCESS` | S01, S04, S05, S06, S08, S09, S13, S14, S18 |
| `UNCERTAIN` | S02, S07, S15, S21, S30 |
| `UNAVAILABLE` | S16, S20, S25, S29, S34 |

**Implication:** the demo path is fully executable today with `VERIFIED` sources (Copernicus DEM, ESA WorldCover, OSM, internal fixtures, demo rainfall). Everything that requires access or is uncertain affects only **live mode, historical evaluation, and real-drainage credibility** — exactly the layers the architecture defers with honest labelling.

---

## 4. Data policy gate

### 4.1 Items requiring human verification (STATUS = REQUIRES HUMAN VERIFICATION)

1. **IMD API terms and access** (S01) — request via nodal officer; unknown terms/latency/resolution until granted.
2. **IMD radar machine feed** (S02) — no confirmed licensed quantitative feed exists; this gates *live* quantitative nowcasting.
3. **`india-geodata` WB AMRUT / SBM layers** (S22, S28) — primary provenance and licence of the underlying government data must be verified before bundling or public display in the SIH demonstration.
4. **FABDEM v1.2 NC-SA implications** (S14) — whether derived (ShareAlike) terrain products are acceptable for the intended distribution; whether a commercial licence is needed.
5. **Bengaluru OpenCity drains licence** (S23) — dataset-specific terms.
6. **Bhuvan/MOSDAC/ISRO products** (S04–S07, S15, S21) — registration tiers, non-commercial restrictions, redistribution terms.
7. **UK EA benchmark input datasets** (8A/8B) — the report is public; the test inputs' reuse terms must be confirmed, or the cases reconstructed from the published specifications.
8. **Copernicus DEM attribution strings** (S12) — mandatory notices must appear in dashboard, docs, and any distributed screenshots.
9. **OSM attribution/share-alike** (S24, S27) — attribution UI element + derived-database obligations (frozen extracts; no re-publication of unprocessed bulk OSM).

### 4.2 Bundling rules (board endorsement)

- Only small, licence-compatible, deterministic fixtures under `data/demo`. Raw/processed downloads stay out of Git (immutable manifests, checksums, external storage). Already specified; keep it.
- Anything NC-SA (e.g., FABDEM-derived) must **not** be committed or redistributed until the human decision above is recorded.
- API keys/credentials never in Git; `.env.example` only. Already specified.

### 4.3 SIH demonstration use

Demo forcing, DEM (Copernicus with attribution), land cover (CC BY 4.0), roads (ODbL attribution), and the synthetic network are all usable in the SIH demo with attribution. Real-drainage linework (S22/S23) is usable in the demo **only after** a recorded primary-source licence audit, and any assumed hydraulic attributes must be labelled simulated. This is consistent with the docs; the board elevates the licence audit from "should" to a hard precondition for displaying third-party drain linework.

---

## 5. Scientific model audit

### 5.1 The chain, stage by stage

| Stage | Equation/model | Inputs | Outputs | Status |
|---|---|---|---|---|
| 1. Rainfall | Interval mean rate field; persistence `R(t0+τ)=R(t0)` | Source fields, `[valid_from, valid_to)`, provenance | `r` (m/s) per cell | Fully specified (Baseline 1). ML/stats baselines deferred by design. |
| 2. Losses | Interception/microstore `ΔD = min(D_max−D, rΔt)`; Horton `f = f_min + (f_0−f_min)e^(−kt)`; ledger-authoritative allocation | `r`, cover/soil parameters | `r_e` (effective rain), store states | Equations specified; **parameter values TBD from literature**; Green–Ampt alternative documented. |
| 3. Surface flow | Local-inertial shallow-water approximation (Landlab `OverlandFlow`, de Almeida et al. 2012); continuity + momentum with adaptive CFL timestep | `r_e`, DEM, Manning `n`, boundaries | `h`, `q_x`, `q_y` per cell/link | Method chosen (pending spike). The momentum equation shown in the doc is the **Bates et al. (2010) form**; the chosen component implements the **de Almeida et al. (2012) stabilised variant (θ term)** — documentation must be aligned to the component's actual discretisation (finding B15). |
| 4. Drainage interaction | Signed head-driven orifice relation (design direction, not approved), capped by available volume/capacity; equal-and-opposite ledgers | `η_s`, `H_d`, inlet geometry/state | `Q_ex` per exchange ID | **Formulation not yet selected** — correctly labelled; coupling spike mandatory. |
| 5. Drainage | EPA SWMM 5.2 dynamic wave (1-D Saint-Venant) via Python toolkit; subcatchment rainfall-runoff disabled | Lateral inflow, network geometry, controls | Node head/depth, link flow, flooding, outfall flow | Engine chosen (pending spike); hydraulically complete only where real attributes exist. |
| 6. Surcharge/overflow | SWMM ponding + controlled transfer back to mapped surface cells | SWMM state, ponded volume | Surface source term | Spike-pending; mass-accounting subtleties of `node.flooding` documented in §5.4. |
| 7. Depth/velocity | `h = max(0, η−z)`; velocity null/flagged below wet threshold | `η`, `z` | Snapshots | Specified; wet/dry threshold TBD from tests. |
| 8. Road impact | max/p95 depth + wet-length sampling; configurable penalty/closure cost model; graph routing | Depth raster, road graph, vehicle profile | Road risk, routes, alerts | Specified; **passability thresholds TBD** (correctly not derived from the severity legend). |

**Vagueness check:** No stage is described as "AI will predict it" or similar. Every open item is an explicit, status-labelled parameter or a scheduled spike. The two genuinely missing scientific definitions are (a) demo rainfall scenario hyetographs and (b) the inlet formulation — both flagged by the board as pre-implementation decisions (D-016; Phase 4 spike).

### 5.2 Units, boundary conditions, initial conditions

- Units: SI throughout with an explicit mm/h → m/s conversion and tolerance-tested unit tests. Correct.
- Initial conditions: zero surface water above terrain (warm start optional); SWMM empty; microstore zero. Sensible and stated.
- Boundary conditions: reviewed open/closed surface boundaries; outfall stage boundaries; closed/flap-gate options. Sensible; boundary-sensitivity testing required (already specified). Coastal tide is correctly deferred.

### 5.3 Parameters

The parameter register (`MODEL_ASSUMPTIONS.md` §13) is the right mechanism: every TBD (Manning mapping, Horton triplets, depression storage, wet threshold, inlet coefficients, closure thresholds, mass gates) is status-labelled and requires literature citation or scenario labelling. The board endorses the rule "parameters must be selected from data/literature and approved, not invented during coding" and recommends making it a **code-review checklist item**, not just a doc statement.

### 5.4 Known limitations (board additions)

- Landlab `OverlandFlow`'s `rainfall_intensity` is a **uniform scalar** (verified against the component API): spatially variable 15-min rainfall fields and per-cell Horton losses must be applied **by the adapter** (per-cell depth increment / removal), ledger-accounted, and stability-tested. This is an implementation-critical detail the docs do not yet mention (blocker B06; proposed D-019).
- SWMM's reported node flooding rate is an **unrestricted mass imbalance** (community-documented): the coupling must reconcile ponded-volume changes against transferred volumes, or it will silently create/destroy water. This is exactly the failure the spike's conservation tests are designed to catch — the board confirms the spike is mandatory, not optional.
- Landlab boundary outflow is not directly reported by the component; the adapter must integrate boundary-link discharges for the ledger.

---

## 6. Mass-conservation review

### 6.1 Intended relationship

The docs define a complete whole-system identity:

`V_rain + V_external_in + V_surface,0 + V_drain,0  =  V_infiltration + V_surface_boundary_out + V_drain_outfall + V_microstore,final + V_surface,final + V_drain,final + ε`

with the surface–drain exchange defined to cancel exactly (equal-and-opposite per exchange ID), evaporation omitted over the 3-hour horizon (stated), and component/interval ledgers retained for error localisation.

### 6.2 How errors will be detected

- Residual `ε` and relative error `e_rel` computed every run; proposed gates: pass ≤1%, warning ≤5%, fail >5%, plus an absolute-volume check for near-dry runs.
- Per-component ledgers (surface, SWMM, exchange, losses, boundaries) retained to locate the source of any residual.
- SWMM's own runoff and flow-routing continuity reports parsed and stored.
- Fail-stop on NaN, material negative depth, or unacceptable continuity error.
- Benchmark tests: exact closed-bowl volume, one-cell exchange conservation, timestep-halving convergence, 0/25/50/100% blockage monotonicity only where the network allows it.

### 6.3 Board verdict

**STATUS = NOT A BLOCKER.** The architecture provides a defensible mass-conservation design that is *more* rigorous than typical student work: identity, detection, localisation, gates, and verification tests are all specified.

Two conditions attach to this verdict:

1. The 1%/5% thresholds are engineering proposals pending benchmark evidence; they must be set from measured numerical behaviour (convergence tests, dry-run behaviour) and **never loosened silently to pass** — the docs already say this; the board adds that threshold changes require a `DECISIONS.md` entry with evidence.
2. The three measurement subtleties in §5.4 (scalar-rainfall adapter, SWMM flooding semantics, Landlab boundary flux) must be resolved in the Phase 1 spike; if the spike cannot achieve interval-level closure, the coupling design itself must be reviewed — the roadmap's stop condition covers this.

---

## 7. Hydraulic / drainage review

| Question | Answer in the proposal | Board verdict |
|---|---|---|
| What is a node? | `DrainageNode`: inlet / junction / storage / outfall with geometry, ground & invert elevation, max depth, inlet capture def, `parameter_status` | Adequate. Board addition: a typed `node_type` enum plus explicit **ponded area** per node is needed before Phase 4 (SWMM ponding depends on it). |
| What is an edge? | `DrainageLink`: from/to node, linestring, length, shape, dimensions, `n`, slope, blockage fraction, `parameter_status` | Adequate. Flow direction must be evidenced (topology + invert sign), as the audit requirements already demand. |
| What data defines each? | Geometry + hydraulic attributes, each status-labelled measured/published/derived/assumed | Correct and honest. |
| How is pipe capacity represented? | Shape/dimensions + Manning `n` inside SWMM (not a fixed per-edge number) | Physically credible. |
| How is slope represented? | From invert elevations (assumed where absent) | Correct; vertical-datum reconciliation with the DEM is the critical precondition (already gated). |
| How is flow calculated? | SWMM dynamic wave (1-D Saint-Venant: pressurisation, backwater, reversal) | Correct choice for the stated purpose. |
| How is surcharge detected? | Head above rim → ponding/flooding; `DrainageState` carries `surcharge_m3_s`, `capacity_ratio`, state enum | Adequate. |
| How does water leave the network? | Outfall nodes with stage boundaries; outfall flows in the ledger | Correct. |
| How does water return to the surface? | Signed two-way exchange: SWMM ponded volume transferred to mapped surface cells when `H_d > η_s` | Direction correct; formulation spike-pending. |
| How are blocked drains represented? | Actual hydraulic controls/orifice opening changes at 0/25/50/100%, not just a status label | Scientifically correct; roughness-only blocking rightly rejected as a universal proxy. |
| How are outlets/boundaries represented? | SWMM outfalls with stage boundary; flap gates where known | Adequate. |

**Model type classification:** *physically based engine (1-D dynamic wave) with scenario-assumed parameters.* The docs' terminology does not over-claim: they never call assumed-attribute networks "actual capacity". This is the correct level of rigour for a screening prototype.

**Residual risk:** with absent inverts/dimensions the network is physically meaningless even in relative terms (an assumed 1 m pipe vs 0.5 m pipe changes everything). The synthetic fixture and the `ASSUMED_PARAMETER` labelling policy handle this correctly, but the board insists on the stated audit metric: **the percentage of parameters that are measured/published/derived/assumed must be displayed in the UI for every run.**

---

## 8. Surface-water model review

| Item | Proposal | Board verdict |
|---|---|---|
| DEM preprocessing | No indiscriminate pit filling (D-014); reviewed conditioning with before/after reports | Correct — urban pluvial flooding *is* depression filling; preserving depressions is the scientifically right call. |
| Sinks/depressions | Represented by the DEM + solver; micro-store must not double-count | Correct; add a depression-accounting test (disconnected depressions benchmark). |
| Flow direction/accumulation | Not used for routing (solver-based); available for diagnostics | Correct — D8-style routing would not be defensible for surcharge/backwater. |
| Slope | From DEM (DSM caveat stated) | Correct with stated caveat. |
| Roughness | Manning `n` mapped from land cover with cited ranges | Correct; spatially variable `n` in Landlab must be confirmed in the spike (component default is a uniform scalar). |
| Infiltration | Horton (Green–Ampt alternative documented) | Acceptable for MVP with sensitivity runs; parameter sourcing is the real risk, not the equation. |
| Imperviousness | Via land-cover classes → loss/roughness zones | Honest; not presented as measured. |
| Surface storage | Micro-store + DEM depressions | Correct. |
| Drainage inlets | Mapped surface cells with two-way exchange | Correct design; formulation spike-pending. |
| Timestep | Adaptive CFL, `α` initial 0.5 within the documented 0.2–0.7 range | Correct; `α` is a numerical test value, not physics — the docs state this. |
| Stability | θ-weighted de Almeida stabilisation, wet/dry threshold TBD | Correct; threshold must be a documented tested value. |
| Boundary conditions | Reviewed open/closed; no hidden sources | Correct. |

**Terminology verdict:** the proposal is **genuinely a 2-D local-inertial shallow-water approximation** (storage-cell scheme with staggered link discharges), not a raster redistribution heuristic — and the docs' own wording is precise about this ("reduced-physics", "local-inertial approximation", "D4 link flow"). No over-claim found. The board flags only that the momentum equation written in `MODEL_ASSUMPTIONS.md` §5.2 is the Bates et al. (2010) form while the chosen component implements the de Almeida et al. (2012) stabilised form; the documentation should quote the component's published discretisation including the θ term (finding B15).

---

## 9. Rainfall nowcasting review

### 9.1 Method comparison (as applied to the actual data situation)

| Approach | Data needed | Achievable horizon | Achievable resolution | Verdict at Phase 0 |
|---|---|---|---|---|
| Persistence | One current verified rain field | Decays with storm motion; minutes–tens of minutes of genuine skill | Native source resolution (~10 km today) | **Baseline 1 — implement first. Correct choice.** |
| Statistical/advection (optical flow, exponential smoothing) | Frequent georeferenced fields (radar imagery) | Up to ~30–60 min in convective cases | Source-limited | Defer behind persistence; needs data audit first. Correct order. |
| Radar extrapolation | Quantitative radar rain-rate feed | 30–90 min (storm-dependent) | ~1 km | **Blocked on data (S02 UNCERTAIN).** Do not schedule until a feed is verified. |
| ML (e.g., U-Net/ConvLSTM on rain fields) | Long homogeneous training sequence + ground truth | Comparable to advection; sometimes better at 1–2 h | Model/resolution-limited | **Out of MVP. Correctly deferred.** No GPU, no dataset, no baseline yet. |
| Deep learning on raw imagery | Even larger datasets | — | — | Stretch only. |

### 9.2 The seven questions

1. **What data is available?** Demo scenario rainfall (guaranteed), IMERG/GSMaP-ISRO historical (delayed, coarse), Open-Meteo NWP (labelled), IMD on approval. No verified quantitative low-latency radar feed.
2. **What forecast horizon is achievable?** With persistence on a current field: short lead only (skill decays with advection time). With radar: ~0–60 min defensible. **0–180 min quantitative nowcasting is not achievable with any confirmed data today**; the honest 180-min product is scenario forcing (demo) or labelled external NWP.
3. **What spatial resolution?** ~10 km with confirmed products; street scale unachievable without radar/gauge-density work.
4. **What training data exists?** None confirmed in-repo or verified accessible.
5. **What ground truth exists?** IMD gauges (access-gated); no independent dense gauge product confirmed.
6. **What baseline will be used?** Persistence — defined with rolling-origin evaluation, lead-stratified metrics, rain/no-rain skill. Correct.
7. **What metric decides ML is better?** Not yet defined. Board proposal: CSI/FSS at ≥2 lead bins + intensity-binned MAE, evaluated on rolling-origin held-out events, with leakage-safe splits and a pre-registered improvement threshold over persistence **before** any ML is admitted. This metric decision belongs in `DECISIONS.md` when a training sequence actually exists.

### 9.3 Recommendation

**Baseline-first is confirmed as correct.** The project must not introduce a neural network merely because SIH mentions AI/ML. The defensible "AI/ML story" for SIH26085 is the *coupled physical model itself* plus honest baselines — and, if data materialises, a verified nowcast improvement. The board endorses D-010 as written and adds: no ML code may be written before a documented dataset and a pre-registered evaluation protocol exist.

---

## 10. Validation audit

### 10.1 Model validation (does the flood model behave correctly?)

Well specified: analytical closed-bowl volume, wetting/drying, planar-slope runoff, one-cell exchange equilibrium, SWMM example regression, blockage hydraulic-change tests, EA Tests 8A/8B (staged, subject to dataset access), timestep/cell-size/parameter sensitivity, fail-stop rules. **Verdict: strong; verification-first and correct.** Board additions: (a) axis-order unit tests in Phase 1 (not Phase 9); (b) every benchmark test must record mass residual, not just visual agreement; (c) sensitivity results must be published in `docs/BENCHMARKS.md` with hardware/versions.

### 10.2 Prediction validation (do predictions match observations?)

Correctly unavailable: no independent aligned reference exists. The docs state the exact disclosure sentence for the UI. **Verdict: honest.** The board requires that this remains a hard rule: no metric is emitted until an independent reference is ingested with code + artifacts.

### 10.3 System validation (does the pipeline work?)

Specified as integration tests asserting lineage + mass ledger, API contract tests, failure-path tests, E2E judge flow. **Verdict: adequate.**

### 10.4 Demonstration validation (does the demo reproduce the same result?)

Run fingerprinting (input/model/parameter/forecast-issue hash), deterministic seeds, cached identical artifacts, clean-environment rebuild. **Verdict: adequate**, with one addition: the demo script must print the run fingerprint and mass-balance status on screen so judges can see reproducibility live.

### 10.5 Metric table — no invented thresholds

| Metric | Ground truth | Dataset | Period | Spatial scale | Temporal scale | Acceptance threshold |
|---|---|---|---|---|---|---|
| Rain MAE/RMSE (mm/h), CSI/FSS by lead bin | Observed/estimated rain fields | Not yet ingested (IMERG/GSMaP/IMD candidates) | To define when data exists | ~10 km | 30 min–1 h | **Not set.** Set only after reference data exists and the baseline is evaluated. |
| Flood extent IoU / precision / recall / F1 | Independent flood maps (Sentinel-1-derived or official) | Not yet ingested | Event-based, held-out | Pilot domain | Event peak + sequence | **Not set.** Never inferred from literature figures. |
| Depth MAE/RMSE | Timestamped depth observations | UNAVAILABLE | — | Point/street | Event | **Not set.** Report "evaluation unavailable" honestly. |
| Mass residual | Ledger identity | Every run | All | Whole domain + components | Per interval + whole run | Proposed 1%/5% + absolute test — **pending benchmark evidence**; revise only with evidence + decision-log entry. |
| Benchmark 8A/8B agreement | Published benchmark results | EA SC120002 report + inputs (to locate) | Specified in report | Urban test domain | Event | **Not set** — define quantitative agreement criteria (e.g., inundation extent/depth error bands vs published package results) before running. |
| Routing correctness | Analytically known shortest paths | Toy graphs (internal) | Unit | Graph | N/A | Exact assertions (no threshold needed). |

---

## 11. Pilot area audit

**Verdict: the pilot strategy is appropriate, with conditions.**

- The docs correctly **challenge the whole-metropolitan-city temptation** and propose a ~4 km × 4 km subset. Endorsed: a full Kolkata/Bengaluru megacity would break the compute budget and force data fabrication.
- **Preferred order (endorsed):** (1) a small West Bengal AMRUT urban area — because vent points exist, making the surface/drain exchange demonstrable; (2) Bengaluru subset — public drain linework hierarchy; (3) human-supplied city if the team has stronger data; (4) synthetic fixture always, as the guaranteed scientific demonstration.
- **Conditions attached by the board:**
  - Pilot acceptance requires a written audit: schema, bounds, geometry validity, licence, attribute coverage (diameter/invert/inlet/outlet % present), terrain/road overlap, and an explicit statement of the assumed-parameter percentage.
  - The DEM tile must actually cover the pilot (Copernicus GLO-30 Public has country-level gaps — verify).
  - If WB AMRUT inspection shows linework-only coverage (no usable vents or attributes), **move to Bengaluru without delay** — the decision rule already exists; apply it.
  - The pilot must contain a natural drainage outlet (receiving water body or domain edge) — a fully landlocked 4×4 km box makes boundary conditions arbitrary.
- The board does **not** recommend an immediate switch to any whole city, including Kolkata.

---

## 12. Scientifically Credible MVP

The smallest system that proves the SIH26085 idea: *rainfall → runoff → surface flow → drainage interaction → flood depth → GIS visualisation*, with blockage demonstrably changing the result and mass accounted.

### MUST HAVE

1. Deterministic seeded rainfall scenarios on the canonical grid (15-min forcing, documented design derivation — see D-016).
2. Versioned pilot bundle: DEM (30 m, attributed), land cover, roads, **status-labelled** drainage (synthetic fixture guaranteed).
3. Loss model (micro-store + Horton) with full ledger accounting and unit tests.
4. Landlab local-inertial 2-D surface routing with adaptive stepping, tested (closed bowl, wetting/drying, planar flow, sensitivity).
5. EPA SWMM dynamic-wave drainage with a verified Python interface (spike gated).
6. Conservative two-way inlet/surcharge exchange with per-exchange-ID ledger cancellation (spike gated).
7. Hydraulic blockage scenarios (0/25/50/100%) that change flow, not just UI state.
8. Per-run mass-balance diagnostics passing reviewed gates.
9. Road-depth sampling + routing whose costs/closures actually change with flood depth (exact toy-graph tests).
10. MapLibre dashboard: timeline (now…+180 min), provenance badges, scenario comparison (extreme vs extreme+blockage), explicit limitations.
11. Reproducible clean-environment demo + honest "no independent validation data" disclosure.

### SHOULD HAVE

12. Persistence rainfall forecast operating on replay/demo fields with rolling-origin skill reports.
13. Labelled external NWP context layer (Open-Meteo) with source/resolution display.
14. PostGIS profile (SQLite profile acceptable for demo).
15. UK EA 8A/8B benchmark runs (subject to dataset access).
16. A real-pilot run (drains labelled assumed) beside the synthetic fixture.

### STRETCH

17. Radar advection/statistical nowcast (requires verified feed).
18. Ensemble scenario spread display (explicitly not called "probability").
19. Pumps/gates/tidal boundaries.
20. Higher-resolution DTM/building/kerb representation.

### DEFER (explicitly out of the first deliverable)

21. Any ML/DL rainfall model (no data, no baseline yet, no GPU).
22. Live-mode activation (requires verified feeds — see §13).
23. Multi-user queues, cloud storage, Kubernetes.
24. Emergency-routing claims usable in real operations (needs expert-reviewed profiles).
25. Any accuracy claim (no reference dataset).

---

## 13. Demo mode vs live mode

**The architecture already separates them; the board endorses and hardens it:**

- **DEMO MODE:** deterministic, reproducible: `scenario hyetograph + DEM + drainage network + blockage scenario → flood simulation`, labelled `SIMULATED_SCENARIO`, seeded, fingerprinted.
- **LIVE MODE:** activates **only** when a real-time quantitative rainfall feed is verified in writing (source, terms, latency, resolution). Until then the live controls show "unavailable". A failed live source shows `STALE`/unavailable — **never** a silent switch to simulated data. Already specified.
- **Board addition (proposed D-017):** because no live feed is verified today, persistence in live mode has no "current field" to persist. Persistence is therefore demonstrated in replay/historical mode only; live mode is a separate activation gate with its own checklist. The dashboard must not ship with a live toggle that feeds synthetic data.

---

## 14. AI usage audit

### 14.1 Where AI agents are appropriate (endorsed)

Scaffolding/boilerplate, typed contract generation from schemas, test harnesses (with human-approved assertions), data-processing glue, documentation, visualisation, benchmark runners, dependency/Poetry setup, CI config.

### 14.2 HIGH-RISK AI AREA labels

Every area where an LLM could produce convincing-but-wrong implementation, and the required human control:

| HIGH-RISK AI AREA | Failure mode if agent-written unchecked | Required human control |
|---|---|---|
| SWMM `.inp` generation + coupling arithmetic | Silent mass creation/loss; wrong ponding semantics; double-counted flooding | Hydraulics engineer reviews every exchange path; spike conservation tests are gatekeepers |
| Inlet weir/orifice formulation + regime switching | Physically plausible but wrong discharge law | Cited formulation + regime-transition tests; human sign-off (Phase 4 gate) |
| CRS / vertical-datum / unit conversions | Confusing EGM2008 vs local datum; mm/h vs m/s errors; axis-order bugs | Unit/CRS test fixtures; ingestion report reviewed by human |
| Raster resampling/remapping logic | Conservative remapping errors; claiming false resolution | Round-trip volume tests; resampling flagged `RESAMPLED`; human GIS review |
| Mass-ledger accounting | Forgetting a term (microstore, boundary flux) that balances by luck | Ledger identity is a reviewed contract; dry/extreme tests |
| Adaptive timestep / stability tweaks | "Fixing" instability by silently raising α or wet threshold or lowering physics | Timestep-halving convergence evidence; parameter changes require decision-log entry |
| Evaluation metric computation | Leaky splits, wrong alignment, metrics on non-independent data | Metrics code reviewed; reference dataset independently verified; no threshold invented by agent |
| Licence interpretation ("it's probably fine") | Misjudging NC-SA/ODbL obligations | Human/legal review; manifest records licence + decision |
| Scenario design-storm generation | Inventing intensities and calling them "extreme" | Hyetographs derived from named cited design storms/historical events (D-016) |
| "Adjusting" a failing scientific test | Loosening tolerance or editing expected values to pass | Scientific QA gatekeeper; diff review of test expectations |
| Writing conclusions from model output | Claiming calibration/accuracy that doesn't exist | Human writes and signs all claims; model card limits |

### 14.3 Human-only decisions (never delegated to agents)

Scientific assumptions, equations, model validity, parameter selections, data licensing, validation methodology, acceptance thresholds, public claims, final interpretation. This matches the existing agent-state design; the board adds that **any** change to an equation or threshold requires a `DECISIONS.md` entry.

---

## 15. Red-team the project

| Scenario | Expected system behaviour per the Phase 0 design | Enforcing test/gate |
|---|---|---|
| A. Extremely heavy rainfall | Scenario 3; solver substeps shrink adaptively; drainage surcharges; ledger runs; if solver diverges → run **fails with diagnostics**, never silent clamping | Extreme-rain test; fail-stop rules; mass gate |
| B. Zero rainfall | Domain stays dry; microstore unchanged; zero losses/outflow; drain idle | Zero-rain dry test (specified) |
| C. Blocked drainage | Scenario 4: orifice/opening actually changed; surcharge + flood depth change vs scenario 3; explanation shown | Hydraulic-change test (specified); monotonicity only on controlled networks |
| D. Drainage data missing | Network built only from real attributes; missing fields generated under a named scenario and labelled `ASSUMED_PARAMETER`/`SIMULATED_SCENARIO`; UI shows assumed-% | Assumed-parameter audit report; provenance tests |
| E. DEM contains sinks | Depressions preserved (no blanket fill); water ponds physically; microstore doesn't double-count | Disconnected-depression benchmark; conditioning report |
| F. Rainfall and DEM CRS differ | Ingestion **rejects** (no silent guessing); human override possible only with recorded justification | CRS fail-fast tests; axis-order fixture |
| G. Rainfall timestamps delayed | `STALE` flag; persistence uses the last valid field up to configured max age; UI shows observation time and latency | Staleness tests; provenance badges |
| H. Rainfall disappears 20 min | Gap flagged `MISSING_VALUES`; **never zero-filled**; nowcast goes stale/unavailable per policy; demo unaffected (scenario forcing) | Gap-handling test (specified in red-team matrix) |
| I. Multiple drainage outlets | SWMM multiple outfalls; each outfall flow in ledger; per-outfall stage boundaries; no hidden sink | Multi-outfall conservation test |
| J. Flood depth negative | Only tested-epsilon floating undershoot clamped **and counted in diagnostics**; material negative → run fail | Non-negative depth tests |
| K. Numerical instability | θ-stabilised scheme, adaptive CFL; timestep-halving convergence evidence required; failure → run-level diagnostics, no NaN propagation to UI | Convergence/sensitivity suite |
| L. Flooded road still routed | Depth sampling → penalty/closure applied to graph; closed edges removed; explanation lists avoided edges; nodata = unknown, not dry | Routing toy-graph + flooded-edge tests (specified) |

**Architecture-level red-team (what would prove the design wrong):**

1. The SWMM coupling spike cannot reach interval-level mass closure → **stop-and-review is pre-specified**; fallback is a reviewed adapter decision, not undocumented custom hydraulics. (Board: if this fails, the documented alternative of SWMM storage nodes with ponded-area exchange driven at a single coupled timestep may be considered — a human decision.)
2. Local-inertial solver misbehaves on the actual pilot terrain (steep slopes/DSM artifacts) → sensitivity + conditioning report triggers review; synthetic fixture unaffected.
3. A 180-min run cannot complete faster than 3 h on the sandbox → benchmark-first policy + precomputed labelled fallback exist.
4. Licence audit of pilot drains fails → switch to synthetic fixture + Bengaluru/other audit; demo unaffected.
5. Copernicus DEM tile missing for pilot → ALOS AW3D30 fallback (registration) or adjacent domain.

---

## 16. Blockers and risks

| ID | Issue | Severity | Why it matters | Required resolution |
|---|---|---|---|---|
| B01 | **Phase 0 approval gates outstanding** — pilot, solvers, resolution/domain, assumed-data policy, thresholds not yet approved by the human team | BLOCKER | README + ARCHITECTURE explicitly gate implementation on human approval; the audit cannot substitute for it | Human team records decisions in `DECISIONS.md` / `PHASE0_APPROVAL.md`; only then does Phase 1 start |
| B02 | **Pilot drainage data unverified** — no candidate drain file has been inspected; hydraulic attributes almost certainly absent; one download attempt failed (EOF) | BLOCKER for Phase 2 pilot acceptance (does not block Phase 1 spikes or the synthetic demo path) | The central idea is drainage–rainfall coupling; accepting unverified linework as "the network" would fabricate capacity claims | Written pilot data audit (schema/bounds/licence/attribute coverage) before any real-pilot run; synthetic fixture in the meantime |
| B03 | **Demo rainfall scenarios undefined** — normal/heavy/extreme hyetographs have no named derivation | BLOCKER for Phase 5 scenario acceptance | Invented intensities would silently define the demo's scientific meaning | Approve D-016: design storms from cited DDF curves or documented historical events, reviewed by a hydrologist |
| B04 | **Live rainfall access unverified** (IMD API/radar, MOSDAC tiers) | HIGH (live mode; demo unaffected) | "Nowcasting" with no current field is replay, not nowcasting; must not be disguised | Parallel access requests by humans; live-mode activation gate (D-017); demo-first stays |
| B05 | **SWMM↔surface coupling unproven** — API primitives verified to exist, but operator-split order, ponding/flooding mass accounting, and stability are untested on this hardware | HIGH (could become BLOCKER) | The coupling is the scientific core; a silent mass error here poisons every result | Phase 1 spike with the pre-specified stop-and-review condition; one-cell conservation, oscillation, timestep-halving evidence |
| B06 | **Landlab rainfall input is a uniform scalar; spatially variable rain + per-cell Horton losses require adapter-level application** | HIGH (implementation-critical, undiscovered by the docs) | The documented rainfall contract is spatially variable; the component cannot consume it directly | Spike must demonstrate per-cell rain application + infiltration removal with ledger closure before Phase 3 proceeds (D-019) |
| B07 | **Mass-gate thresholds (1%/5%) have no benchmark evidence yet** | MEDIUM | Gates that fail too often halt the demo; too loose and they're theatre | Set from measured convergence/behaviour evidence; changes require decision-log entries |
| B08 | **Vertical datum reconciliation unresolved for real networks** (DEM EGM2008 vs local inverts) | HIGH for real-pilot hydraulic claims; handled for synthetic | Datum mismatch reverses hydraulic behaviour | Keep the assumed/synthetic policy; require common-datum audit before any real-network claim |
| B09 | **Copernicus GLO-30 "Public" coverage is country-incomplete** | MEDIUM | Pilot tile may be missing | Verify pilot tiles at ingestion; ALOS AW3D30 fallback |
| B10 | **FABDEM NC-SA implications for derived terrain** | MEDIUM | ShareAlike inheritance could restrict SIH demo redistribution | Human decision (policy gate §4.1.4); default: internal sensitivity use only (D-018) |
| B11 | **Problem statement not archived in-repo** | MEDIUM | Cited prompt values (30 s coupling, severity bands, horizon) are untraceable | Commit official PDF/URL + requirements summary to `docs/` |
| B12 | **EA benchmark input datasets not yet located** | MEDIUM | 8A/8B are the strongest independent verification; the report alone is insufficient | Locate/request inputs or reconstruct from published specs; record licence |
| B13 | **Vehicle passability/closure thresholds TBD** | HIGH for routing credibility; MEDIUM for demo | Routes could silently embed unsafe assumptions | Nominate disaster-management reviewer; provisional demo profile explicitly labelled |
| B14 | **No project LICENSE/.gitignore/CI** | LOW | Housekeeping; interacts with demo data licensing | Phase 1 foundation task (already planned); choose project licence with data policy in mind |
| B15 | **Momentum-equation doc shows Bates (2010) form while the component implements de Almeida (2012) stabilised form** | LOW | Documentation precision; reviewers will compare the two | Align docs to the component's published discretisation during the spike |
| R01 | **No independent flood depth/extent reference exists** | HIGH (reporting, not demo) | All accuracy claims are impossible; the docs already handle this honestly | Keep the disclosure policy; pursue Sentinel-1-derived extent + municipal flood records |
| R02 | **OSM-derived speeds/access are imputed, not observed** | LOW | Routing ETAs are demonstrative | Flag imputation in UI + route explanations |
| R03 | **Sandbox constraints (3.8 GiB, no Docker) may stress the full PostGIS profile** | LOW | Demo latency/installation | SQLite profile fallback (already designed); measure in Phase 1 |

---

## 17. Approval matrix

Maintained separately in [`PHASE0_APPROVAL.md`](PHASE0_APPROVAL.md). Every item is **PENDING**. Only the human team may change a status; changes should cite a `DECISIONS.md` entry, a date, and the reviewer.

---

## 18. Proposed decisions (no silent changes)

The board did **not** rewrite any scientific choice. Four new proposed entries were appended to [`DECISIONS.md`](DECISIONS.md), all labelled **PROPOSED**:

- **D-016** — Demo rainfall scenarios must be derived from named, cited design storms or documented historical events; no ad-hoc invented intensities.
- **D-017** — Live mode activation gate: a verified quantitative near-real-time rainfall feed must exist before live mode is enabled; persistence nowcasting is demonstrated in replay mode until then.
- **D-018** — DEM licensing posture: Copernicus DEM GLO-30 (free, attribution) as primary; FABDEM v1.2 (CC BY-NC-SA 4.0) restricted to internal sensitivity runs until the human team decides on ShareAlike-derived redistribution.
- **D-019** — Landlab adapter must implement spatially variable rainfall and per-cell infiltration application with ledger accounting (component limitation found during this audit).

Existing D-001…D-015 were reviewed and **left unchanged**; they remain proposals awaiting human approval.

*This audit is a review record. It grants no implementation authority. Implementation remains blocked until the human team records its approvals.*

---

## Overall Assessment

Implementation readiness:
**CONDITIONALLY READY**

Critical blockers:

- B01: the six Phase 0 approval gates must be resolved by the human team before implementation begins (pilot strategy, solvers, resolution/domain, assumed-data policy, thresholds, mass gates).
- B02/B03: no pilot bundle may be accepted before a written data audit, and no scenario may be accepted before its hyetographs are derived from named, cited design storms or events.
- B05/B06: the SWMM-coupling and Landlab-rainfall-application spikes carry pre-specified stop-and-review conditions; if they fail their conservation/closure tests, implementation pauses for a reviewed decision rather than proceeding on weakened physics.

Major risks:

- Real-drainage credibility is limited by unverified aggregator data and missing hydraulic attributes (mitigated by the synthetic fixture and `ASSUMED_PARAMETER` labelling).
- Live "nowcasting" is not possible with any currently verified feed; the demo must remain the primary evidence and live mode must be gated.
- No independent flood reference exists, so no accuracy metric can be reported — only numerical verification and honest disclosure.
- Passability/severity thresholds and mass gates remain expert/policy decisions that no agent may invent.

Recommended MVP:
The `MUST HAVE` list in §12: deterministic scenarios → losses → local-inertial 2-D surface flow → SWMM dynamic wave with conservative two-way exchange → blockage scenarios → mass ledger → flood-depth GIS timeline → depth-driven routing — on a ~4 km × 4 km, 30 m domain, with the synthetic hydraulic fixture guaranteeing the demonstration and real-area layers labelled by status.

Recommended pilot:
A small (≤4 km × 4 km) West Bengal AMRUT urban subregion audited first, Bengaluru subset as fallback, with the deterministic synthetic fixture always included. No whole-city domain.

Recommended first implementation milestone:
Phase 1 as planned, **after B01 approval**: repository foundation + dependency spikes (Landlab reproduction, SWMM Python interface + one-cell conservative exchange, pilot-data audit, Copernicus DEM subset), with the SWMM spike's stop condition treated as a hard gate.

Human decisions required:

1. Approve/reject the six Phase 0 gates (ARCHITECTURE §18) and record them in `DECISIONS.md` / `PHASE0_APPROVAL.md`.
2. Approve or amend proposed decisions D-016…D-019.
3. Decide the FABDEM redistribution posture and the project licence.
4. Nominate reviewers: hydrologist (losses, design storms, mass gates), drainage engineer (SWMM/coupling review), disaster-management/transport expert (passability thresholds).
5. Initiate IMD/MOSDAC access requests and municipal/academic outreach for drainage and LiDAR data.
6. Archive the official SIH26085 problem statement in `docs/`.
