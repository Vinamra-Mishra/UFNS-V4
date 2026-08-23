"""M6 result store — reads precomputed M5 artifacts (no simulation re-run).

The M6 dashboard/API is an inspection layer. It consumes the authoritative,
precomputed scenario results (``data/demo/m5/m5_results.json`` and
``data/demo/m5/m5_comparison.json``) and merges in the live scenario
definitions (``services.scenarios.registry.M5_SCENARIOS``) so that every
response carries full provenance (assumptions, limitations, fingerprints,
model version, dataset status).

The hydraulic simulation is NEVER re-run by this module (IMPLEMENTATION_SPEC
M6 §performance): scenario registry -> precomputed ScenarioResult -> API ->
dashboard.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from services.scenarios import MODEL_VERSION
from services.scenarios.profiles import D016_STATUS, D016_HUMAN_REVIEW
from services.scenarios.registry import M5_SCENARIOS

# Repository root: apps/api/store.py -> apps/api -> apps -> root
REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = REPO_ROOT / "data" / "demo" / "m5"

RESULTS_JSON = ARTIFACT_ROOT / "m5_results.json"
COMPARISON_JSON = ARTIFACT_ROOT / "m5_comparison.json"

VALID_SCENARIO_IDS = ("S1", "S2", "S3", "S4")


class StoreError(Exception):
    """Raised when the precomputed artifacts are missing or malformed."""


@lru_cache(maxsize=1)
def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise StoreError(f"precomputed artifact missing: {path}")
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise StoreError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise StoreError(f"unexpected JSON structure in {path}")
    return data


def load_results() -> dict[str, dict[str, Any]]:
    """Per-scenario result summaries, keyed by scenario id (S1..S4)."""
    data = _load_json(RESULTS_JSON)
    for sid in VALID_SCENARIO_IDS:
        if sid not in data:
            raise StoreError(f"m5_results.json missing scenario {sid}")
    return data


def load_comparison() -> dict[str, Any]:
    """The deterministic M5 comparison artifact (incl. S3/S4 blockage diff)."""
    return _load_json(COMPARISON_JSON)


def _scenario_def(sid: str):
    """Live scenario definition (full provenance) from the M5 registry."""
    if sid not in M5_SCENARIOS:
        return None
    return M5_SCENARIOS[sid]


def scenario_metadata(sid: str) -> dict[str, Any]:
    """Full scenario metadata merged from the live definition + precomputed result."""
    s = _scenario_def(sid)
    if s is None:
        return {}
    results = load_results()
    r = results.get(sid, {})
    profile = s.rainfall_profile
    drain = s.drainage_condition
    return {
        "scenario_id": sid,
        "display_name": s.display_name,
        "description": s.description,
        "rainfall_profile": profile.to_dict(),
        "rainfall_profile_id": profile.profile_id,
        "rainfall_status": s.rainfall_status,
        "drainage_condition": drain.to_dict(),
        "duration_minutes": s.duration_minutes,
        "start_time": s.start_time.isoformat(),
        "coupling_timestep_s": s.coupling_timestep_s,
        "snapshot_interval_minutes": s.snapshot_interval_minutes,
        "surface_config_fingerprint": s.surface_config_fingerprint,
        "swmm_fixture_fingerprint": s.swmm_fixture_fingerprint,
        "scenario_fingerprint": s.fingerprint,
        "extent_threshold_m": s.extent_threshold_m,
        "assumptions": list(s.assumptions),
        "limitations": list(s.limitations),
        "provenance": s.provenance_note,
        "model_version": MODEL_VERSION,
        "engine_version": r.get("engine_version", ""),
        "run_id": r.get("run_id", ""),
        "dataset_status": "SYNTHETIC",
        "d016_status": D016_STATUS,
        "d016_human_review": D016_HUMAN_REVIEW,
        "labels": ["SYNTHETIC", "SIMULATED", "PROVISIONAL"],
        "not_for_operational_use": True,
    }


def scenario_result(sid: str) -> dict[str, Any]:
    """The authoritative precomputed ScenarioResult for one scenario."""
    results = load_results()
    r = results.get(sid)
    if r is None:
        return {}
    # Deep copy so callers cannot mutate the cached store.
    out = dict(r)
    # Normalise any absolute artifact URIs away; the API derives artifact paths
    # itself (no path traversal). Keep snapshot_inventory but strip absolute paths.
    out["snapshot_inventory"] = [
        {k: v for k, v in snap.items() if k != "depth_asset_uri"}
        for snap in r.get("snapshot_inventory", [])
    ]
    # Always attach current D-016 status (authoritative, not stale JSON text).
    out["d016_status"] = D016_STATUS
    out["d016_human_review"] = D016_HUMAN_REVIEW
    out["not_for_operational_use"] = True
    return out


def list_scenarios() -> list[dict[str, Any]]:
    """Scenario list with status labels (never hides scientific status)."""
    results = load_results()
    out: list[dict[str, Any]] = []
    for sid in VALID_SCENARIO_IDS:
        s = _scenario_def(sid)
        r = results.get(sid, {})
        if s is None:
            continue
        out.append({
            "scenario_id": sid,
            "display_name": s.display_name,
            "rainfall_profile_id": s.rainfall_profile.profile_id,
            "rainfall_total_mm": s.rainfall_profile.total_depth_mm,
            "rainfall_status": s.rainfall_status,
            "drainage_condition": s.drainage_condition.status.value,
            "drainage_fingerprint": s.drainage_condition.inp_fingerprint,
            "peak_depth_m": r.get("peak_depth_m"),
            "max_flooded_area_m2": r.get("max_flooded_area_m2"),
            "mass_gate": (r.get("mass_ledger") or {}).get("gate"),
            "scenario_fingerprint": s.fingerprint,
            "dataset_status": "SYNTHETIC",
            "d016_status": D016_STATUS,
            "labels": ["SYNTHETIC", "SIMULATED", "PROVISIONAL"],
        })
    return out


def s3s4_comparison() -> dict[str, Any]:
    """S3/S4 paired blockage comparison (authoritative, precomputed)."""
    comp = load_comparison()
    return {
        "comparison": comp.get("s3s4_blockage_comparison", {}),
        "comparability_controls": comp.get("comparability_controls", {}),
        "model_version": comp.get("model_version", MODEL_VERSION),
        "d016_status": D016_STATUS,
        "d016_human_review": D016_HUMAN_REVIEW,
        "labels": ["SYNTHETIC", "SIMULATED", "PROVISIONAL"],
    }


def snapshot_timeline(sid: str) -> list[dict[str, Any]]:
    """Per-snapshot timeline for one scenario (lead-aligned)."""
    r = scenario_result(sid)
    return r.get("snapshot_inventory", [])


def artifact_tif_path(sid: str, lead_minutes: int) -> Path:
    """Derive the depth GeoTIFF path for a scenario/lead (no client paths)."""
    # Snapshot cadence is fixed at 5 min; validate against the known inventory.
    timeline = snapshot_timeline(sid)
    known_leads = {snap["lead_minutes"] for snap in timeline}
    if lead_minutes not in known_leads:
        raise KeyError(f"lead {lead_minutes} not in {sid} snapshot inventory")
    return ARTIFACT_ROOT / sid.lower() / f"depth_t{lead_minutes:03d}.tif"
