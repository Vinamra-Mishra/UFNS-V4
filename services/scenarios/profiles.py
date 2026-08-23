"""M5 rainfall-profile governance (M5 spec §6).

Every profile carries explicit status (APPROVED / PROVISIONAL / SIMULATED /
INVALID), derivation provenance, units, and fingerprint. Profiles are built
by the alternating-block method (Chow et al. 1988) — the same construction
already exercised in M4's rainfall scenarios — but with explicit metadata
and review-status handling required by M5.

Until D-016 (hyetograph derivation review) is approved, every profile has
status PROVISIONAL and must be labelled NOT FOR OPERATIONAL USE.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from services.rainfall.scenarios import alternating_block_hyetograph


# ---------------------------------------------------------------------------
# Profile status vocabulary
# ---------------------------------------------------------------------------

class ProfileStatus(str, Enum):
    APPROVED = "APPROVED"          # hydrologist-reviewed, accepted for use
    PROVISIONAL = "PROVISIONAL"    # methodologically sound but not yet reviewed
    SIMULATED = "SIMULATED"        # synthetic test profile, no real-world claim
    INVALID = "INVALID"            # rejected / withdrawn; must not be used


# ---------------------------------------------------------------------------
# M5 rainfall totals — documented, provisional.
#
# The three storm totals are illustrative fixture-scale design storms:
#   S1 normal:   20 mm / 3 h  (~moderate summer rain, ~7 mm/h average)
#   S2 heavy:    45 mm / 3 h  (~strong convective storm, ~15 mm/h average)
#   S3 extreme:  90 mm / 3 h  (~very severe event, ~30 mm/h average)
# These are NOT calibrated to any gauge record, return period, or IDF curve;
# D-016 requires hydrologist sign-off on a derived design storm before any
# operational or calibrated claim is made.
# ---------------------------------------------------------------------------

INTERVAL_MINUTES = 15
DURATION_MINUTES = 180
N_INTERVALS = DURATION_MINUTES // INTERVAL_MINUTES  # 12

PROFILE_DEFS: dict[str, dict[str, Any]] = {
    "P_NORMAL": {
        "profile_id": "P_NORMAL",
        "display_name": "Normal rainfall — 20 mm / 3 h",
        "total_mm": 20.0,
        "derivation": (
            "Alternating-block hyetograph (Chow, Maidment & Mays 1988, ch. 14) "
            "from provisional depth-duration P(d) = P60*(d/60)^0.4 anchored to "
            "total depth 20 mm over 180 minutes. Synthetic fixture storm; not "
            "derived from observed records or published Kolkata/West Bengal "
            "IDF curves. D-016 review required before operational use."
        ),
        "source": "UFNS synthetic (alternating-block, Chow et al. 1988)",
    },
    "P_HEAVY": {
        "profile_id": "P_HEAVY",
        "display_name": "Heavy rainfall — 45 mm / 3 h",
        "total_mm": 45.0,
        "derivation": (
            "Alternating-block hyetograph (Chow et al. 1988) from provisional "
            "depth-duration P(d) = P60*(d/60)^0.4 anchored to total depth "
            "45 mm over 180 minutes. Same method and exponent as M4 heavy "
            "profile for backward comparability. D-016 review required."
        ),
        "source": "UFNS synthetic (alternating-block, Chow et al. 1988)",
    },
    "P_EXTREME": {
        "profile_id": "P_EXTREME",
        "display_name": "Extreme rainfall — 90 mm / 3 h",
        "total_mm": 90.0,
        "derivation": (
            "Alternating-block hyetograph (Chow et al. 1988) from provisional "
            "depth-duration P(d) = P60*(d/60)^0.4 anchored to total depth "
            "90 mm over 180 minutes. Severe convective-storm magnitude chosen "
            "to stress the coupled system (drainage surcharge regime). D-016 "
            "review required."
        ),
        "source": "UFNS synthetic (alternating-block, Chow et al. 1988)",
    },
}


# ---------------------------------------------------------------------------
# Profile data class
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RainfallProfileRecord:
    """Immutable rainfall profile with full provenance (M5 §6)."""

    profile_id: str
    display_name: str
    derivation: str
    source: str
    temporal_resolution_minutes: int
    duration_minutes: int
    total_depth_mm: float
    peak_intensity_mmh: float
    intensities_mmh: tuple[float, ...]
    spatial_policy: str
    alternating_block_order: str
    units: str
    review_status: ProfileStatus
    d016_review_status: str  # "PENDING" | "PREPARED" | "APPROVED" | "NOT_REQUIRED"
    limitations: tuple[str, ...]
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "display_name": self.display_name,
            "derivation": self.derivation,
            "source": self.source,
            "temporal_resolution_minutes": self.temporal_resolution_minutes,
            "duration_minutes": self.duration_minutes,
            "total_depth_mm": self.total_depth_mm,
            "peak_intensity_mmh": round(self.peak_intensity_mmh, 4),
            "intensities_mmh": [round(v, 4) for v in self.intensities_mmh],
            "spatial_policy": self.spatial_policy,
            "alternating_block_order": self.alternating_block_order,
            "units": self.units,
            "review_status": self.review_status.value,
            "d016_review_status": self.d016_review_status,
            "limitations": list(self.limitations),
            "fingerprint": self.fingerprint,
        }


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

_EXPONENT = 0.4  # PROVISIONAL depth-duration exponent; subject to D-016


def _fingerprint(profile_id: str, total_mm: float, interval_min: int,
                 duration_min: int, exponent: float, intensities: tuple[float, ...]) -> str:
    payload = json.dumps(
        {
            "profile_id": profile_id,
            "total_mm": total_mm,
            "interval_min": interval_min,
            "duration_min": duration_min,
            "exponent": exponent,
            "intensities": [round(v, 8) for v in intensities],
        },
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# D-016 derivation is now SCIENTIFICALLY PREPARED from a published,
# peer-reviewed IDF source (Kumar & Remesan 2026, Bagjola Canal basin / Kolkata;
# see docs/D016_RAINFALL_DERIVATION.md and services/rainfall/idf.py).
# A hydrologist must still approve the derivation and the return-period ->
# scenario-label mapping before any operational use. No approval is fabricated.
D016_STATUS = "PREPARED"                 # scientifically prepared
D016_HUMAN_REVIEW = "REQUIRED"           # hydrologist sign-off still pending

_STANDARD_LIMITATIONS = (
    "PROVISIONAL: derived by alternating-block method from an assumed "
    "depth-duration curve, not from observed IDF or gauge records.",
    "NOT FOR OPERATIONAL USE: scenario magnitudes are illustrative for "
    "fixture-scale testing only.",
    "NOT REAL-WORLD CALIBRATED: depth-duration exponent 0.4 is a standard "
    "textbook value, not fitted to pilot-region rainfall.",
    f"Spatial pattern: seeded convective-cell field (deterministic, seed "
    f"{20260821}); not a radar or NWP product.",
    f"D-016 review status: {D016_STATUS} — HUMAN REVIEW REQUIRED. Final "
    f"approval requires hydrologist sign-off on the published-IDF derivation "
    f"(see docs/D016_RAINFALL_DERIVATION.md).",
)


def build_profile_record(profile_key: str) -> RainfallProfileRecord:
    """Construct a single profile record with full provenance."""
    if profile_key not in PROFILE_DEFS:
        raise KeyError(f"unknown profile key: {profile_key}; "
                       f"known: {sorted(PROFILE_DEFS)}")
    d = PROFILE_DEFS[profile_key]
    total_mm = float(d["total_mm"])
    intensities = tuple(
        alternating_block_hyetograph(total_mm, DURATION_MINUTES, INTERVAL_MINUTES,
                                     exponent=_EXPONENT)
    )
    peak = max(intensities) if intensities else 0.0
    fp = _fingerprint(d["profile_id"], total_mm, INTERVAL_MINUTES, DURATION_MINUTES,
                      _EXPONENT, intensities)
    return RainfallProfileRecord(
        profile_id=d["profile_id"],
        display_name=d["display_name"],
        derivation=d["derivation"],
        source=d["source"],
        temporal_resolution_minutes=INTERVAL_MINUTES,
        duration_minutes=DURATION_MINUTES,
        total_depth_mm=total_mm,
        peak_intensity_mmh=peak,
        intensities_mmh=intensities,
        spatial_policy="convective_cell (seeded, deterministic; M2 renderer)",
        alternating_block_order="largest increment at storm centre, alternating outward (Chow et al. 1988)",
        units="mm/h (intensity); mm (total depth)",
        review_status=ProfileStatus.PROVISIONAL,
        d016_review_status=D016_STATUS,
        limitations=_STANDARD_LIMITATIONS,
        fingerprint=fp,
    )


def all_profiles() -> dict[str, RainfallProfileRecord]:
    """Return all M5 rainfall profiles, keyed by profile_id."""
    return {key: build_profile_record(key) for key in PROFILE_DEFS}


# ---------------------------------------------------------------------------
# Rainfall severity label definitions (M5 §6: no undocumented "normal/heavy")
# ---------------------------------------------------------------------------

SEVERITY_DEFINITIONS: dict[str, dict[str, Any]] = {
    "NORMAL": {
        "label": "NORMAL",
        "total_depth_mm": 20.0,
        "duration_hours": 3.0,
        "average_intensity_mmh": 20.0 / 3.0,
        "criterion": (
            "Moderate short-duration rain; expected to produce only shallow "
            "surface water with effective drainage (capture regime)."
        ),
    },
    "HEAVY": {
        "label": "HEAVY",
        "total_depth_mm": 45.0,
        "duration_hours": 3.0,
        "average_intensity_mmh": 45.0 / 3.0,
        "criterion": (
            "Strong convective storm; drainage operates but surface ponding "
            "develops; used as M4 heavy baseline."
        ),
    },
    "EXTREME": {
        "label": "EXTREME",
        "total_depth_mm": 90.0,
        "duration_hours": 3.0,
        "average_intensity_mmh": 90.0 / 3.0,
        "criterion": (
            "Very severe event that stresses the drainage system into "
            "surcharge; chosen to demonstrate blockage sensitivity (S3/S4)."
        ),
    },
}
