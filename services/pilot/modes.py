"""M11 — Real-pilot model capability modes and real/synthetic labels.

M11 establishes an explicit capability/state model so the system can consume
real drainage geometry WITHOUT claiming that hydraulic simulation of those
drains is scientifically valid.

The fundamental distinction (MANDATORY):

    REAL DRAINAGE GEOMETRY   ≠   REAL HYDRAULIC NETWORK

The real WB AMRUT drainage data carries geometry but NOT the five required
hydraulic attributes (diameter_m, invert_upstream_m, invert_downstream_m,
manning_n, capacity_m3s). Therefore the system reports:

    REAL_GEOMETRY_AVAILABLE  = True   (when geometry is mapped)
    HYDRAULIC_PARAMETERS_MISSING = True
    HYDRAULIC_NETWORK_READY   = False

Model modes (every result must identify its mode; modes are never mixed):

    MODE A — REAL_TERRAIN / REAL_DRAINAGE_GEOMETRY
        Real DEM + real drainage geometry + real provenance.
        Does NOT claim hydraulic drainage simulation (hydraulics absent).

    MODE B — REAL_TERRAIN / SYNTHETIC_HYDRAULICS
        Real DEM + explicitly labelled SYNTHETIC/ASSUMED hydraulic fixture.
        Validates that real terrain can pass through the existing coupled
        model while keeping synthetic hydraulics explicitly labelled.
        Result label: REAL_TERRAIN_SYNTHETIC_HYDRAULICS.

    MODE C — SYNTHETIC_BASELINE
        Historical M1-M9 fixture behaviour (synthetic DEM + synthetic
        hydraulics). Regression-compatible. Result label: SYNTHETIC.

Hard gate: a result containing real DEM must never become SYNTHETIC; a result
containing synthetic hydraulic parameters must never become REAL_DATA.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PilotModelMode(str, Enum):
    """M11 model capability modes (Section 7). Never mixed within one result."""

    MODE_A_REAL_TERRAIN_REAL_DRAINAGE = "MODE_A_REAL_TERRAIN_REAL_DRAINAGE_GEOMETRY"
    MODE_B_REAL_TERRAIN_SYNTHETIC_HYDRAULICS = "MODE_B_REAL_TERRAIN_SYNTHETIC_HYDRAULICS"
    MODE_C_SYNTHETIC_BASELINE = "MODE_C_SYNTHETIC_BASELINE"


# Governed result-content labels (Section 14). These describe WHAT the result
# is made of; they are never generic and never hide a synthetic component.
LABEL_REAL_TERRAIN_SYNTHETIC_HYDRAULICS = "REAL_TERRAIN_SYNTHETIC_HYDRAULICS"
LABEL_REAL_TERRAIN_REAL_DRAINAGE_GEOMETRY = "REAL_TERRAIN_REAL_DRAINAGE_GEOMETRY"
LABEL_SYNTHETIC = "SYNTHETIC"
LABEL_MISSING = "MISSING"
LABEL_UNRESOLVED = "UNRESOLVED"
LABEL_ASSUMED = "ASSUMED"
LABEL_PROVISIONAL = "PROVISIONAL"
LABEL_NOT_REAL_TIME = "NOT_REAL_TIME"
LABEL_NOT_VALIDATED_FORECAST = "NOT_VALIDATED_FORECAST"


def content_label_for_mode(mode: PilotModelMode) -> str:
    """The governed content label a result of ``mode`` must carry."""
    if mode == PilotModelMode.MODE_B_REAL_TERRAIN_SYNTHETIC_HYDRAULICS:
        return LABEL_REAL_TERRAIN_SYNTHETIC_HYDRAULICS
    if mode == PilotModelMode.MODE_A_REAL_TERRAIN_REAL_DRAINAGE:
        return LABEL_REAL_TERRAIN_REAL_DRAINAGE_GEOMETRY
    return LABEL_SYNTHETIC


@dataclass(frozen=True)
class PilotCapabilityState:
    """Explicit capability/state model (Section 6).

    Records whether real geometry is available and whether a real hydraulic
    network is ready. A real-pilot result may have real geometry available
    while a hydraulic network is NOT ready (the Bagjola/Kolkata pilot case).
    """

    real_terrain_available: bool
    real_geometry_available: bool
    hydraulic_parameters_present: bool
    hydraulic_network_ready: bool
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "real_terrain_available": self.real_terrain_available,
            "real_geometry_available": self.real_geometry_available,
            "hydraulic_parameters_present": self.hydraulic_parameters_present,
            "hydraulic_network_ready": self.hydraulic_network_ready,
            "reason": self.reason,
        }
