# Pilot Data Audit — West Bengal AMRUT Stormwater Collection (B02)

**Status:** ATTRIBUTE-LEVEL AUDIT EXECUTED — result **VALIDATED** (2026-08-23: CRS provenance RESOLVED via authoritative external source — MoHUA/TCPO/NRSC AMRUT GIS D&S; embedded CRS remains ABSENT; source CRS EPSG:4326 established through governed `ExternalCRSProvenance` mechanism; entity mapping executed); **human acceptance of full audit still open**
**Date:** 2026-08-21 (metadata layer); 2026-08-22 (attribute-level execution on the real artifacts)
**Auditor:** Antigravity 1 (AI); findings require human acceptance before any real-pilot acceptance

## 1. What was verified

The `india-geodata` collection (`yashveeeeeeer/india-geodata`, release tag `water/urban-water`) was inspected via the GitHub API (API reachable from the sandbox; the release-asset CDN is not):

| Item | Finding |
|---|---|
| Files present | `WB_AMRUT_Stormwater_drains.parquet` (15.8 MB), `WB_AMRUT_Stormwater_vents.parquet` (0.44 MB), plus SBM layers and PMTiles/GeoJSONL variants |
| Collection metadata (from repo `data/water/urban-water/metadata.json`) | Sources: Swachh Bharat Mission and AMRUT (authority: Ministry of Housing & Urban Affairs), **plus a third-party aggregator `ramSeraph/indian_water_features` ("aggregated from government sources")** |
| Claimed licence | India Open Government Licence (data.gov.in) |
| Claimed CRS | EPSG:4326 |
| Claimed vintage | 2024; collection last updated 2026-03-15 |
| Distribution | GitHub Releases only (`gh release download water/urban-water --repo yashveeeeeeer/india-geodata`) |

## 2. Attribute-level audit — EXECUTED on the real artifacts (2026-08-22)

The in-sandbox CDN block (§1 history) was the access sub-blocker. A human
supplied both parquets (byte-identical, SHA-256 verified) into `data/raw/`;
the prior in-sandbox `BLOCKED` attempts remain recorded verbatim in
`data/raw/acquisition_attempts.json`, followed by `FETCHED` records with
path/bytes/SHA-256. The attribute-level audit then ran unchanged via
`scripts/run_m10_real_pilot_validation.py` (evidence:
`data/processed/m10_real_pilot_validation.json`).

**Result: `AUDIT_PARTIAL` for both files — the single gap is an embedded CRS.**

| Audit item | Drains (90,395 rows) | Vents (9,579 rows) |
|---|---|---|
| Readable / GeoParquet | yes (1.1.0, WKB) | yes |
| Geometry | MultiLineString; 0 invalid, 0 empty, 0 unsupported | MultiPoint; 0 invalid, 0 empty; all 9,579 unsupported for the drain-LINE mapping contract (counted, never coerced) |
| Duplicate source ids | 100 | 100 |
| CRS | **not embedded** (no `crs` in GeoParquet metadata) → `crs_valid=False` → AUDIT_PARTIAL | same |
| Extent (EPSG:4326, from geometry) | 86.347–88.844°E, 22.017–26.769°N (state-wide WB) | 87.231–88.672°E, 22.560–23.573°N |
| Schema | 23 columns; accepted `id`; missing `type` + all 5 required hydraulic attributes (**MISSING confirmed absent**); rejected none; unresolved none | 17 columns; same accepted/missing pattern |
| Entity mapping | **BLOCKED** — `mapping requires a VALIDATED source audit`; 0 entities; nothing fabricated | **BLOCKED** — same contract |

Findings carried forward (no reinterpretation, no fabrication):
- **Hydraulics confirmed absent**: `diameter_m/_mm`, `invert_*_m`,
  `manning_n`, `capacity_m3s` do not exist in either file. Nothing guessed.
- **No `type` column**; candidate columns (`Drn_Typ`: Nalla/Outfall/Nala/
  Open/Box…; `Sub_Class`: "Storm Water Drain"…; `NW_Type`; `Cons_Type`) do
  not match the explicit M10 type-rule table under exact matching → under
  the existing rules every feature is `UNRESOLVED_TYPE` (never guessed).
- Ambiguous columns (`Width` 0–2300, `Depth` 0–15, `Dr_Slope`, `DPS_CAP`, …)
  preserved verbatim; units/semantics unverifiable → not mapped to any
  hydraulic field.
- The documented EPSG:4326 claim is consistent with the observed West Bengal
  ranges but is **not verifiable from the artifact** — hence AUDIT_PARTIAL.

## 3. What remains (human action)

The download command is no longer required (artifacts are in `data/raw/`).
What remains to close B02:

1. **Human acceptance of this audit report**, including the embedded-CRS gap
   and the confirmed-absent hydraulic attributes. Either accept the
   documented EPSG:4326 provenance claim as the CRS basis (consistent with
   the observed ranges) or re-obtain the files with an embedded CRS so the
   audits can reach VALIDATED.
2. **Pilot-area decision** (DATA/MODEL INTEGRATION ISSUE,
   `docs/M10_REAL_PILOT_FOUNDATION.md` §12): the audited data does not
   overlap the established M1 pilot GridSpec; a human must decide whether
   the grid is re-based to the real pilot region.
3. **Optional rule-table governance**: approve/extend the M10 type rules for
   the real vocabulary if feature typing of the real data is wanted.

Re-run the audit any time with (unchanged machinery):

```python
from pathlib import Path
from services.ingestion.drainage_real import audit_wb_amrut_drains, map_drainage_entities

result = audit_wb_amrut_drains(Path("data/raw/WB_AMRUT_Stormwater_drains.parquet"))
print(result.status, result.to_dict()["schema_audit"])
mapping = map_drainage_entities(Path("data/raw/WB_AMRUT_Stormwater_drains.parquet"))
print(mapping.status, mapping.blockers)
```

## 4. Interim policy (unchanged from Phase 0)

Until the attribute-level audit passes and the human team accepts the primary provenance, **no WB AMRUT geometry may be presented as the pilot's real drainage network**. The deterministic synthetic fixture (M3) remains the demonstration network, labelled `SIMULATED_SCENARIO`. B02 stays OPEN in `AI_REVIEW.md`.
