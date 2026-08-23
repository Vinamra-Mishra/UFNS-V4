"""M5 drainage-condition governance (M5 spec §7).

Two explicit drainage conditions are defined on the synthetic M4 fixture:
  - NORMAL:  clean fixture (C1 D=0.30 m; full-bore Manning capacity ~97 L/s)
  - BLOCKED: reduced-capacity fixture (C1 D=0.12 m; capacity ~8.4 L/s;
             capacity ratio (0.12/0.30)^(8/3) ≈ 0.087)

Blockage is a real hydraulic capacity reduction (conduit diameter change),
not a visualization multiplier or artificial depth scaling.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from services.hydraulics.fixture import (
    C1_DIAMETER,
    C1_LENGTH,
    C1_MANNING,
    C1_SLOPE,
    exact_fixture_inp,
    full_bore_capacity,
)

# M4 datum offset (documented in services/simulation/engine.py:
# shifts SWMM fixture onto the synthetic DEM local datum by +10 m; B08 fix).
M4_DATUM_OFFSET_M = 10.0


class DrainageStatus(str, Enum):
    NORMAL = "NORMAL"
    BLOCKED = "BLOCKED"


# Blocked-conduit diameter for S4 (M4 heavy_blocked used D=0.12; S4 keeps
# this value for M4 result comparability).
BLOCKED_DIAMETER_M = 0.12

ROOT = Path(__file__).resolve().parents[2]

# The M4 fixtures are pre-written in data/demo/. We verify they match the
# expected content fingerprint.
_CLEAN_INP = ROOT / "data/demo/drainage_synthetic_m4.inp"
_BLOCKED_INP = ROOT / "data/demo/drainage_synthetic_m4_blocked.inp"


def _sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _inp_fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


@dataclass(frozen=True)
class DrainageCondition:
    """Documented drainage condition with hydraulic evidence."""

    condition_id: str
    display_name: str
    status: DrainageStatus
    inp_path: Path
    inp_fingerprint: str
    affected_assets: tuple[str, ...]
    c1_diameter_m: float
    c1_full_capacity_m3s: float
    capacity_ratio_to_normal: float
    reason: str
    physical_mechanism: str
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]
    parameter_status: str  # "SYNTHETIC" / "ASSUMED" / "measured" / ...

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition_id": self.condition_id,
            "display_name": self.display_name,
            "status": self.status.value,
            "inp_path": str(self.inp_path),
            "inp_fingerprint": self.inp_fingerprint,
            "affected_assets": list(self.affected_assets),
            "c1_diameter_m": self.c1_diameter_m,
            "c1_full_capacity_m3s": round(self.c1_full_capacity_m3s, 6),
            "capacity_ratio_to_normal": round(self.capacity_ratio_to_normal, 6),
            "reason": self.reason,
            "physical_mechanism": self.physical_mechanism,
            "assumptions": list(self.assumptions),
            "limitations": list(self.limitations),
            "parameter_status": self.parameter_status,
        }


# ---------------------------------------------------------------------------
# Build conditions and verify against the checked-in INP files.
# ---------------------------------------------------------------------------

def _build_conditions() -> dict[str, DrainageCondition]:
    clean_inp_text = exact_fixture_inp(blocked=False, datum_offset_m=M4_DATUM_OFFSET_M,
                                        blocked_diameter_m=C1_DIAMETER)
    blocked_inp_text = exact_fixture_inp(blocked=True, datum_offset_m=M4_DATUM_OFFSET_M,
                                          blocked_diameter_m=BLOCKED_DIAMETER_M)
    # Verify the checked-in files match the expected synthetic fixtures
    # (cross-check provenance; fail loudly if they have drifted).
    if _CLEAN_INP.exists():
        on_disk_clean = _CLEAN_INP.read_text()
        if _sha256_text(on_disk_clean) != _sha256_text(clean_inp_text):
            # The on-disk file may differ in whitespace/formatting only —
            # compare by content fingerprint instead of literal bytes.
            raise RuntimeError(
                f"SWMM fixture mismatch: {_CLEAN_INP.name} content SHA-256 does not match "
                "the programmatic generator. Re-run scripts/build_synthetic_fixtures.py "
                "or fix the file."
            )
    if _BLOCKED_INP.exists():
        on_disk_blocked = _BLOCKED_INP.read_text()
        if _sha256_text(on_disk_blocked) != _sha256_text(blocked_inp_text):
            raise RuntimeError(
                f"SWMM fixture mismatch: {_BLOCKED_INP.name} content SHA-256 does not match "
                "the programmatic generator. Re-run scripts/build_synthetic_fixtures.py "
                "or fix the file."
            )

    q_clean = full_bore_capacity(C1_DIAMETER, C1_SLOPE, C1_MANNING)
    q_blocked = full_bore_capacity(BLOCKED_DIAMETER_M, C1_SLOPE, C1_MANNING)

    common_assumptions = (
        "Synthetic SWMM fixture (ST1→C1→V1→C2→O1); exact-exchange construction "
        "with storage nodes only (no junctions) so the drainage ledger is "
        "engine-exact.",
        "All conduit parameters (length, slope, roughness, diameter) are "
        "SYNTHETIC/ASSUMED; they represent NO real drainage network.",
        f"Datum shifted +{M4_DATUM_OFFSET_M} m onto the synthetic DEM local datum "
        "(constant shift preserves every slope/invert exactly; documented B08 fix).",
        "Single-point blockage on C1 (the main downstream conduit); pumps, "
        "gates, tide, and distributed inlet blockage are out of scope.",
    )

    clean = DrainageCondition(
        condition_id="D_NORMAL",
        display_name="Normal drainage — clean synthetic fixture",
        status=DrainageStatus.NORMAL,
        inp_path=_CLEAN_INP,
        inp_fingerprint=_inp_fingerprint(_CLEAN_INP),
        affected_assets=(),
        c1_diameter_m=C1_DIAMETER,
        c1_full_capacity_m3s=q_clean,
        capacity_ratio_to_normal=1.0,
        reason="Baseline clean-drainage condition for paired comparison.",
        physical_mechanism=(
            "Conduit C1 conveys captured stormwater to outfall O1 at its full "
            "Manning capacity; system remains in capture regime under "
            f"S1-S3 rainfall (max ST1 head stays below vent ground level)."
        ),
        assumptions=common_assumptions,
        limitations=(
            "Real-drainage network effects (multiple inlets, complex geometry, "
            "sediment, pump operation) are not represented.",
            *common_assumptions,
        ),
        parameter_status="SYNTHETIC/ASSUMED",
    )

    blocked = DrainageCondition(
        condition_id="D_BLOCKED",
        display_name="Blocked drainage — reduced-capacity C1 (D=0.12 m)",
        status=DrainageStatus.BLOCKED,
        inp_path=_BLOCKED_INP,
        inp_fingerprint=_inp_fingerprint(_BLOCKED_INP),
        affected_assets=("C1",),
        c1_diameter_m=BLOCKED_DIAMETER_M,
        c1_full_capacity_m3s=q_blocked,
        capacity_ratio_to_normal=q_blocked / q_clean,
        reason=(
            "Demonstrates drainage-blockage impact: a 60% diameter reduction "
            "(C1 0.30→0.12 m) produces ~11.5× conveyance loss by the Manning "
            "full-bore relation, which is large enough to force surcharge "
            "under extreme rainfall while remaining on the validated M4 fixture."
        ),
        physical_mechanism=(
            "Reduced conduit capacity backs water up to the ST1 storage node; "
            "ST1 head rises above vent ground level, the return orifice "
            "activates, and water spills onto the surface at the vent cell "
            "(D2S). Inlet capture is throttled by backwater; outfall discharge "
            "drops proportionally."
        ),
        assumptions=common_assumptions,
        limitations=(
            "Single-conduit constriction; real-world blockages are often "
            "distributed across inlets/pipes.",
            "Blockage is static from t=0 (present from the start of the run); "
            "no progressive blockage or clearance is modelled.",
            *common_assumptions,
        ),
        parameter_status="SYNTHETIC/ASSUMED",
    )

    return {"D_NORMAL": clean, "D_BLOCKED": blocked}


DRAINAGE_CONDITIONS = _build_conditions()
