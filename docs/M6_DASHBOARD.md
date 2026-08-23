# M6 — Dashboard & API (Scenario Inspection Layer)

**Status:** PASS (implementation complete; D-016 remains PREPARED — HUMAN REVIEW REQUIRED)
**Date:** 2026-08-21
**Scope:** A usable dashboard/API for inspecting precomputed M5 scenario results and
communicating flood information without overstating scientific certainty.

---

## 1. Objective

Provide the first usable UFNS inspection interface: a versioned JSON/artifact API
plus a single-file web dashboard that shows the four M5 scenarios (S1–S4), their
metrics, flood-depth and flood-extent maps, mass-balance diagnostics, provenance,
and the S3/S4 blockage comparison — while visibly labelling every result
SYNTHETIC / SIMULATED / PROVISIONAL / NOT FOR OPERATIONAL USE.

The dashboard **consumes precomputed results**; it never re-runs the M4/M5
hydraulic simulation to serve a request.

## 2. Architecture

```text
services/scenarios/         (unchanged M5 scenario engine — not modified)
        │
        ▼
data/demo/m5/               precomputed artifacts (authoritative)
   ├── m5_results.json       per-scenario result summaries + mass ledgers
   ├── m5_comparison.json    S3/S4 blockage comparison + controls
   └── s{1..4}/depth_t*.tif  37 GeoTIFF depth snapshots per scenario
        │
        ▼
apps/api/store.py            loads results + comparison, merges live scenario
                             definitions (full provenance); no simulation
apps/api/render.py           on-demand PNG rendering of depth/extent GeoTIFFs
apps/api/app.py              FastAPI app (versioned routes + static dashboard)
apps/web/index.html          single-file dashboard (no build step, no CDN)
scripts/run_dashboard.py     uvicorn launcher
```

Scenario registry → precomputed `ScenarioResult` → API → dashboard
(**not** dashboard request → rerun SWMM/Landlab → response).

## 3. API

Base: `/api/v1` (versioned); `/health` unversioned. All responses carry
`dataset_status`, `d016_status`, `d016_human_review`, and `labels`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Dashboard (HTML) |
| GET | `/health` | Liveness, model versions, artifact readiness |
| GET | `/api/v1/version` | API/model/engine version + D-016 status |
| GET | `/api/v1/scenarios` | Scenario list (S1–S4) with status labels |
| GET | `/api/v1/scenarios/{id}` | Full metadata + provenance (assumptions/limitations/fingerprints) |
| GET | `/api/v1/scenarios/{id}/result` | Authoritative precomputed ScenarioResult |
| GET | `/api/v1/scenarios/{id}/snapshots` | Per-snapshot timeline (lead 0…180) |
| GET | `/api/v1/scenarios/{id}/mass-balance` | Conservation identity from the authoritative ledger |
| GET | `/api/v1/scenarios/{id}/flood-depth?lead=N` | Flood-depth map PNG (m) |
| GET | `/api/v1/scenarios/{id}/flood-extent?lead=N` | Flood-extent map PNG (depth > threshold) |
| GET | `/api/v1/comparison/s3s4` | S3/S4 paired blockage comparison |

### Errors

Structured envelope (never hides model/artifact failures):

```json
{"error": {"code": "SCENARIO_NOT_FOUND", "message": "...", "valid_scenario_ids": ["S1","S2","S3","S4"]}}
```

### Safety

- Scenario identifiers are allow-listed (`S1`…`S4`); anything else → 404.
- No client-supplied file path is ever accepted; artifact paths are derived
  server-side from the allow-listed id + validated lead (no path traversal).
- `lead` is validated against the 5-minute snapshot inventory (0…180).
- No secrets, no external services, no credentials.

## 4. UI

Single-file `apps/web/index.html` (inline CSS/JS; no build step, no CDN, no
external fonts). Panels:

1. **Scenario selector** — S1 Normal / S2 Heavy / S3 Extreme / S4 Extreme+Blocked,
   each showing rainfall total, rainfall status (PROVISIONAL), drainage
   condition, and mass gate.
2. **Scenario metrics** — rainfall total, peak depth, flooded area, S2D, D2S,
   outfall, surcharge, mass residual, time-to-peak, scenario fingerprint, run ID,
   model/engine versions, status badges (units labelled).
3. **Mass balance** — the conservation identity (`rainfall − losses − surface
   outflow − drainage outfall − Δstorage = residual`) shown verbatim from the
   authoritative backend ledger (never recomputed in the browser).
4. **Flood depth & extent maps** — colour-ramped depth map and binary extent map
   with a timeline slider (lead 0–180, 5-min steps), legend with units (m), and
   the extent threshold (0.05 m) shown.
5. **S3/S4 comparison** — side-by-side maps + difference table (capture, outfall,
   D2S return flow, surface storage, surcharge, peak depth, area) + the physical
   interpretation, explicitly stating that the small global peak-depth change
   does **not** mean blockage has no hydraulic effect.
6. **Scientific-status legend** — APPROVED / PROVISIONAL / SYNTHETIC / SIMULATED /
   ASSUMED / NOT FOR OPERATIONAL USE; no green "validated" styling for
   provisional science.

Every map image carries a visible provenance banner (SYNTHETIC / SIMULATED /
PROVISIONAL / NOT FOR OPERATIONAL USE).

## 5. Artifact Flow

```text
run_m5_diagnostics.py  (M5)  →  data/demo/m5/{results,comparison}.json + GeoTIFFs
                                          │
apps/api/store.py ─────────────────────────┘ (read-only)
apps/api/render.py ─── reads GeoTIFFs, renders PNG (in-memory cache)
apps/api/app.py ────── serves JSON + PNG + dashboard HTML
```

Depth GeoTIFFs are single-band float32 (m), EPSG:32645, with provenance tags
(`MODEL_PREDICTION`, `SYNTHETIC PROVISIONAL`, valid time, extent threshold,
simulation id) written by the M4 engine.

## 6. Provenance

Every scenario response preserves: scenario ID, rainfall-profile fingerprint,
drainage fingerprint, model version, engine version, dataset status
(SYNTHETIC), D-016 status (PREPARED — HUMAN REVIEW REQUIRED), assumptions,
limitations, provenance note, run ID, and scenario/run fingerprints. The
dashboard is an inspection layer, not a replacement for provenance.

## 7. Limitations

1. **Synthetic fixture** — results represent no real location or event; the 30 m
   grid is neighbourhood-scale flood screening, not street-scale truth.
2. **PROVISIONAL rainfall** — D-016 is PREPARED but not approved; profiles are
   NOT FOR OPERATIONAL USE.
3. **No live data / nowcast / routing** — those are M8–M10.
4. **Precomputed results only** — the dashboard shows the fixed M5 results; no
   simulation-on-demand is exposed (and none should be added without a
   separately-reviewed worker path).
5. **Single-file UI** — no map library; images are server-rendered PNGs (adequate
   for the 134×134 synthetic fixture, not a tile server).

## 8. Testing

`tests/test_m6_dashboard.py` (17 tests) covers scenario listing/retrieval, result
schema, provenance preservation, S3/S4 comparison, mass-balance values, artifact
existence, deterministic responses, and invalid/traversal inputs. The full M1–M5
suite remains green (no regression).

## 9. Local Run

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-spikes.txt
python3 scripts/run_dashboard.py      # http://127.0.0.1:8000
# UFNS_API_HOST / UFNS_API_PORT override (see .env.example)
```

## 10. Known Limitations / Scientific-Status Handling

- Provisional science is styled amber (not green "validated").
- The dashboard asserts nothing about real-world flood accuracy.
- Mass-balance "PASS" is a ledger/software gate, not a validation of flood depth.
