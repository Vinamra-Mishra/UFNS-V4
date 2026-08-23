"""M11 — Real-pilot model integration layer.

Integrates the validated Bagjola/Kolkata real pilot into the existing UFNS
modelling stack through explicit, auditable contracts. Real data enters the
model through adapters; where the real data is insufficient for a scientific
operation (hydraulic parameters absent), the operation is STOPPED at the
contract boundary — never filled with an assumption unless that assumption is
explicitly governed, labelled, and approved for that exact purpose.

Architecture (Section 9):

        existing engine (services/simulation/engine.py)
                ↑
        M11 adapter (services/pilot/adapter.py)
                ↑
        real pilot data (normalized DEM + mapped drainage)

See docs/M11_REAL_PILOT_INTEGRATION.md for the full M11 report.
"""

from __future__ import annotations

from services.pilot.adapter import (
    DEFAULT_MODEB_DURATION_MIN,
    DEFAULT_N_INLETS,
    DEFAULT_ROI_OFFSET,
    DEFAULT_ROI_WINDOW,
    M11SimulationAdapter,
    PilotROI,
    RealCellMapping,
    RealPilotSimulationResult,
    map_real_cells,
    select_real_pilot_roi,
    write_mode_b_synthetic_inp,
)
from services.pilot.contract import (
    REQUIRED_HYDRAULIC_ATTRIBUTES,
    AttributeReadiness,
    HydraulicAvailability,
    HydraulicReadinessContract,
    build_real_drainage_contract,
    build_synthetic_fixture_contract,
)
from services.pilot.drainage import (
    AlignedDrainage,
    RealDrainageAdapter,
    drainage_mapping_stats,
)
from services.pilot.modes import (
    LABEL_REAL_TERRAIN_SYNTHETIC_HYDRAULICS,
    PilotCapabilityState,
    PilotModelMode,
    content_label_for_mode,
)
from services.pilot.provenance import (
    CRSSourceProvenance,
    RealPilotProvenance,
    gridspec_fingerprint,
)
from services.pilot.terrain import (
    RealTerrain,
    RealTerrainAdapter,
    authoritative_pilot_grid,
)

M11_VERSION = "m11-real-pilot-adapter-v1"

__all__ = [
    "DEFAULT_MODEB_DURATION_MIN",
    "DEFAULT_N_INLETS",
    "DEFAULT_ROI_OFFSET",
    "DEFAULT_ROI_WINDOW",
    "LABEL_REAL_TERRAIN_SYNTHETIC_HYDRAULICS",
    "M11_VERSION",
    "REQUIRED_HYDRAULIC_ATTRIBUTES",
    "AlignedDrainage",
    "AttributeReadiness",
    "CRSSourceProvenance",
    "HydraulicAvailability",
    "HydraulicReadinessContract",
    "M11SimulationAdapter",
    "PilotCapabilityState",
    "PilotModelMode",
    "PilotROI",
    "RealCellMapping",
    "RealDrainageAdapter",
    "RealPilotProvenance",
    "RealPilotSimulationResult",
    "RealTerrain",
    "RealTerrainAdapter",
    "authoritative_pilot_grid",
    "build_real_drainage_contract",
    "build_synthetic_fixture_contract",
    "content_label_for_mode",
    "drainage_mapping_stats",
    "gridspec_fingerprint",
    "map_real_cells",
    "select_real_pilot_roi",
    "write_mode_b_synthetic_inp",
]
