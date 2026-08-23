"""B13 — Vehicle passability policy (B13-DEMO-V1, PROVISIONAL DEMONSTRATION).

Vehicle/road passability thresholds are UNRESOLVED (IMPLEMENTATION_SPEC §4
B13, DECISIONS D-012/D-013). No expert-approved or operational threshold is
claimed anywhere in UFNS.

This module defines a single, centralized, configurable, versioned and
fingerprinted PROVISIONAL DEMONSTRATION POLICY. Thresholds are kept here —
never scattered through the code — so that a future human-approved policy can
replace B13-DEMO-V1 in one place without touching sampling, impact, routing or
UI code.

Severity bands reuse the demo bands already recorded in D-013 (0.05 / 0.15 /
0.30 m) and add a 0.50 m demonstration "impassable" cutoff. These are
demonstration severity bands, NOT safety standards.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Centralized, versioned policy constants
# ---------------------------------------------------------------------------

POLICY_ID = "B13-DEMO-V1"
POLICY_STATUS = "PROVISIONAL_DEMONSTRATION"  # NOT expert-approved
POLICY_VERSION = 1

# Impact classification thresholds (metres of simulated water depth).
#   DRY:          depth <= dry_m
#   LOW_IMPACT:   dry_m   < depth <= low_m
#   CAUTION:      low_m   < depth <= caution_m
#   HIGH_IMPACT:  caution_m < depth <= impassable_m
#   IMPASSABLE:   impassable_m < depth
THRESHOLDS: dict[str, float] = {
    "dry_m": 0.05,
    "low_m": 0.15,
    "caution_m": 0.30,
    "impassable_m": 0.50,
}

# A road cell is "impacted" (counted toward impacted_fraction / impacted length)
# when its simulated depth exceeds this value. Matches the M5 extent threshold
# (0.05 m) so road impact and flood extent use a consistent notion of "wet".
IMPACTED_DEPTH_THRESHOLD_M: float = 0.05

# Routing speed factors per impact class. A factor < 1.0 penalises travel on a
# flooded road by reducing its effective speed (documented, configurable — not
# an arbitrary hidden weight). IMPASSABLE roads are excluded from the graph.
SPEED_FACTORS: dict[str, float] = {
    "DRY": 1.0,
    "LOW_IMPACT": 0.7,
    "CAUTION": 0.5,
    "HIGH_IMPACT": 0.3,
    # IMPASSABLE: excluded (no speed factor)
}

# Road classes -> baseline free-flow speed (km/h). SYNTHETIC / ASSUMED.
BASELINE_SPEED_KMH: dict[str, float] = {
    "primary": 50.0,
    "secondary": 40.0,
    "local": 30.0,
}

# Ordered classification ladder (index order == severity order).
CLASS_ORDER = ("DRY", "LOW_IMPACT", "CAUTION", "HIGH_IMPACT", "IMPASSABLE")


from types import MappingProxyType

@dataclass(frozen=True)
class PassabilityPolicy:
    """The active passability policy (frozen, versioned, fingerprinted)."""

    policy_id: str
    status: str
    version: int
    thresholds: MappingProxyType[str, float]
    impacted_depth_threshold_m: float
    speed_factors: MappingProxyType[str, float]
    baseline_speed_kmh: MappingProxyType[str, float]
    disclaimer: str
    fingerprint: str

    def __init__(self, policy_id: str, status: str, version: int, thresholds: dict[str, float], impacted_depth_threshold_m: float, speed_factors: dict[str, float], baseline_speed_kmh: dict[str, float], disclaimer: str):
        object.__setattr__(self, "policy_id", policy_id)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "version", version)
        
        sealed_thresholds = MappingProxyType(dict(thresholds))
        object.__setattr__(self, "thresholds", sealed_thresholds)
        
        object.__setattr__(self, "impacted_depth_threshold_m", impacted_depth_threshold_m)
        
        sealed_speed = MappingProxyType(dict(speed_factors))
        object.__setattr__(self, "speed_factors", sealed_speed)
        
        sealed_base = MappingProxyType(dict(baseline_speed_kmh))
        object.__setattr__(self, "baseline_speed_kmh", sealed_base)
        
        object.__setattr__(self, "disclaimer", disclaimer)
        
        payload = {
            "policy_id": policy_id,
            "status": status,
            "version": version,
            "thresholds": dict(sealed_thresholds),
            "impacted_depth_threshold_m": impacted_depth_threshold_m,
            "speed_factors": dict(sealed_speed),
            "baseline_speed_kmh": dict(sealed_base),
            "class_order": CLASS_ORDER,
        }
        canon = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        fp = hashlib.sha256(canon.encode("utf-8")).hexdigest()
        object.__setattr__(self, "fingerprint", fp)

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "status": self.status,
            "version": self.version,
            "thresholds": dict(self.thresholds),
            "impacted_depth_threshold_m": self.impacted_depth_threshold_m,
            "speed_factors": dict(self.speed_factors),
            "baseline_speed_kmh": dict(self.baseline_speed_kmh),
            "disclaimer": self.disclaimer,
            "fingerprint": self.fingerprint,
            "approved": False,
        }


DISCLAIMER = (
    "Vehicle passability: PROVISIONAL DEMONSTRATION POLICY. "
    "Not an operational safety recommendation. Thresholds are demonstration "
    "severity bands, not expert-approved or universal public-safety limits."
)

POLICY = PassabilityPolicy(
    policy_id=POLICY_ID,
    status=POLICY_STATUS,
    version=POLICY_VERSION,
    thresholds=THRESHOLDS,
    impacted_depth_threshold_m=IMPACTED_DEPTH_THRESHOLD_M,
    speed_factors=SPEED_FACTORS,
    baseline_speed_kmh=BASELINE_SPEED_KMH,
    disclaimer=DISCLAIMER,
)


def classify(max_depth_m: float, policy: PassabilityPolicy = POLICY) -> str:
    """Map a road's maximum sampled depth (m) to an impact class."""
    t = policy.thresholds
    if max_depth_m <= t["dry_m"]:
        return "DRY"
    if max_depth_m <= t["low_m"]:
        return "LOW_IMPACT"
    if max_depth_m <= t["caution_m"]:
        return "CAUTION"
    if max_depth_m <= t["impassable_m"]:
        return "HIGH_IMPACT"
    return "IMPASSABLE"


def passability(classification: str) -> str:
    """PASSABLE for every class except IMPASSABLE."""
    return "IMPASSABLE" if classification == "IMPASSABLE" else "PASSABLE"


def speed_factor(classification: str, policy: PassabilityPolicy = POLICY) -> float:
    """Routing speed factor for an impact class (IMPASSABLE has none)."""
    if classification == "IMPASSABLE":
        raise ValueError("IMPASSABLE roads are excluded; no speed factor exists")
    return policy.speed_factors[classification]
