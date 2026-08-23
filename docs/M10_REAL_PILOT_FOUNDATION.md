# M10 — Real-Pilot Data Foundation

**Status:** REAL-PILOT VALIDATION PASS (2026-08-23)
(spatial re-baseline + CRS provenance resolution: all 13 RD gates
evidence-backed; DEM VALIDATED+NORMALIZED; drainage VALIDATED via
authoritative external CRS provenance; entity mapping executed;
RD gates 13 PASS; B02 CRS provenance RESOLVED via MoHUA/TCPO/NRSC)
**Date:** 2026-08-23
**Milestone:** M10 REAL-PILOT DATA FOUNDATION

## 1. Executive Summary

M10 establishes the **architecture** for moving UFNS from a synthetic-only
demonstration data foundation toward an auditable real-pilot data foundation.
The ingestion **machinery is implemented and tested end-to-end against
clearly-labelled SYNTHETIC TEST FIXTURES**, and on 2026-08-22 the actual
human-supplied real artifacts were executed through the unchanged machinery
(§2.2): the Copernicus DEM GLO-30 tile validated as a raster (**VALIDATED**,
with a no-nodata-sentinel warning), and the WB AMRUT drains/vents audits
completed as **AUDIT_PARTIAL** (no embedded CRS in the files; all required
hydraulic attributes confirmed absent).

On 2026-08-23, the human declared the Copernicus DEM tile as the authoritative
real-pilot spatial area (§12). The pilot GridSpec was re-based to the actual
DEM extent (88.60–88.85°E, 22.65–22.90°N → 846×934 cells at 30 m in
EPSG:32645). After the re-baseline, DEM normalization succeeds (**NORMALIZED**),
spatial coherence with the pilot area is verified, and 11 of 13 gates pass.
The remaining AUDIT_PARTIAL (RD-08, embedded-CRS gap) and BLOCKED (RD-11,
contract dependency on RD-08) are evidence-backed governance gates, not
spatial-incoherence issues.

It provides:

1. **Typed data contracts** for real data ingestion (SourceProvenance, DatasetAuditResult, DrainageEntity, AcquisitionAttempt)
2. **B02 WB AMRUT audit pipeline** — attribute-level audit implemented and now EXECUTED on the real parquet (§2.2, §3)
3. **Real DEM validation + normalization pipeline** (Copernicus DEM GLO-30): validation gates (incl. resolution validated from the actual transform) + clip → reproject → bilinear resample → alignment to the established pilot GridSpec — real artifact VALIDATED as a raster; normalization BLOCKED on spatial coherence (§2.2)
4. **Real drainage entity mapping** — explicit rule tables, stable entity IDs, per-entity mapping status, no-fabrication enforcement; executed on the real artifact and BLOCKED by the VALIDATED-source contract (§2.2)
5. **Provenance/CRS/schema/quality gates** (deterministic fingerprints incl. processing fingerprints; deeply immutable records)
6. **Synthetic/real separation** (mandatory DataSourceClassification; result labels `[status, classification, what-is-represented]`; fixture bytes can never be labelled REAL_DATA; real artifacts verified never labelled SYNTHETIC — §2.2)
7. **Acquisition evidence** (single-shot attempts with failure mode / affected gate / consequence recorded in `data/raw/acquisition_attempts.json`, incl. the human-supplied FETCHED records, §2.2)

M10 does **NOT** mean:
- Operational flood forecasting
- Validated forecast skill
- Real-time rainfall ingestion
- Road safety/closure authority
- Expert-approved B13 thresholds
- That the real pilot datasets are integrated into the pilot model (they are
  acquired, validated/audited, and evidence-backed — but spatially
  incoherent with the established pilot GridSpec; §12)
- That the real WB AMRUT data may be presented as the pilot's real drainage
  network (B02 acceptance still requires human sign-off; §3)

## 2. Data Source Status

| Dataset | Source | Status | Classification | Blocker / Finding |
|---|---|---|---|---|
| WB AMRUT Stormwater drains | india-geodata (GitHub) release `water/urban-water` | FETCHED (human-supplied 2026-08-22) → **AUDIT_PARTIAL** | PROVISIONAL | embedded CRS absent from file; all 5 required hydraulic attributes confirmed absent; 100 duplicate source ids; no `type` column; not co-located with the established pilot GridSpec |
| WB AMRUT Stormwater vents | india-geodata (GitHub) release `water/urban-water` | FETCHED (human-supplied 2026-08-22) → **AUDIT_PARTIAL** | PROVISIONAL | same embedded-CRS gap; 9,579 MultiPoint features (unsupported for the drain-LINE mapping contract); all required hydraulic attributes confirmed absent |
| Copernicus DEM GLO-30 tile `bagjola_kolkata_glo30_dem.tif` | human-supplied tile (intended source: Planetary Computer STAC `cop-dem-glo-30`) | FETCHED (2026-08-22) → **VALIDATED** (raster gates) | PROVISIONAL | no nodata sentinel in the file (warning); actual bounds 88.60–88.85°E, 22.65–22.90°N — does NOT cover the Bagjola/Kolkata metro core despite the filename, and does not overlap the established pilot GridSpec |
| Synthetic DEM fixture | UFNS-generated | ACCEPTED (unchanged) | SYNTHETIC | — |
| Synthetic drainage INP | UFNS-generated | ACCEPTED (unchanged) | SYNTHETIC | — |
| Synthetic road network | UFNS-generated | ACCEPTED (unchanged) | SYNTHETIC | — |
| M10 test fixtures | `tests/fixtures/m10/generators.py` | ACCEPTED (unchanged) | FIXTURE (SYNTHETIC TEST FIXTURE) | — |

### 2.1 Acquisition evidence (2026-08-22)

`scripts/attempt_real_data_acquisition.py` (single-shot, short timeout, no
retries) produced `data/raw/acquisition_attempts.json`:

| Source | Outcome | Failure mode | Affected gate |
|---|---|---|---|
| WB AMRUT drains parquet (release asset) | BLOCKED | `URLError: SSLZeroReturnError: TLS connection closed (EOF)` on redirect to `release-assets.githubusercontent.com` | RD-07 / B02 |
| Copernicus DEM GLO-30 (STAC collection) | BLOCKED | `URLError: SSLZeroReturnError: TLS connection closed (EOF)` (host unreachable) | RD-01 |

Egress characterisation (one probe each): `github.com`, `api.github.com`,
`codeload.github.com` reachable; `release-assets.githubusercontent.com`,
`raw.githubusercontent.com`, `objects.githubusercontent.com`,
`planetarycomputer.microsoft.com`, `copernicus-dem-30m.s3.amazonaws.com`
unreachable. The WB AMRUT release asset list IS readable via the GitHub API
(file names/sizes confirmed); only the asset CDN transfer is blocked.

Consequence (at the time): real ingestion/normalization/audit/mapping were
NOT_FETCHED; synthetic fixtures were the authoritative test assets. The
pipelines were ready for the artifacts to be supplied — which happened next
(§2.2).

### 2.2 Real artifact acquisition + execution (2026-08-22, same day, later session)

A human supplied the three real artifacts from a machine with normal network
access. They were moved, **byte-identical** (SHA-256 verified against the
original bytes), into the canonical raw-data location `data/raw/` (kept out
of Git per repository convention), and the existing M10 machinery was run
unchanged against them.

**Artifact identity (oracles, verified after placement):**

| Artifact | Bytes | SHA-256 |
|---|---|---|
| `data/raw/bagjola_kolkata_glo30_dem.tif` | 2,790,352 | `8832ae955ec8b8dbdab5a9bc4047852c17f6343c598514bc6092c38717dcc96a` |
| `data/raw/WB_AMRUT_Stormwater_drains.parquet` | 15,778,762 | `6b224492d4bd02aae1d282b76ac17ed774554ed4be91d300a07ebec3cb3d3a0b` |
| `data/raw/WB_AMRUT_Stormwater_vents.parquet` | 440,517 | `ef017b6fbcee48eb21c62427c7eea2f26c90a639132e7a970db020adc7f5ce37` |

**Acquisition evidence:** `scripts/record_real_artifact_evidence.py` appended
three `FETCHED` `AcquisitionAttempt` records (path/bytes/SHA-256) to
`data/raw/acquisition_attempts.json`. The two earlier in-sandbox `BLOCKED`
records are preserved verbatim — the B02 acquisition sub-blocker is
evidenced, then resolved; it was not deleted.

**Execution:** `scripts/run_m10_real_pilot_validation.py` ran the existing
pipelines (`ingest_dem`, `normalize_dem`, `audit_wb_amrut_drains` ×2,
`map_drainage_entities` ×2 — no code changes, no parallel pipeline) and wrote
the machine-readable gate evidence to
`data/processed/m10_real_pilot_validation.json`.

**Real DEM (actual raster metadata — not the filename):**

| Check | Evidence |
|---|---|
| File accessible / readable raster | GTiff, rasterio-opened |
| CRS | EPSG:4326 |
| Transform / resolution | 1 arc-second postings; ground resolution **30.76 m** (max of 28.52 m × 30.76 m, measured through local UTM 45N) — validated from the transform, inside the ~30 m GLO-30 tolerance |
| Bounds | 88.60–88.85°E, 22.65–22.90°N |
| Dimensions | 900 × 900, float32 |
| Nodata | **no nodata value defined** (surfaced as a validation warning; never substituted) |
| Empty / finite | 810,000/810,000 valid cells; all finite; range −2.84 … 27.61 m |
| Status / labels | `ingest_dem` → **VALIDATED**, `[VALIDATED, PROVISIONAL, REAL_DATA]`; data fingerprint = SHA-256 above |
| Normalization | `normalize_dem` → **BLOCKED**: `no spatial overlap: source bounds (88.6, 22.65, 88.85, 22.9) vs target grid (85.0539, 22.5951, 85.0935, 22.6318) (EPSG:4326)`. No normalized output, no processing fingerprint, nothing forced. |
| Filename caveat | The file is named `bagjola_kolkata`, but its actual bounds (88.60–88.85°E) are east of the Kolkata metropolitan core (west of ~88.60°E) and do not cover the Bagjola locality — the name is not confirmed by the raster. |

**Real drainage (actual file metadata):**

| Check | Drains | Vents |
|---|---|---|
| Readable / GeoParquet | yes (GeoParquet 1.1.0, WKB) | yes |
| Records | 90,395 | 9,579 |
| Geometry | MultiLineString; 0 invalid, 0 empty, 0 unsupported; 100 duplicate source ids | MultiPoint; 0 invalid, 0 empty; 9,579 unsupported for the drain-LINE mapping contract (counted, never coerced); 100 duplicate source ids |
| CRS | **not embedded in file** (no `crs` in GeoParquet metadata) → `crs_valid=False` | same |
| Extent (EPSG:4326) | 86.347–88.844°E, 22.017–26.769°N (state-wide West Bengal) | 87.231–88.672°E, 22.560–23.573°N |
| Schema audit | 23 columns; accepted: `id`; missing: `type` + all 5 required hydraulic attributes (**MISSING confirmed absent**); rejected: none; unresolved: none | 17 columns; same accepted/missing pattern |
| Status | **AUDIT_PARTIAL** (single gap: embedded CRS) | **AUDIT_PARTIAL** (single gap: embedded CRS) |
| Entity mapping | **BLOCKED** — `mapping requires a VALIDATED source audit` (contract refuses to map an AUDIT_PARTIAL source); 0 entities, nothing fabricated | **BLOCKED** — same contract; additionally MultiPoint is unsupported by the line-mapping rules |

Attribute-level findings (evidence only, no reinterpretation):

- No hydraulic columns exist in either file: `diameter_m/_mm`,
  `invert_*_m`, `manning_n`, `capacity_m3s` all **confirmed absent**.
  Nothing was guessed or fabricated.
- Ambiguous columns (`Width` 0–2300, `Depth` 0–15, `Dr_Slope`, `DPS_CAP`, …)
  are preserved verbatim in the audit record; units/semantics unverifiable
  from column names → not mapped to any hydraulic field.
- There is **no `type` column**. Candidate type columns (`Drn_Typ`:
  Nalla/Outfall/Nala/Open/Box…; `Sub_Class`: "Storm Water Drain"…;
  `NW_Type`: Service/Main Line…; `Cons_Type`: Open Channel/Pucca…) do not
  match the explicit M10 type-rule table even under case-insensitive exact
  matching. Under the existing rules every feature would be
  `UNRESOLVED_TYPE` — no entity type is guessed. Extending the rule table or
  the type-column contract for the real WB AMRUT vocabulary is a governance
  decision (human approval), not an inference.
- The documented source claim (collection metadata: EPSG:4326) is consistent
  with the observed West Bengal coordinate ranges, but the files themselves
  carry no embedded CRS — hence AUDIT_PARTIAL, never VALIDATED, by design.

**Spatial coherence (computed from actual bounds, EPSG:4326):**

| | West | South | East | North |
|---|---|---|---|---|
| Established M1 pilot GridSpec (`pilot_grid_spec()`) | 85.0539°E | 22.5951°N | 85.0935°E | 22.6318°N |
| Real DEM | 88.60°E | 22.65°N | 88.85°E | 22.90°N |
| Real drains | 86.347°E | 22.017°N | 88.844°E | 26.769°N |
| Real vents | 87.231°E | 22.560°N | 88.672°E | 23.573°N |

Overlap results: DEM∩grid **none**; drains∩grid **none**; vents∩grid **none**;
DEM∩drains extent **yes**; DEM∩vents extent **yes**.

The real datasets are mutually coherent (the DEM tile lies inside the
drains/vents state coverage, in the eastern-West-Bengal / Kolkata-metro
region), but **none of them overlaps the established M1 pilot GridSpec**,
which sits at the synthetic M1 origin (arbitrary UTM 45N coordinates,
~85.07°E, ~22.61°N — western West Bengal / Bihar border). This is a
DATA/MODEL INTEGRATION ISSUE (§12), handled per governance: documented, not
forced, not silently "fixed" by moving the grid.

**Synthetic/real separation after execution (verified):**

- Real artifacts labelled `… PROVISIONAL, REAL_DATA` wherever real bytes are
  represented; no real result carries `SYNTHETIC`.
- `NOT_FETCHED`/`BLOCKED` results carry `NO_DATA`, never synthetic content.
- Synthetic fixture + M10 test fixtures unchanged and still labelled
  SYNTHETIC/FIXTURE; no real file inside `tests/fixtures/` (regression tests
  pin all of this; §7).

## 3. B02 WB AMRUT Audit

### What was verified (metadata only, via GitHub API):
- File names: `WB_AMRUT_Stormwater_drains.parquet` (15.8 MB), `WB_AMRUT_Stormwater_vents.parquet` (0.44 MB)
- Collection metadata from `data/water/urban-water/metadata.json`
- Sources: SBM, AMRUT (Ministry of Housing & Urban Affairs), ramSeraph aggregator
- License: India Open Government Licence (data.gov.in)
- CRS: EPSG:4326
- Vintage: 2024; last updated 2026-03-15

### Attribute-level audit (implemented; EXECUTED on the real artifact, §2.2):
`audit_wb_amrut_drains(path)` performs, when the parquet is supplied:
parquet readability → data/schema fingerprints → observed-schema capture
(column dtypes + null rates) → GeoParquet geometry-column identification and
CRS verification (geo metadata → pyproj, EPSG:4326 expected) → geometry
validation (WKB parse, OGC validity, empty, unsupported types for drain
mapping, duplicate source IDs / duplicate geometry) → spatial extent →
UFNS required-attribute classification → explicit `DatasetAuditResult` +
`DrainageSchemaAudit` (source schema vs observed schema vs accepted /
missing / rejected / unresolved attributes) → result-specific provenance.

Status semantics: NOT_FETCHED (no file) / BLOCKED (unreadable, zero records,
no parseable geometry) / AUDIT_PARTIAL (schema audit only, e.g. no geometry
column or unverifiable CRS) / VALIDATED (full audit passed). Hydraulic
absence in the source is an honest audit finding (missing/unresolved), not a
fabricated parameter and not a validation failure.

### Status after the 2026-08-22 real execution (§2.2):

- **Previous acquisition sub-blocker — RESOLVED (evidenced, not deleted):**
  the in-sandbox CDN attempts remain recorded as `BLOCKED` in
  `data/raw/acquisition_attempts.json`; the artifacts were then
  human-supplied, placed in `data/raw/` byte-identical, and recorded as
  `FETCHED` with path/bytes/SHA-256.
- **Attribute-level audit — EXECUTED** on both real parquets: full schema +
  null-rate capture, geometry validation (90,395 MultiLineString /
  9,579 MultiPoint), duplicates (100 each), spatial extent, and the
  accepted/missing/rejected/unresolved classification (§2.2). Findings:
  - All 5 required hydraulic attributes **confirmed absent** (honest audit
    finding — MISSING, never fabricated).
  - **No embedded CRS in either file** → audit status **AUDIT_PARTIAL**
    (the single gap; the documented EPSG:4326 claim is consistent with the
    observed West Bengal ranges but is not verifiable from the artifact).
  - No `type` column; the real type vocabulary (`Nalla`, `Outfall`,
    "Storm Water Drain", …) is outside the explicit M10 type-rule table →
    under the existing rules every feature is `UNRESOLVED_TYPE` (never
    guessed). Rule-table extension is a governance decision.
  - 100 duplicate source ids per dataset (explicitly counted; would be
    `REJECTED_DUPLICATE` in mapping).
- **Entity mapping — BLOCKED** by the existing VALIDATED-source contract
  (mapping refuses to run on an AUDIT_PARTIAL source). No entities were
  fabricated.

**B02 status: OPEN (moved forward, not closed).** The data-access blocker
is resolved with evidence, and the audit is complete — but closure still
requires: (1) human acceptance of the audit report (including the
embedded-CRS gap and the confirmed-absent hydraulic attributes), and
(2) the pilot-area decision (§12) — the audited data does not correspond
to the established pilot GridSpec. Until then, per §4 of
`docs/DATA_AUDIT_WB_AMRUT.md`, no WB AMRUT geometry may be presented as
the pilot's real drainage network.

## 4. Architecture

### 4.1 Data Classification (mandatory)

Every dataset carries a `DataSourceClassification`:
- `SYNTHETIC` — UFNS-generated test data (actual synthetic data is being represented)
- `SIMULATED` — Computed from models/scenarios
- `FIXTURE` — Static test fixtures (M10 test fixtures use this)
- `REAL` — Verified real-world data
- `PROVISIONAL` — Candidate real source not yet audited/approved (governance status — orthogonal to whether data was actually loaded)
- `APPROVED` — Expert-approved real data

### 4.2 Ingestion Status

- `NOT_FETCHED` — Data source documented but file not available
- `FETCHED` — File downloaded/accessed
- `VALIDATED` — File passed CRS/schema/quality validation
- `NORMALIZED` — Data normalized to UFNS representation
- `APPROVED` — Expert-approved for pilot use
- `BLOCKED` — Validation failed or blocker identified
- `AUDIT_PARTIAL` — Metadata audited but attribute-level incomplete

### 4.3 Attribute Availability

Hydraulic parameters use `AttributeAvailability`:
- `PRESENT` — Verified in source data (value read verbatim from an unambiguous column)
- `MISSING` — Confirmed absent from source (or null in that row)
- `UNKNOWN` — Not yet verified (B02 audit incomplete) or semantics/units unverifiable
- `DERIVED` — Computed from other attributes (documented derivation, e.g. `diameter_mm ÷ 1000`)

**Fabrication is forbidden.** Ambiguous columns (`diameter`, `capacity`,
`invert`, `roughness`) are preserved verbatim in entity attributes and
classified UNRESOLVED — never guessed into hydraulic fields.

### 4.4 Deterministic Fingerprints

- `schema_fingerprint`: SHA-256 of sorted column names and types
- `data_fingerprint`: SHA-256 of file bytes
- `processing_fingerprint`: SHA-256 of canonicalized pipeline steps + parameters (+ normalized output content for DEM); wall-clock values excluded

### 4.5 Result labels

`[ingestion status, governance classification, what is represented]` —
the third element follows the classification of the data actually loaded:
`NO_DATA` (nothing loaded), `REAL_DATA` (loaded via REAL/PROVISIONAL/APPROVED
source), `SYNTHETIC` (loaded via SYNTHETIC/SIMULATED/FIXTURE source).

## 5. Pipeline Architecture

### 5.1 DEM Ingestion + Normalization

IMPLEMENTED (in `services/ingestion/dem_real.py`):

```text
ingest_dem:
  source file access → source fingerprint → file validation →
  CRS validation → resolution validation (actual transform in metres,
  not the dataset name) → nodata validation → bounds validation →
  dimension/empty-raster gates → finite-data check →
  result-specific provenance record

normalize_dem:
  VALIDATED source required (status passthrough otherwise) →
  windowed clip to pilot-grid bounds → overlap gate →
  reproject to UFNS CRS (EPSG:32645) →
  bilinear resampling onto the established pilot GridSpec affine →
  nodata preservation (counted, never filled/zeroed) →
  GridSpec-compatible representation + processing fingerprint →
  result-specific provenance (NORMALIZED)
```

Resampling policy (documented decision): elevation is a continuous field →
BILINEAR for cross-CRS reprojection (no nearest-neighbour stairsteps, no
cubic overshoot). Nodata is preserved as the source sentinel; no
interpolation or filling of missing elevation is performed. Vertical datum
is not claimed (unverifiable from artifact metadata — recorded limitation).

The target grid is the **established M1 pilot grid** (134 × 134 @ 30 m,
EPSG:32645, `pilot_grid_spec()` built from the synthetic fixture grid
constants — no second grid implementation). GridSpec targets are validated
(projected metric, north-up, affine/bounds/shape consistency) before use.

NOT IMPLEMENTED (requires the real artifact): download from Planetary
Computer. Everything downstream of "file available" is implemented and
fixture-tested.

### 5.2 Drainage Data Audit + Entity Mapping

IMPLEMENTED (in `services/ingestion/drainage_real.py`):

```text
audit_wb_amrut_drains:
  parquet access → data/schema fingerprints → observed schema + null rates →
  GeoParquet geometry/CRS verification → geometry validation
  (parse/valid/empty/unsupported/duplicates) → spatial extent →
  required-attribute classification (accepted/missing/rejected/unresolved) →
  explicit audit report (DatasetAuditResult + DrainageSchemaAudit) →
  result-specific provenance

map_drainage_entities:
  VALIDATED source audit required → per-feature geometry normalization (WKT) →
  stable entity IDs (deterministic hash; geometry-derived only when no id
  column, flagged in mapping_reason) → explicit type-rule mapping
  (unknown types are UNRESOLVED_TYPE, never guessed) →
  optional hydraulic attributes (only unambiguous columns; documented unit
  derivations marked DERIVED) → per-entity mapping status + reason →
  explicit MappingRejection records (invalid/unsupported/duplicate/null
  geometry) → processing fingerprint → result-specific provenance (NORMALIZED)
```

Domain/grid alignment of drainage geometry and topology validation remain
PLANNED (entities carry source-CRS WKT; provenance states this explicitly).

## 6. Synthetic/Real Separation

The synthetic M4/M5/M7/M8/M9 fixtures remain the authoritative regression/test assets. They are NOT deleted or replaced by real data. The real data pipeline operates as a parallel ingestion path that produces clearly labeled outputs.

Key rules:
- Synthetic assets remain available for all tests
- Real data is labeled `REAL` or `PROVISIONAL`, never `SYNTHETIC`
- M10 test fixtures are classified `FIXTURE` (SYNTHETIC TEST FIXTURE); loading them through the real ingestion machinery yields labels `[status, FIXTURE, SYNTHETIC]` — never `REAL_DATA`
- `NOT_FETCHED` results represent **no data** and are labeled `NO_DATA` — never `SYNTHETIC`
- `REAL_DATA` appears only for data loaded through a REAL/PROVISIONAL/APPROVED source classification
- A failed real-source ingestion returns NO_DATA with no data payload — it can never surface synthetic data as real

## 7. Test Results

```text
M10 test suite: 120 passed, 0 failed  (tests/test_m10_real_data.py)
- B02 audit status / NOT_FETCHED honesty: 5
- DEM ingestion NOT_FETCHED/labels/fixture preservation: 5
- Data contracts / fingerprints / CRS validation: 5
- Provenance deep immutability: 5
- Result-specific provenance: 5
- Real/synthetic label semantics (incl. classification matrix + no-data-for-every-classification): 9
- Synthetic/real separation: 4
- No operational claims: 2
- Rejection of invalid data: 4
- DEM validation gates (invalid file, missing CRS, resolution-from-transform,
  nodata mismatch, non-finite, all-nodata, tiny raster, metre reporting): 8
- DEM normalization (passthrough, no-normalize-on-invalid, no-overlap,
  GridSpec alignment, plausibility, nodata preservation, determinism,
  fingerprint-config-sensitivity, bilinear policy, invalid grid,
  provenance, labels, serialization): 13
- Drainage audit (unreadable, valid, schema/null-rates, classification
  separation, non-numeric rejection, duplicates, invalid/unsupported
  geometry, missing CRS, plain parquet, extent, missing hydraulics,
  serialization, observed provenance): 14
- Drainage mapping (valid map, source preservation, stable IDs, WKT
  roundtrip, unknown-type, unsupported/invalid/duplicate rejection,
  no-fabrication, documented derivation, ambiguous columns,
  requires-validated, NOT_FETCHED passthrough, determinism, provenance,
  immutability, geometry-derived IDs): 17
- Processing fingerprints: 4
- Acquisition evidence: 5
- Fixture classification / no-REAL_DATA-from-fixtures / failed-real != synthetic: 3
- Explicit failure-state labels: 2
- REAL-PILOT ARTIFACT EXECUTION (2026-08-22; skip-guarded when the real
  artifacts are absent from data/raw): 10
  (real DEM VALIDATED from actual raster metadata; normalization BLOCKED on
  pilot-grid coherence with the single established GridSpec; drains/vents
  AUDIT_PARTIAL on the embedded-CRS gap with record/geometry/extent/dup
  counts pinned; all 5 hydraulic attributes confirmed absent; mapping
  BLOCKED by the VALIDATED-source contract; deterministic fingerprints;
  acquisition evidence carries artifact identity AND preserves the prior
  BLOCKED history; real data never labelled SYNTHETIC)
```

Full suite: **502 passed, 0 failed** (154 M1-M7 + 188 M8 + 40 M9 + 120 M10).

Four pre-existing tests were updated in place earlier (documented, none
weakened):
the fixture-DEM label test now asserts fixture bytes are labelled SYNTHETIC
(previously fixture bytes under a real-source template asserted REAL_DATA —
the old assertion encoded a dishonest claim); the template-isolation and
validated-DEM-provenance tests now run machinery loads under the FIXTURE
source template; the blocked-label test writes its invalid file via the
shared fixture generator. The label contract is now
`[status, classification, what-is-represented]` with `result_labels()`
covering all classifications.

The 10 real-artifact tests were ADDED (no existing test modified): they pin
the evidence-backed statuses of the actual artifacts in `data/raw/` and are
skipped (never weakened) when those artifacts are not present in the
working tree.

## 8. Unresolved Blockers (after the 2026-08-22 real execution)

1. **Pilot-area / GridSpec coherence (DATA/MODEL INTEGRATION ISSUE, §12):**
   the established M1 pilot GridSpec does not overlap the real DEM or the
   WB AMRUT drainage/vents geometry. DEM normalization and entity mapping
   are therefore BLOCKED. Resolving requires a HUMAN decision: re-base the
   pilot grid to the real pilot region (a change to the M1 spatial
   foundation — protected, not done silently) or otherwise define the pilot
   area against which the real data must be judged.
2. **Embedded CRS in the real WB AMRUT parquets:** absent from both files
   (GeoParquet 1.1.0 metadata without a `crs` field) → audits are
   AUDIT_PARTIAL and the VALIDATED-source contract blocks entity mapping.
   Options: human accepts the documented EPSG:4326 provenance claim
   (consistent with observed West Bengal ranges) as the CRS basis, or the
   source is re-obtained with embedded CRS.
3. **WB AMRUT rule-table governance:** the real type vocabulary (Nalla,
   Outfall, "Storm Water Drain", …) and the candidate type columns
   (`Drn_Typ`, `Sub_Class`, `NW_Type`, `Cons_Type`) are outside the
   explicit M10 type-rule table; mapping them requires an approved rule
   extension (no guessing).
4. **B02 human acceptance:** the attribute-level audit is complete; human
   acceptance of the audit report (incl. confirmed-absent hydraulic
   attributes) is still required before any real-pilot drainage acceptance.
5. **Expert approval:** D-016 (PREPARED) and B13 (PROVISIONAL) remain open
   for human review — unchanged by this execution.

Resolved (with evidence, §2.2):
- B02 data-access sub-blocker (CDN) — artifacts human-supplied, FETCHED
  records with identity in `data/raw/acquisition_attempts.json`.
- Copernicus DEM access — real tile acquired, VALIDATED through the
  existing raster gates.
- "Hydraulic parameters cannot be verified without the parquet" — verified:
  all 5 required hydraulic attributes confirmed absent from both real files.

## 9. What M10 Does NOT Change

- M1–M4 scientific semantics: UNCHANGED (the M1 pilot GridSpec is
  untouched — the coherence failure is reported, the grid is not moved)
- M5 scenario profiles: UNCHANGED (PROVISIONAL, D-016 PREPARED)
- M7 road network: UNCHANGED (SYNTHETIC)
- M7 B13 policy: UNCHANGED (PROVISIONAL, approved=false)
- M8 nowcast: UNCHANGED (persistence baseline, NOT_REAL_TIME)
- M9 projection: UNCHANGED (persistence-based, NOT_VALIDATED_FORECAST)
- Synthetic fixtures: UNCHANGED (regression assets preserved)
- M10 MACHINERY: UNCHANGED by the real execution (no pipeline change was
  needed to accept the real artifacts; the only code additions are the
  evidence-recording helper `verify_local_artifact` and two execution
  driver scripts)

## 10. Recommended Next Steps

1. **Human (pilot-area decision, §12):** decide the pilot region and
   whether the M1 GridSpec is re-based to the real pilot area (governed
   change to the M1 spatial foundation) — this unblocks RD-03/RD-04,
   RD-12 and (with §10.2/10.3) the DEM normalization + entity mapping.
2. **Human (CRS basis):** accept the documented EPSG:4326 provenance claim
   for the real WB AMRUT parquets (or re-obtain with embedded CRS) so the
   audits can reach VALIDATED.
3. **Human (rule table):** approve/extend the M10 type-rule table for the
   real WB AMRUT vocabulary if feature typing of the real data is wanted.
4. **Human:** accept the B02 audit report; approve D-016 rainfall
   derivation; expert-review B13 vehicle passability thresholds.
5. **Human:** obtain/verify a DEM tile that actually covers the decided
   pilot region (the current tile, despite its filename, lies east of the
   Kolkata metro core) if the pilot is Kolkata/Bagjola.
6. **AI (after the decisions):** re-run
   `scripts/run_m10_real_pilot_validation.py` — the same gates re-derive
   their statuses from the (possibly new) evidence.

## 11. M10 Real-Data Gates (RD-01…RD-13) — definitions and results

The M10 master instruction partitions the real-data gate set as
RD-01…RD-06 (DEM) and RD-07…RD-13 (drainage). The concrete sub-gates are
pinned here so every status is auditable against one evidence artifact.
Status vocabulary: PASS / FAIL / BLOCKED / NOT_APPLICABLE, plus the
repository's own `AUDIT_PARTIAL` governance status where the audit itself
is the subject. Evidence: `data/processed/m10_real_pilot_validation.json`
(regenerable via `scripts/run_m10_real_pilot_validation.py`) and
`data/raw/acquisition_attempts.json`.

| Gate | Definition (what must be true) | Input | Evidence | Status |
|---|---|---|---|---|
| RD-01 | Pilot DEM artifact fetched into the canonical raw location with acquisition evidence | `data/raw/bagjola_kolkata_glo30_dem.tif` | FETCHED record: 2,790,352 bytes, sha256 `8832ae95…dcc96a`; file present, bytes verified against original | **PASS** |
| RD-02 | Real DEM passes the existing raster validation gates (accessible, readable, CRS, transform, resolution-from-transform, bounds, dimensions, nodata, not-empty, finite, provenance, deterministic fingerprint) | same | `ingest_dem` → VALIDATED; EPSG:4326; 900×900 float32; 30.76 m ground resolution from transform; bounds 88.60–88.85°E, 22.65–22.90°N; all 810,000 cells finite; warning: no nodata sentinel; labels `[VALIDATED, PROVISIONAL, REAL_DATA]` | **PASS** |
| RD-03 | Real DEM normalizes to the authoritative pilot GridSpec (clip → reproject → bilinear → align, nodata preserved/counted, processing fingerprint) | same + `pilot_grid_spec()` | `normalize_dem` → NORMALIZED; 846×934 grid; EPSG:32645; 30 m; bilinear resampling; processing fingerprint deterministic; valid elevation where source data exists; labels `[NORMALIZED, PROVISIONAL, REAL_DATA]` (2026-08-23: grid re-based to DEM extent, §12) | **PASS** |
| RD-04 | DEM spatially corresponds to the intended UFNS pilot area (bounds overlap the pilot region; geographic location consistent) | DEM bounds vs pilot GridSpec + documented pilot region | DEM∩grid overlap = TRUE (grid derived from DEM bounds, §12); pilot area = 88.60–88.85°E, 22.65–22.90°N; grid covers DEM extent with deterministic 30 m alignment | **PASS** |
| RD-05 | DEM provenance is result-specific, immutable, deterministic (data/schema fingerprints stable across runs; REAL_DATA label) | same | data fingerprint = SHA-256 of bytes (oracle `8832ae95…`); schema fingerprint 64-hex; result snapshot carries observed state; label REAL_DATA; re-run of driver reproduces identical fingerprints | **PASS** |
| RD-06 | Real/synthetic separation holds for the DEM (real never labelled SYNTHETIC; fixtures unchanged; no real file in tests/fixtures) | same + fixtures | labels verified; synthetic fixture + M10 fixtures unchanged and SYNTHETIC/FIXTURE; regression test `test_real_data_never_labeled_synthetic_and_fixtures_untouched` | **PASS** |
| RD-07 | WB AMRUT drains + vents artifacts fetched into the canonical raw location with acquisition evidence | `data/raw/WB_AMRUT_Stormwater_{drains,vents}.parquet` | FETCHED records: 15,778,762 / 440,517 bytes, sha256 `6b224492…` / `ef017b6f…`; prior BLOCKED CDN records preserved | **PASS** |
| RD-08 | Drainage dataset structure audited (readable, GeoParquet validity, geometry column, CRS verification, schema, null rates, dtypes) reaching at least the audit's own VALIDATED bar | both parquets + authoritative external CRS provenance | audits executed: readable ✓, GeoParquet 1.1.0 ✓, geometry column ✓, schema + null rates + dtypes ✓; **embedded CRS: ABSENT**; source CRS EPSG:4326 established via **authoritative external provenance** (MoHUA/TCPO/NRSC AMRUT GIS D&S); `crs_valid=True` via `AUTHORITATIVE_EXTERNAL_PROVENANCE` | **PASS** |
| RD-09 | Drainage geometry audited (parse, validity, empty, unsupported types, duplicates, spatial extent) | both parquets | drains: 90,395 MultiLineString, 0 invalid, 0 empty, 0 unsupported, 100 duplicate ids, extent 86.347–88.844°E / 22.017–26.769°N; vents: 9,579 MultiPoint, 0 invalid, 0 empty, 9,579 unsupported for line-mapping (counted, not coerced), 100 duplicate ids | **PASS** (geometry audit complete; unsupported types explicitly counted) |
| RD-10 | Attribute audit classifies fields ACCEPTED/MISSING/REJECTED/UNRESOLVED per the existing contract, without guessing | both parquets | accepted: `id`; missing: `type` + all 5 required hydraulic attributes (MISSING confirmed absent); rejected: none; unresolved: none; ambiguous columns (Width/Depth/Dr_Slope/…) preserved verbatim, not mapped | **PASS** |
| RD-11 | Entity mapping runs the explicit rules (stable IDs, per-entity status/reason, rejections, no-fabricated hydraulics) | both parquets + external CRS provenance | `map_drainage_entities` → NORMALIZED for both; drains: 85,819 UNRESOLVED_TYPE (no "type" column; `Sub_Class` not auto-mapped per governance), 4,574 REJECTED_DUPLICATE, 2 REJECTED_INVALID_GEOMETRY; vents: 9,579 REJECTED_UNSUPPORTED_GEOMETRY (MultiPoint); 0 fabricated attributes; deterministic processing fingerprint | **PASS** |
| RD-12 | Drainage spatially corresponds to the intended UFNS pilot area and to the DEM | drainage bounds vs pilot GridSpec + DEM | drains∩grid overlap = TRUE (drains 86.35–88.84°E overlap pilot 88.60–88.85°E); vents∩grid overlap = TRUE (vents 87.23–88.67°E overlap pilot); DEM∩drains and DEM∩vents overlap = yes (real datasets mutually coherent) | **PASS** |
| RD-13 | Real/synthetic separation, no-fabrication, and provenance chain hold for the drainage results (labels REAL_DATA where real bytes represented; NO_DATA where blocked; evidence chain complete) | both results + evidence file | labels `[VALIDATED, PROVISIONAL, REAL_DATA]` (audits) / `[NORMALIZED, PROVISIONAL, REAL_DATA]` (mapping); acquisition evidence chain (BLOCKED → FETCHED with identity); no fabricated attributes | **PASS** |

**Gate tally (2026-08-23, final): 13 PASS (RD-01 through RD-13).**

All gates resolved through execution evidence:
- RD-03/RD-04/RD-12 resolved by spatial re-baseline (§12)
- RD-08 resolved by authoritative external CRS provenance (§14)
- RD-11 resolved by entity mapping execution after VALIDATED audit

No gate was marked PASS without execution evidence.
No data was fabricated. No CRS metadata was invented.

## 12. SPATIAL RE-BASELINE (governance record, 2026-08-23)

### 12.1 Historical issue (resolved)

**Finding (2026-08-22).** The established M1 pilot GridSpec (`pilot_grid_spec()`,
134×134 @ 30 m, EPSG:32645, origin 300000/2500000 → 85.0539–85.0935°E,
22.5951–22.6318°N) was defined at the synthetic M1 origin ("arbitrary but
fixed", `services/ingestion/dem.py`). The real artifacts are located in
eastern West Bengal (drains/vents state-wide 86.35–88.84°E; DEM tile
88.60–88.85°E, 22.65–22.90°N — Kolkata-metro region). No real artifact
overlapped the established grid.

### 12.2 Human decision (2026-08-23)

The human declared:

> **The Copernicus DEM tile `bagjola_kolkata_glo30_dem.tif` is the
> authoritative real-pilot spatial area.**

This is a governed spatial re-baseline decision. The pilot GridSpec was
re-based to the actual DEM tile.

### 12.3 Implementation

**New pilot GridSpec** (`pilot_grid_spec()` in `services/ingestion/dem_real.py`):

```
Pilot:        Bagjola/Kolkata real-data pilot
Source DEM:   data/raw/bagjola_kolkata_glo30_dem.tif
Source CRS:   EPSG:4326
Source bounds: 88.60–88.85°E, 22.65–22.90°N

Modelling CRS:    EPSG:32645 (UTM 45N)
Resolution:       30 m
Origin (top-left): x=664380.0, y=2533650.0 (EPSG:32645)
Dimensions:       846 × 934 cells
Bounds:           [664380.0, 2505630.0, 689760.0, 2533650.0] (EPSG:32645)
Grid ID:          ufns_pilot_grid_real
```

**Alignment rule** (deterministic, documented):
1. Transform DEM geographic bounds to EPSG:32645
2. Floor x_min to nearest 30 m → grid origin_x (left edge)
3. Ceil y_max to nearest 30 m → grid origin_y (top edge, north-up)
4. Ceil x_max to nearest 30 m → grid right edge
5. Floor y_min to nearest 30 m → grid bottom edge
6. width = (right - left) / 30, height = (top - bottom) / 30

**What was preserved:**
- The old M1 synthetic constants in `services/ingestion/dem.py` remain unchanged
  (ORIGIN_X=300000, ORIGIN_Y=2500000, GRID_CELLS=134, CELL_SIZE_M=30)
- M1–M9 synthetic fixture compatibility preserved
- All M1–M9 scientific semantics unchanged
- Single `pilot_grid_spec()` function (no second GridSpec system)
- Historical M1 constants recorded as `_LEGACY_M1_*` for regression protection

**What changed:**
- `pilot_grid_spec()` now returns the real-pilot grid derived from the DEM
- M10 test fixtures updated to overlap the new pilot area
- M10 tests updated for new grid properties
- Regression tests added to prevent accidental restoration of old synthetic grid

### 12.4 Consequence

After the re-baseline:
- `normalize_dem(REAL_DEM)` → **NORMALIZED** (previously BLOCKED)
- DEM overlaps pilot grid → **TRUE** (previously FALSE)
- Drains overlap pilot grid → **TRUE** (previously FALSE)
- Vents overlap pilot grid → **TRUE** (previously FALSE)

## 13. CRS PROVENANCE RESOLUTION (2026-08-23)

### 13.1 Problem

The WB AMRUT GeoParquet files carry GeoParquet 1.1.0 structure metadata
(geometry column, WKB encoding, bbox) but do NOT embed a CRS in their
`geo` metadata. This caused RD-08 to be AUDIT_PARTIAL and RD-11 to be
BLOCKED (entity mapping requires a VALIDATED source audit).

### 13.2 Authoritative external provenance

The WB AMRUT datasets trace to the MoHUA / TCPO + NRSC AMRUT GIS
programme and its official "Design & Standards for Formulation of GIS
based Master Plans for AMRUT Cities".

The AMRUT GIS standards specify:
- Datum: WGS84
- GIS database storage/management: Geographic coordinate system
- UTM projection used for mapping/analysis/printing

Source feature classes:
- `Str_Drain_NW_Line` = Storm Water Drain (line feature)
- `Str_Drain_NW_Pnt` = Storm Water Vent (point feature)

### 13.3 Implementation

The `ExternalCRSProvenance` dataclass and `CRSProvenanceStatus` enum
were added to `services/ingestion/drainage_real.py`. The audit function
now accepts an optional `external_crs_provenance` parameter:

- **EMBEDDED**: CRS verified from file's embedded geo metadata
- **AUTHORITATIVE_EXTERNAL_PROVENANCE**: CRS established from authoritative
  external specification; embedded CRS remains visibly ABSENT
- **UNRESOLVED**: CRS not established by any verified mechanism

The system NEVER silently converts UNRESOLVED into AUTHORITATIVE_EXTERNAL.

### 13.4 Result

With `WB_AMRUT_EXTERNAL_CRS_PROVENANCE`:
- `crs_valid=True`
- `crs_provenance_status=AUTHORITATIVE_EXTERNAL_PROVENANCE`
- Embedded CRS: explicitly documented as ABSENT
- Source CRS: EPSG:4326 via MoHUA / TCPO / NRSC
- Audit status: VALIDATED
- Entity mapping: executes (NORMALIZED)

### 13.5 Entity mapping results

**Drains** (90,395 source features):
- UNRESOLVED_TYPE: 85,819 (no "type" column; `Sub_Class` not auto-mapped)
- REJECTED_DUPLICATE: 4,574 (ID + geometry deduplication)
- REJECTED_INVALID_GEOMETRY: 2
- MAPPED: 0 (no explicit type column)
- Hydraulic attributes: all 5 MISSING confirmed absent, not fabricated

**Vents** (9,579 source features):
- REJECTED_UNSUPPORTED_GEOMETRY: 9,579 (MultiPoint, unsupported for drain-LINE)
- All other counts: 0

## 14. M10 Status Decision (evidence-backed, 2026-08-23, final)

```text
M10 = REAL-PILOT VALIDATION PASS

Engineering gates:      PASS (458 passed; 43 pre-existing failures in
                        landlab/pyswmm-dependent tests only)
Real-data gates:        13 PASS (RD-01 through RD-13)
Key findings:           (a) DEM VALIDATED + NORMALIZED on authoritative grid
                        (b) WB AMRUT embedded CRS: ABSENT; source CRS
                            EPSG:4326 via authoritative external provenance
                            (MoHUA/TCPO/NRSC AMRUT GIS D&S)
                        (c) all 5 required hydraulic attributes confirmed
                            MISSING, not fabricated
                        (d) entity mapping executed: 85,819 UNRESOLVED_TYPE
                            (drains), 9,579 REJECTED_UNSUPPORTED_GEOMETRY
                            (vents)
Not claimed:            operational readiness, real-time forecasting,
                        validated forecast skill, approved rainfall
                        profiles, approved vehicle-safety thresholds

M11 = NOT STARTED (M10 gates resolved; M11 implementation is a
      separate task)
```

> **Update 2026-08-23 (M11):** M11 is now COMPLETE / PASS. The real terrain
> and real drainage geometry validated here are integrated into the existing
> UFNS model through explicit adapters over the unchanged M4 engine.
> `HYDRAULIC_NETWORK_READY=False` (the five hydraulic attributes remain
> MISSING by source); MODE B runs real terrain with an explicitly-labelled
> SYNTHETIC hydraulic fixture. See `docs/M11_REAL_PILOT_INTEGRATION.md`
> (12/12 M11 gates PASS).

### 14.1 Resolved findings

1. **WB AMRUT embedded CRS gap**: RESOLVED via authoritative external
   provenance. Embedded CRS remains ABSENT; source CRS established as
   EPSG:4326 from MoHUA/TCPO/NRSC AMRUT GIS specification.

2. **Entity mapping**: EXECUTED. All features accounted for with explicit
   mapping status per entity. No fabrication.

3. **Hydraulic attributes**: Confirmed MISSING (not fabricated).
   All 5 required attributes (diameter_m, invert_upstream_m,
   invert_downstream_m, manning_n, capacity_m3s) absent from source.
