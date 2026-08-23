"""M11 — Real-pilot inspection store (API/Dashboard, Section 17).

Reads the precomputed M11 real-pilot inspection artifact
(``data/demo/m11/pilot_inspection.json``) produced by
``scripts/run_m11_real_pilot_validation.py``. The API is an inspection layer
and NEVER re-runs the hydraulic simulation to serve a request.

Truthfulness guarantees (Section 17): the view distinguishes REAL_PILOT /
SYNTHETIC / PROVISIONAL / ASSUMED / MISSING / UNRESOLVED / NOT_REAL_TIME /
NOT_VALIDATED_FORECAST, and never implies operational forecasting, validated
forecast skill, certified road safety, or real drainage hydraulic capacity.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from services.scenarios.profiles import D016_HUMAN_REVIEW, D016_STATUS

REPO_ROOT = Path(__file__).resolve().parents[2]
INSPECTION_JSON = REPO_ROOT / "data" / "demo" / "m11" / "pilot_inspection.json"


class PilotStoreError(Exception):
    """Raised when the precomputed M11 inspection artifact is missing."""


@lru_cache(maxsize=1)
def _load() -> dict[str, Any]:
    if not INSPECTION_JSON.exists():
        raise PilotStoreError(
            "M11 real-pilot inspection artifact missing: run "
            "`python scripts/run_m11_real_pilot_validation.py` first"
        )
    try:
        with INSPECTION_JSON.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise PilotStoreError(f"invalid JSON in {INSPECTION_JSON}: {exc}") from exc
    if not isinstance(data, dict):
        raise PilotStoreError(f"unexpected JSON structure in {INSPECTION_JSON}")
    return data


def inspection_available() -> bool:
    return INSPECTION_JSON.exists()


def reset_cache() -> None:
    """Clear the cached inspection (used by tests)."""
    _load.cache_clear()


def pilot_overview() -> dict[str, Any]:
    """Top-level real-pilot inspection overview."""
    data = _load()
    return {
        "overall_gate": data.get("overall_gate"),
        "dem_provenance": data.get("dem_provenance"),
        "gridspec": data.get("gridspec"),
        "gridspec_fingerprint": data.get("gridspec_fingerprint"),
        "drainage_coverage": data.get("drainage_coverage"),
        "hydraulic_readiness": _slim_contract(data.get("hydraulic_readiness")),
        "model_modes": data.get("model_modes"),
        "model_mode_executed": data.get("model_mode_executed"),
        "rainfall_status": {
            **data.get("rainfall_status", {}),
            "d016_status": D016_STATUS,
            "d016_human_review": D016_HUMAN_REVIEW,
        },
        "simulation_availability": data.get("simulation_availability"),
        "labels": data.get("labels"),
        "not_for_operational_use": True,
    }


def pilot_dem() -> dict[str, Any]:
    data = _load()
    return {
        "dem_provenance": data.get("dem_provenance"),
        "gridspec": data.get("gridspec"),
        "labels": ["REAL_DATA", "REAL_TERRAIN", "PROVISIONAL"],
        "not_for_operational_use": True,
    }


def pilot_drainage() -> dict[str, Any]:
    data = _load()
    cov = data.get("drainage_coverage", {})
    return {
        "drainage_coverage": cov,
        "mapped_count": cov.get("mapped_count"),
        "unresolved_count": cov.get("unresolved_count"),
        "rejected_count": cov.get("rejected_count"),
        "rejection_breakdown": cov.get("rejection_breakdown"),
        "labels": ["REAL_DATA", "REAL_DRAINAGE_GEOMETRY", "UNRESOLVED", "PROVISIONAL"],
        "note": (
            "Real drainage GEOMETRY only — NOT a real hydraulic network "
            "(hydraulic parameters MISSING). MultiPoint vents handled by "
            "contract, never coerced to lines."
        ),
        "not_for_operational_use": True,
    }


def pilot_hydraulic_readiness() -> dict[str, Any]:
    data = _load()
    return {
        "hydraulic_readiness": _slim_contract(data.get("hydraulic_readiness")),
        "labels": ["MISSING", "ASSUMED", "PROVISIONAL"],
        "not_for_operational_use": True,
    }


def _slim_contract(contract: Any) -> dict[str, Any]:
    if not isinstance(contract, dict):
        return {}
    return {
        "required_attributes": contract.get("required_attributes"),
        "missing_attributes": contract.get("missing_attributes"),
        "assumed_attributes": contract.get("assumed_attributes"),
        "unresolved_attributes": contract.get("unresolved_attributes"),
        "real_hydraulic_network_ready": contract.get("real_hydraulic_network_ready"),
        "synthetic_fixture_labelled": contract.get("synthetic_fixture_labelled"),
        "hydraulic_network_ready": contract.get("hydraulic_network_ready"),
        "notes": contract.get("notes"),
    }
