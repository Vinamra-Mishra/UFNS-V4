# M11 — Real-Pilot Model Integration

**Status:** M11 = PASS (all 12 gates PASS with execution evidence)
**Date:** 2026-08-23
**Branch:** `arena/01a02c6a-ufns`
**Adapter version:** `m11-real-pilot-adapter-v1`
**Engine version:** `m4-coupling-v1` (unchanged physics; one additive, byte-identical-by-default grid-origin hook)

> Governing principle (master prompt §9): real data enters the model through
> explicit, auditable contracts. Where the real data is insufficient for a
> scientific operation, that operation is STOPPED at the contract boundary —
> never filled with an assumption unless that assumption is explicitly
> governed, labelled, and approved for that exact purpose.

---

## 1. Objective

M10 established and validated the real Bagjola/Kolkata pilot data (DEM + WB
AMRUT drainage) through deterministic ingestion/normalization/audit/mapping
contracts (RD-01…RD-13 = 13/13 PASS). M11 integrates that validated real
pilot into the existing UFNS modelling stack:

```
REAL RAW DATA
    ↓
M10 VALIDATION
    ↓
M10 NORMALIZED / MAPPED ARTIFACTS
    ↓
M11 MODEL ADAPTER          ← this milestone
    ↓
UFNS FLOOD MODEL (unchanged M2/M4 engine)
    ↓
REAL-PILOT SIMULATION RESULT
    ↓
PROVENANCE + MASS LEDGER + DIAGNOSTICS
```

The objective is NOT merely to prove ingestion works (M10 did that). It is to
establish a deterministic, auditable path from raw real data to a real-pilot
simulation result, with every category (real / derived / governed-assumption /
provisional / synthetic) explicitly identified and never silently conflated.

## 2. Authoritative pilot (unchanged from M10)

- **DEM:** `data/raw/bagjola_kolkata_glo30_dem.tif` — EPSG:4326, 88.60–88.85°E / 22.65–22.90°N, 900×900 float32, ~1 arc-second.
- **GridSpec:** `ufns_pilot_grid_real` — EPSG:32645, 30 m, 846×934, origin (664380.0, 2533650.0), bounds [664380.0, 2505630.0, 689760.0, 2533650.0]. Derived deterministically from the real DEM tile.
- **Drainage:** `data/raw/WB_AMRUT_Stormwater_drains.parquet` (Str_Drain_NW_Line), `data/raw/WB_AMRUT_Stormwater_vents.parquet` (Str_Drain_NW_Pnt). Source CRS EPSG:4326 via authoritative external provenance (MoHUA/TCPO/NRSC AMRUT GIS); **embedded CRS = ABSENT** (preserved, never faked into the raw artifact).

The pilot GridSpec was NOT moved; the legacy synthetic M1 grid (134×134, origin 300000/2500000) remains available only for M1–M9 fixture/regression compatibility.

## 3. The fundamental distinction (MANDATORY)

```
REAL DRAINAGE GEOMETRY   ≠   REAL HYDRAULIC NETWORK
```

The real WB AMRUT data carries geometry but **NOT** the five UFNS-required
hydraulic attributes. M11 therefore implements an explicit capability/state
model (`services/pilot/modes.py`):

| Capability | Value (this pilot) |
|---|---|
| `REAL_GEOMETRY_AVAILABLE` | True (when geometry is mapped) |
| `HYDRAULIC_PARAMETERS_MISSING` | True |
| `HYDRAULIC_NETWORK_READY` | **False** |

The system can consume real drainage geometry WITHOUT claiming hydraulic
simulation of those drains is scientifically valid.

## 4. Architecture — adapters, not engine rewrites

M11 integrates through a new `services/pilot/` layer that composes the
existing validated components. No M2/M4 mathematics were rewritten.

```
existing engine (services/simulation/engine.py — CoupledFloodModel)
        ↑  (unchanged physics)
M11 adapter (services/pilot/adapter.py — M11SimulationAdapter)
        ↑
real pilot data (normalized DEM + mapped drainage)
```

### 4.1 Engine change (minimal, additive, byte-identical by default)

A single additive field was added to `RunConfig`:

```python
grid_origin_xy: tuple[float, float] | None = None
```

with a `RunConfig.model_affine()` helper used by `_grid_spec()` and the
artifact writer. When `grid_origin_xy is None` (the M1–M9 default),
`model_affine()` returns the synthetic fixture affine (`grid_affine()`)
**exactly** — verified: `cfg.model_affine() == grid_affine()` for every
synthetic config, and the `fingerprint()` payload is untouched, so all M1–M9
fingerprints and grids are byte-identical. Setting `grid_origin_xy` to the
real-pilot origin runs real terrain through the unchanged coupled engine.

No other engine semantics (exchange algorithm, sign convention, causal
ordering, ledger identity, 5 s stride, mass gates) were modified.

### 4.2 `services/pilot/` modules

| Module | Responsibility |
|---|---|
| `modes.py` | Pilot model modes (A/B/C), capability state, governed content labels |
| `contract.py` | Hydraulic readiness contract (required/present/missing/derived/assumed/unresolved) |
| `provenance.py` | Deeply immutable real-pilot provenance + GridSpec fingerprint |
| `terrain.py` | `RealTerrainAdapter` — wraps M10 `normalize_dem`; answers the 8 provenance questions |
| `drainage.py` | `RealDrainageAdapter` — M10 mapping + deterministic EPSG:4326→32645 reprojection |
| `adapter.py` | `M11SimulationAdapter` — MODE A (no sim), MODE B (executable), ROI/cell mapping |

## 5. Model modes (master prompt §7)

| Mode | Terrain | Hydraulics | Executable | Content label |
|---|---|---|---|---|
| **A** | REAL DEM | real drainage geometry only (hydraulics MISSING) | No (geometry only) | `REAL_TERRAIN_REAL_DRAINAGE_GEOMETRY` |
| **B** | REAL DEM | explicitly-labelled SYNTHETIC/ASSUMED fixture | Yes (this milestone) | `REAL_TERRAIN_SYNTHETIC_HYDRAULICS` |
| **C** | synthetic (M1–M9) | synthetic (M1–M9) | Yes (regression path) | `SYNTHETIC` |

Modes are never mixed within one result. Every result identifies its mode.

### 5.1 MODE B execution — region of interest (ROI)

The real DEM carries 9,404 scattered nodata cells (1.19%) that must NEVER be
silently filled. The executable surface model therefore runs on a real-pilot
**region of interest (ROI)**: a deterministic, zero-nodata rectangular window
of the normalized real elevation. This is 100% real elevation data (no
filling, no fabrication) and a genuine sub-rectangle of the authoritative
pilot grid (same CRS, cell size, alignment) — it does NOT move the pilot grid
and does NOT restore the synthetic grid. The full-pilot normalization remains
authoritative (gate M11-01).

- ROI selection (`select_real_pilot_roi`): deterministic raster scan from
  offset (50, 50) for the first 134×134 block with zero nodata.
- Cell mapping (`map_real_cells`): lowest interior cell = basin; inlets =
  nearest ranked basin-shoulder cells above the floor; vent = nearby raised
  cell. Fully deterministic; adaptive band/distance so it is robust to the
  local topography of any valid window.
- Synthetic hydraulic fixture (`write_mode_b_synthetic_inp`): reuses
  `services/hydraulics/fixture.exact_fixture_inp` (no M4 rewrite). The
  **datum offset** anchors the synthetic fixture to the real ROI basin floor
  for sensible coupling — this is a documented alignment, NOT a fabricated
  hydraulic parameter. Hydraulic parameters (diameter, Manning, …) remain
  SYNTHETIC/ASSUMED.

## 6. Hydraulic data-gap contract (master prompt §12)

`services/pilot/contract.py` records, per required attribute, its
availability:

| Attribute | Real-source contract | Synthetic-fixture contract (MODE B) |
|---|---|---|
| `diameter_m` | **MISSING** (confirmed absent) | ASSUMED (synthetic_fixture) |
| `invert_upstream_m` | **MISSING** | ASSUMED |
| `invert_downstream_m` | **MISSING** | ASSUMED |
| `manning_n` | **MISSING** | ASSUMED |
| `capacity_m3s` | **MISSING** | ASSUMED |

- `real_hydraulic_network_ready = False` for BOTH contracts.
- `hydraulic_network_ready` is True ONLY when the REAL source fully
  parameterizes the network. The synthetic-fixture path never sets it True.
- No automatic derivation. Ambiguous source columns (Width, Depth, Dr_Slope,
  DPS_CAP, …) are preserved verbatim and classified UNRESOLVED, never
  converted to hydraulic parameters.

## 7. Real/synthetic separation (hard gate, §14)

A result containing real DEM data never becomes `SYNTHETIC`; a result
containing synthetic hydraulic parameters never becomes `REAL_DATA`. A
combined result carries the governed label `REAL_TERRAIN_SYNTHETIC_HYDRAULICS`
— it names BOTH components and hides nothing.

## 8. Provenance (§13)

Every real-pilot result carries a deeply immutable `RealPilotProvenance`
(`services/pilot/provenance.py`): raw DEM SHA-256, raw drainage SHA-256, CRS
source provenance, normalized-DEM fingerprint, drainage-mapping fingerprint,
GridSpec fingerprint, rainfall fingerprint, model-config fingerprint,
scenario fingerprint, model mode, software/model version, status labels. Nested
members are immutable; `to_dict()` returns fresh copies; a caller cannot
mutate provenance after result creation.

## 9. Mass conservation (§15)

The existing mass ledger is retained verbatim. MODE B reports the same ≤1%
relative-residual gate, film initialization, exchange cancellation, and SWMM
identity-based storage accounting as the M4 engine. Measured relative residual
on the integrated real-terrain run: **7.8 × 10⁻⁸** (gate PASS).

## 10. Rainfall (§8)

Rainfall is NOT promoted. D-016 status remains **PREPARED — HUMAN REVIEW
REQUIRED**; profiles remain **PROVISIONAL**. MODE B uses the existing governed
PROVISIONAL uniform profile for technical integration only. Every result
preserves rainfall provenance/status, D-016 review status, scenario
fingerprint, `real_time=False`, `validated_forecast=False`. No observed
rainfall is invented; no forecast validation or real-time operation is claimed.

## 11. M11 gate matrix (§18) — all PASS with execution evidence

Evidence artifact: `data/demo/m11/gate_matrix.json` (regenerated by
`scripts/run_m11_real_pilot_validation.py`).

| Gate | Name | Status | Key evidence |
|---|---|---|---|
| M11-01 | Real DEM model-ready | **PASS** | NORMALIZED onto `ufns_pilot_grid_real` (846×934); processing fingerprint `9b7ab5…64e1`; nodata preserved (9,404 cells), never filled |
| M11-02 | Real drainage spatially aligned | **PASS** | EPSG:4326 → EPSG:32645 via pyproj; embedded CRS = ABSENT; AUTHORITATIVE_EXTERNAL_PROVENANCE; coords in metres |
| M11-03 | Entity provenance complete | **PASS** | 90,395 features fully accounted (0 mapped + 85,819 unresolved + 4,576 rejected); traceable to source ids |
| M11-04 | Hydraulic readiness governed | **PASS** | all 5 required attributes MISSING; `hydraulic_network_ready=False` |
| M11-05 | Real/synthetic separation | **PASS** | MODE-B label `REAL_TERRAIN_SYNTHETIC_HYDRAULICS`; real terrain never SYNTHETIC |
| M11-06 | Real-pilot simulation path | **PASS** | coupled run succeeded on real ROI terrain; S2D = 72.13 m³ (real exchange occurred) |
| M11-07 | Mass conservation | **PASS** | relative residual 7.8 × 10⁻⁸ ≤ 1%; status `pass` |
| M11-08 | Determinism | **PASS** | repeated run → identical config fingerprint + bit-identical depth arrays |
| M11-09 | Provenance completeness | **PASS** | full chain present; raw-DEM SHA-256 matches; GridSpec + config fingerprints linked |
| M11-10 | M1–M9 regression | **PASS** | synthetic DEM/grid/INP untouched; pilot grid ≠ legacy; engine byte-identical by default |
| M11-11 | No fabricated hydraulic values | **PASS** | zero hydraulic fields on real entities; all 5 MISSING |
| M11-12 | API/dashboard truthfulness | **PASS** | capability state correct; NOT_REAL_TIME / NOT_VALIDATED_FORECAST labels present |

**OVERALL: M11 = PASS** (wall time 42.6 s).

## 12. Entity mapping statistics (real WB AMRUT drains)

| Outcome | Count |
|---|---|
| Total source features | 90,395 |
| MAPPED | 0 (no `type` column → not guessed) |
| UNRESOLVED_TYPE | 85,819 |
| REJECTED (duplicate source id) | 4,574 |
| REJECTED (invalid geometry) | 2 |

Unresolved types are NOT reinterpreted to raise mapping counts. The source
vocabulary remains auditable. Vents (9,579 MultiPoint) are handled by the
existing contract (counted, never coerced to lines).

## 13. Dashboard / API (§17)

New endpoints (inspection layer over the precomputed
`data/demo/m11/pilot_inspection.json`; never re-runs simulation):

- `GET /api/v1/pilot/real` — overview (DEM provenance, drainage coverage, hydraulic readiness, GridSpec, rainfall status, model mode, simulation availability, mass-balance status)
- `GET /api/v1/pilot/real/dem` — DEM provenance + GridSpec
- `GET /api/v1/pilot/real/drainage` — coverage + mapped/unresolved/rejected counts
- `GET /api/v1/pilot/real/hydraulic-readiness` — formal readiness contract

The UI distinguishes REAL_PILOT / SYNTHETIC / PROVISIONAL / ASSUMED / MISSING
/ UNRESOLVED / NOT_REAL_TIME / NOT_VALIDATED_FORECAST and never implies
operational forecasting, validated forecast skill, certified road safety, or
real drainage hydraulic capacity. Health exposes
`real_pilot_inspection_available`.

## 14. Artifacts (`data/demo/m11/`)

- `gate_matrix.json` — the 12-gate matrix with evidence
- `mode_b_result.json` — full MODE-B result (provenance, mass ledger, contract, ROI, cell map)
- `pilot_inspection.json` — lightweight API inspection payload
- `mode_b_drainage_synthetic.inp` — the labelled synthetic hydraulic fixture (datum-anchored to the real basin)

(SWMM `.out`/`.rpt` are gitignored per repository convention.)

## 15. Scientific limitations (§21) — MANDATORY

The real WB AMRUT drainage data lacks diameter, invert elevations, Manning
roughness, and capacity. Therefore M11 **does NOT claim** "real drainage
hydraulic simulation" or "real drainage geometry integrated through the coupled model".
It **does claim** "real terrain integrated through the coupled model" — with execution
evidence (gates M11-01, M11-06).

- Hydraulic parameters in MODE B are SYNTHETIC/ASSUMED, not real, not validated against the pilot network.
- Vertical datum of the real DEM is UNVERIFIED; the synthetic fixture datum is anchored to the real ROI basin for coupling only.
- Rainfall is PROVISIONAL (D-016 PREPARED, human review required); not real-time, not a validated forecast.

## 16. Remaining human decisions

- **D-016:** hydrologist approval of the rainfall derivation (return-period mapping + derived totals) — flips profiles to APPROVED.
- **B13:** expert review of the PROVISIONAL DEMONSTRATION passability policy before any operational wording.
- **B02:** human acceptance of the WB AMRUT audit report (embedded-CRS basis + confirmed-absent hydraulics + pilot-area decision).
- **Hydraulic parameters:** if a real hydraulic network is wanted, the five required attributes must be independently obtained and governed (field survey / as-built drawings / asset register). Until then MODE A is the only real-data mode and MODE B is the only executable real-terrain mode (with synthetic hydraulics).
- **WB AMRUT type rules:** approve/extend the explicit M10 type rules for the real vocabulary if feature typing of the real data is wanted (no guessing until then).

## 17. What was NOT done (hard constraints honoured)

No fabricated hydraulic parameters; no silent estimation; no modification of
the raw parquet files; no claim that drainage geometry is a complete hydraulic
network; no synthetic-as-real; no pilot-grid move; no synthetic-grid restore;
no M4 rewrite; no mass-balance weakening; no provenance removal; no
synthetic→real relabelling; no operational/forecast-skill/real-time claims;
no D-016/B13 approval fabrication; no fake observed rainfall or field
measurements; no geometry coercion; no deletion of acquisition evidence; no
M1–M9 semantic change for convenience.

## 18. Final M11 status

**M11 = PASS** — all 12 defined gates have execution evidence; real terrain
and real drainage geometry are integrated through explicit, auditable
contracts; the real/synthetic boundary is intact; mass conservation holds;
provenance is complete and immutable; M1–M9 regression is protected; the API
is truthful.
