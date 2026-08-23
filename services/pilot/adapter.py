"""M11 — Real-pilot simulation adapter (Sections 4, 5, 6, 7, 15).

This adapter integrates the real Bagjola/Kolkata pilot into the EXISTING UFNS
coupled flood model through explicit contracts. It does not rewrite the M2/M4
mathematics; it composes the validated components:

        existing engine (CoupledFloodModel)
                ↑
        M11 adapter (this module)
                ↑
        real pilot data (normalized DEM + mapped drainage)

MODE B execution detail (REAL_TERRAIN / SYNTHETIC_HYDRAULICS):
  Real terrain enters the solver from the real DEM. Because the real DEM
  carries scattered nodata cells that must NEVER be silently filled, the
  executable surface model runs on a real-pilot REGION OF INTEREST (ROI): a
  rectangular window of the normalized real elevation that contains ONLY
  valid (non-nodata) cells. This is 100% real elevation data (no filling, no
  fabrication) and is a genuine sub-rectangle of the authoritative pilot
  grid — it does NOT move the pilot grid and does NOT restore the synthetic
  grid. The ROI keeps the full-pilot normalization authoritative (M11-01).

  The hydraulic network is the existing SYNTHETIC/ASSUMED SWMM fixture
  (services/hydraulics/fixture.py), datum-anchored to the real ROI basin for
  sensible coupling. Hydraulic PARAMETERS (diameter, Manning, etc.) remain
  synthetic and explicitly labelled — only the vertical datum anchor is a
  documented alignment, never a fabricated parameter.

Mass conservation (Section 15): the existing mass ledger is retained verbatim.
The MODE-B result reports the same <=1% relative residual gate, film
initialization, exchange cancellation, and SWMM identity-based storage
accounting as the M4 engine.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from services.contracts import GridSpec, MassBalance
from services.hydraulics.fixture import ST1_INVERT, exact_fixture_inp
from services.ingestion.dem_real import pilot_grid_spec
from services.ingestion.provenance import sha256_bytes, sha256_file
from services.pilot.contract import HydraulicReadinessContract
from services.pilot.modes import (
    LABEL_REAL_TERRAIN_SYNTHETIC_HYDRAULICS,
    PilotCapabilityState,
    PilotModelMode,
    content_label_for_mode,
)
from services.pilot.provenance import RealPilotProvenance, gridspec_fingerprint
from services.pilot.terrain import RealTerrain
from services.scenarios.profiles import D016_HUMAN_REVIEW, D016_STATUS
from services.simulation.engine import (
    MODEL_VERSION as ENGINE_MODEL_VERSION,
)
from services.simulation.engine import (
    CoupledFloodModel,
    M4RunResult,
    RainfallSpec,
    RunConfig,
)

M11_VERSION = "m11-real-pilot-adapter-v1"
DEFAULT_ROI_WINDOW = 134          # cells per side (matches synthetic scale)
DEFAULT_ROI_OFFSET = (50, 50)     # deterministic scan start in pilot grid
DEFAULT_N_INLETS = 12
DEFAULT_MODEB_DURATION_MIN = 15
MODEB_INP_PATH = Path("data/demo/m11/mode_b_drainage_synthetic.inp")


# ---------------------------------------------------------------------------#
# ROI + deterministic cell mapping on REAL terrain
# ---------------------------------------------------------------------------#

@dataclass(frozen=True)
class PilotROI:
    """A real-pilot region of interest (sub-rectangle of the pilot grid).

    Contains only valid (non-nodata) real elevations. Its GridSpec is derived
    from the authoritative pilot grid (same CRS, cell size, alignment).
    """

    elevation: np.ndarray
    grid: GridSpec
    pilot_grid: GridSpec
    row0: int
    col0: int
    raw_dem_sha256: str

    @property
    def origin_xy(self) -> tuple[float, float]:
        """Top-left projected corner (x, y) of the ROI affine."""
        px = self.pilot_grid.affine_transform[2]
        py = self.pilot_grid.affine_transform[5]
        ox = px + self.col0 * self.pilot_grid.cell_size_m
        oy = py - self.row0 * self.pilot_grid.cell_size_m
        return (ox, oy)

    def to_dict(self) -> dict[str, Any]:
        return {
            "grid": self.grid.model_dump(mode="json"),
            "pilot_grid_id": self.pilot_grid.grid_id,
            "row0": self.row0,
            "col0": self.col0,
            "window_cells": list(self.elevation.shape),
            "origin_xy": list(self.origin_xy),
            "raw_dem_sha256": self.raw_dem_sha256,
            "labels": ["REAL_DATA", "REAL_TERRAIN", "PROVISIONAL"],
        }


def select_real_pilot_roi(
    terrain: RealTerrain,
    window: int = DEFAULT_ROI_WINDOW,
    offset: tuple[int, int] = DEFAULT_ROI_OFFSET,
) -> PilotROI:
    """Deterministically select a zero-nodata real-pilot ROI window.

    Scans the normalized real elevation from ``offset`` for the first
    ``window`` x ``window`` block with no nodata cells. Raises if none is
    found within the grid. Never fills nodata.
    """
    elev = terrain.elevation
    h, w = elev.shape
    if window > h or window > w:
        raise ValueError(f"ROI window {window} larger than terrain {elev.shape}")
    nodata = terrain.nodata
    start_r, start_c = offset
    # Deterministic raster scan for the first fully-valid window.
    for r0 in range(start_r, h - window + 1):
        for c0 in range(start_c, w - window + 1):
            block = elev[r0:r0 + window, c0:c0 + window]
            if not np.any(block == nodata) and np.all(np.isfinite(block)):
                return _build_roi(terrain, r0, c0, window)
        start_c = 0  # subsequent rows scan from column 0
    raise RuntimeError(
        f"no zero-nodata {window}x{window} real-pilot ROI found; "
        "refusing to fill nodata to force a window"
    )


def _build_roi(terrain: RealTerrain, row0: int, col0: int, window: int) -> PilotROI:
    elev = terrain.elevation[row0:row0 + window, col0:col0 + window].copy()
    pilot = terrain.grid
    ox, oy = (
        pilot.affine_transform[2] + col0 * pilot.cell_size_m,
        pilot.affine_transform[5] - row0 * pilot.cell_size_m,
    )
    roi_grid = GridSpec(
        grid_id=f"{pilot.grid_id}_roi_{row0}_{col0}_{window}",
        crs_wkt_or_epsg=pilot.crs_wkt_or_epsg,
        width=window,
        height=window,
        affine_transform=[pilot.cell_size_m, 0.0, ox, 0.0, -pilot.cell_size_m, oy],
        cell_size_m=pilot.cell_size_m,
        nodata=None,
        bounds=[
            ox,
            oy - window * pilot.cell_size_m,
            ox + window * pilot.cell_size_m,
            oy,
        ],
    )
    return PilotROI(
        elevation=elev.astype(np.float64),
        grid=roi_grid,
        pilot_grid=pilot,
        row0=row0,
        col0=col0,
        raw_dem_sha256=terrain.raw_dem_sha256,
    )


@dataclass(frozen=True)
class RealCellMapping:
    """Deterministic inlet/vent cell mapping on real terrain."""

    basin_cell: tuple[int, int]
    basin_elevation_m: float
    inlet_cells: tuple[tuple[int, int], ...]
    vent_cell: tuple[int, int]
    datum_offset_m: float
    basis: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "basin_cell": list(self.basin_cell),
            "basin_elevation_m": round(self.basin_elevation_m, 4),
            "inlet_cells": [list(c) for c in self.inlet_cells],
            "vent_cell": list(self.vent_cell),
            "datum_offset_m": round(self.datum_offset_m, 4),
            "basis": self.basis,
            "labels": ["REAL_TERRAIN_MAPPING", "PROVISIONAL"],
        }


def map_real_cells(
    roi: PilotROI,
    n_inlets: int = DEFAULT_N_INLETS,
) -> RealCellMapping:
    """Map inlet + vent cells deterministically onto the REAL ROI terrain.

    The basin is the lowest INTERIOR cell. Inlets are the nearest
    (Chebyshev-then-elevation ranked) interior cells above the basin floor;
    the vent is a nearby slightly-raised cell. The datum offset anchors the
    synthetic SWMM fixture to the real basin floor for sensible coupling
    (documented alignment — NOT a fabricated hydraulic parameter).

    Adaptive: the elevation band and distance ring widen until at least two
    inlet shoulder cells are found, so the mapping is robust to the local
    topography of any valid real ROI window while remaining deterministic.
    """
    dem = roi.elevation
    h, w = dem.shape
    interior = dem[1:h - 1, 1:w - 1]
    flat = interior.argmin()
    by_rel, bx_rel = np.unravel_index(flat, interior.shape)
    by, bx = int(by_rel) + 1, int(bx_rel) + 1
    floor = float(dem[by, bx])

    inlet_cells: list[tuple[int, int]] = []
    band_lo, band_hi = 0.2, 1.0
    d_min, d_max = 3, 10
    for _attempt in range(6):
        cands: list[tuple[int, float, float, int, int]] = []
        for r in range(max(1, by - d_max), min(h - 1, by + d_max + 1)):
            for c in range(max(1, bx - d_max), min(w - 1, bx + d_max + 1)):
                if (r, c) == (by, bx):
                    continue
                d = max(abs(r - by), abs(c - bx))
                rel = float(dem[r, c]) - floor
                if d_min <= d <= d_max and band_lo <= rel <= band_hi:
                    cands.append((d, rel, float(dem[r, c]), r, c))
        # rank by distance then elevation; deterministic
        cands.sort(key=lambda t: (t[0], round(t[2], 4)))
        inlet_cells = [(r, c) for (_, _, _, r, c) in cands[:n_inlets]]
        if len(inlet_cells) >= 2:
            break
        # widen the search deterministically
        band_hi += 0.75
        d_max += 4
    if len(inlet_cells) < 2:
        raise RuntimeError(
            "insuitable real basin: not enough inlet shoulder cells "
            "(no fabrication of exchange sites)"
        )

    # Vent: nearest ring cell with elevation in [floor+0.3, floor+0.9]; the
    # raised return location. Falls back to a deterministic offset cell.
    inlet_set = set(inlet_cells)
    vent: tuple[int, int] | None = None
    for d in range(2, d_max + 1):
        ring: list[tuple[float, int, int]] = []
        for r in range(max(1, by - d), min(h - 1, by + d + 1)):
            for c in range(max(1, bx - d), min(w - 1, bx + d + 1)):
                if max(abs(r - by), abs(c - bx)) != d or (r, c) in inlet_set:
                    continue
                if 0.3 <= dem[r, c] - floor <= 0.9:
                    ring.append((round(float(dem[r, c]), 4), r, c))
        if ring:
            ring.sort()
            _, vr, vc = ring[0]
            vent = (vr, vc)
            break
    if vent is None or vent in inlet_set:
        vent = (by, min(bx + 3, w - 2))
        if vent in inlet_set or vent == (by, bx):
            vent = (min(by + 3, h - 2), bx)

    datum_offset = floor - ST1_INVERT  # anchor synthetic fixture to real basin datum
    return RealCellMapping(
        basin_cell=(by, bx),
        basin_elevation_m=floor,
        inlet_cells=tuple(inlet_cells),
        vent_cell=vent,
        datum_offset_m=datum_offset,
        basis=(
            "Deterministic mapping on REAL ROI terrain: lowest interior cell = "
            "basin; inlets = nearest ranked basin-shoulder cells above the "
            "floor; vent = nearby raised cell. Datum offset anchors the "
            "SYNTHETIC SWMM fixture to the real basin floor (documented "
            "alignment, not a fabricated hydraulic parameter)."
        ),
    )


# ---------------------------------------------------------------------------#
# MODE B synthetic INP (labelled)
# ---------------------------------------------------------------------------#

def write_mode_b_synthetic_inp(
    cell_map: RealCellMapping,
    dest: Path = MODEB_INP_PATH,
) -> Path:
    """Write the explicitly-labelled SYNTHETIC hydraulic fixture for MODE B.

    Reuses services.hydraulics.fixture.exact_fixture_inp (no M4 rewrite). The
    datum_offset anchors the fixture to the real basin. Hydraulic parameters
    (diameter, Manning, etc.) are unchanged and synthetic.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    inp = exact_fixture_inp(blocked=False, datum_offset_m=cell_map.datum_offset_m)
    dest.write_text(inp)
    return dest


# ---------------------------------------------------------------------------#
# Results
# ---------------------------------------------------------------------------#

@dataclass(frozen=True)
class RealPilotSimulationResult:
    """Result of an M11 real-pilot simulation (MODE B)."""

    model_mode: PilotModelMode
    content_label: str
    roi: PilotROI
    cell_map: RealCellMapping
    m4_result: M4RunResult
    mass_balance: MassBalance
    hydraulic_contract: HydraulicReadinessContract
    provenance: RealPilotProvenance
    rainfall_status: dict[str, Any]
    limitations: tuple[str, ...] = ()
    sim_summary: dict[str, Any] = field(default_factory=dict)

    @property
    def capability_state(self) -> PilotCapabilityState:
        return PilotCapabilityState(
            real_terrain_available=True,
            real_geometry_available=False,
            hydraulic_parameters_present=False,
            hydraulic_network_ready=False,
            reason=(
                "Real terrain available; real drainage geometry MISSING or UNUSED "
                "(synthetic fixture used). HYDRAULIC_NETWORK_READY=False."
            ),
        )

    @property
    def mass_ledger(self) -> dict[str, Any]:
        led = self.m4_result.ledger
        return {
            "rainfall_input_m3": led.rain_m3,
            "external_inflow_m3": led.ext_in_m3,
            "infiltration_loss_m3": led.losses_m3,
            "microstore_final_m3": led.microstore_final_m3,
            "surface_boundary_outflow_m3": led.surf_out_m3,
            "drainage_outfall_m3": led.outfall_m3,
            "S2D_m3": led.S2D_m3,
            "D2S_m3": led.D2S_m3,
            "swmm_flood_export_m3": led.flood_export_m3,
            "combined_residual_m3": led.residual_total,
            "relative_residual": led.relative_total(),
            "swmm_flow_routing_error_pct": led.flow_routing_error_pct,
            "status": led.status(),
        }

    def to_dict(self) -> dict[str, Any]:
        mb = self.mass_balance
        led = self.m4_result.ledger
        return {
            "model_mode": self.model_mode.value,
            "content_label": self.content_label,
            "capability_state": self.capability_state.to_dict(),
            "roi": self.roi.to_dict(),
            "cell_map": self.cell_map.to_dict(),
            "run_id": self.m4_result.simulation_run.run_id,
            "scenario_id": self.m4_result.simulation_run.scenario_id,
            "config_fingerprint": self.m4_result.simulation_run.configuration_fingerprint,
            "engine_version": self.m4_result.simulation_run.model_versions.get("engine", ""),
            "adapter_version": M11_VERSION,
            "mass_balance": mb.model_dump(mode="json"),
            "mass_ledger": {
                "rainfall_input_m3": led.rain_m3,
                "external_inflow_m3": led.ext_in_m3,
                "infiltration_loss_m3": led.losses_m3,
                "microstore_final_m3": led.microstore_final_m3,
                "surface_boundary_outflow_m3": led.surf_out_m3,
                "drainage_outfall_m3": led.outfall_m3,
                "S2D_m3": led.S2D_m3,
                "D2S_m3": led.D2S_m3,
                "swmm_flood_export_m3": led.flood_export_m3,
                "combined_residual_m3": led.residual_total,
                "relative_residual": led.relative_total(),
                "swmm_flow_routing_error_pct": led.flow_routing_error_pct,
                "status": led.status(),
            },
            "hydraulic_contract": self.hydraulic_contract.to_dict(),
            "provenance": self.provenance.to_dict(),
            "rainfall_status": self.rainfall_status,
            "sim_summary": self.sim_summary,
            "limitations": list(self.limitations),
            "labels": [
                "REAL_TERRAIN",
                "SYNTHETIC_HYDRAULICS",
                self.content_label,
                "PROVISIONAL",
                "NOT_REAL_TIME",
                "NOT_VALIDATED_FORECAST",
            ],
        }


# ---------------------------------------------------------------------------#
# Adapter
# ---------------------------------------------------------------------------#

class M11SimulationAdapter:
    """Compose real terrain + (synthetic hydraulics for MODE B) → engine."""

    def __init__(self, terrain: RealTerrain) -> None:
        self.terrain = terrain

    # -- MODE A: real terrain + real drainage geometry (NO simulation) -------
    def mode_a_capability(
        self,
        aligned_drainage=None,
        hydraulic_contract: HydraulicReadinessContract | None = None,
    ) -> dict[str, Any]:
        """MODE A report: real terrain + real drainage geometry, no hydraulic sim.

        No simulation is claimed because hydraulic parameters are absent.
        """
        contract = hydraulic_contract or _default_mode_a_contract()
        cap = PilotCapabilityState(
            real_terrain_available=True,
            real_geometry_available=aligned_drainage is not None,
            hydraulic_parameters_present=False,
            hydraulic_network_ready=False,
            reason=(
                "MODE A: real DEM + real drainage geometry available; hydraulic "
                "parameters MISSING. No hydraulic drainage simulation claimed."
            ),
        )
        return {
            "model_mode": PilotModelMode.MODE_A_REAL_TERRAIN_REAL_DRAINAGE.value,
            "content_label": content_label_for_mode(
                PilotModelMode.MODE_A_REAL_TERRAIN_REAL_DRAINAGE
            ),
            "capability_state": cap.to_dict(),
            "terrain": self.terrain.to_dict(),
            "drainage": aligned_drainage.to_dict() if aligned_drainage else None,
            "hydraulic_contract": contract.to_dict(),
            "simulation_executed": False,
            "labels": ["REAL_TERRAIN", "REAL_DRAINAGE_GEOMETRY", "MISSING_HYDRAULICS"],
        }

    # -- MODE B: real terrain + synthetic hydraulic fixture (executable) -----
    def mode_b_real_terrain_synthetic_hydraulics(
        self,
        *,
        issue_time: datetime | None = None,
        duration_minutes: int = DEFAULT_MODEB_DURATION_MIN,
        rainfall_mmh: float = 10.0,
        window: int = DEFAULT_ROI_WINDOW,
        offset: tuple[int, int] = DEFAULT_ROI_OFFSET,
        n_inlets: int = DEFAULT_N_INLETS,
        inp_path: Path = MODEB_INP_PATH,
        synthetic_contract: HydraulicReadinessContract | None = None,
        rainfall_profile_fingerprint: str = "",
    ) -> RealPilotSimulationResult:
        """Run real terrain through the existing coupled engine with a labelled
        synthetic hydraulic fixture (MODE B)."""
        issue_time = issue_time or datetime(2026, 8, 23, tzinfo=timezone.utc)
        roi = select_real_pilot_roi(self.terrain, window=window, offset=offset)
        cell_map = map_real_cells(roi, n_inlets=n_inlets)
        inp = write_mode_b_synthetic_inp(cell_map, dest=inp_path)

        # Build a deterministic governed rainfall fingerprint (PROVISIONAL).
        rain_fp = rainfall_profile_fingerprint or _rainfall_fingerprint(
            rainfall_mmh, duration_minutes
        )

        cfg = RunConfig(
            run_id=f"m11_modeB_{issue_time:%Y%m%dT%H%M%SZ}",
            scenario_id="M11_MODE_B",
            issue_time=issue_time,
            dem=roi.elevation,
            cell_size_m=roi.grid.cell_size_m,
            crs=roi.grid.crs_wkt_or_epsg,
            vertical_reference=self.terrain.vertical_reference,
            rainfall=RainfallSpec(
                kind="uniform",
                interval_minutes=duration_minutes,
                intensities_mmh=[rainfall_mmh],
                pattern="uniform",
                seed=20260823,
            ),
            losses=__import__(
                "services.simulation.engine", fromlist=["LossSpec"]
            ).LossSpec(),
            mannings_n=0.03,
            alpha=0.5,
            theta=0.8,
            h_init=1e-6,
            closed_boundaries=True,
            drainage_inp=inp,
            inlet_cells=list(cell_map.inlet_cells),
            vent_cell=cell_map.vent_cell,
            dt_c=5,
            surface_substeps=5,
            duration_minutes=duration_minutes,
            snapshot_interval_minutes=_pick_snapshot_interval(duration_minutes),
            extent_threshold_m=0.05,
            cd=0.6,
            ao_per_inlet=0.002,
            grid_origin_xy=roi.origin_xy,
        )
        model = CoupledFloodModel(cfg)
        m4 = model.run()

        contract = synthetic_contract or _default_mode_b_contract()
        prov = _build_provenance(
            terrain=self.terrain,
            mode=PilotModelMode.MODE_B_REAL_TERRAIN_SYNTHETIC_HYDRAULICS,
            config_fingerprint=cfg.fingerprint(),
            gridspec=roi.grid,
            rainfall_fingerprint=rain_fp,
        )
        limitations = (
            (
                "MODE B uses REAL terrain (real ROI elevations from the real DEM) "
                "with an explicitly-labelled SYNTHETIC hydraulic fixture."
            ),
            (
                "Hydraulic parameters (diameter, invert, Manning, capacity) are "
                "SYNTHETIC/ASSUMED — they are NOT real and NOT validated against "
                "the pilot drainage network."
            ),
            (
                "Vertical datum of the real DEM is UNVERIFIED; the synthetic "
                "fixture datum is anchored to the real ROI basin for coupling only."
            ),
            (
                f"Rainfall is PROVISIONAL (D-016 {D016_STATUS}, human review "
                f"{D016_HUMAN_REVIEW}); NOT real-time, NOT a validated forecast."
            ),
            (
                "ROI is a zero-nodata sub-rectangle of the authoritative pilot "
                "grid; full-pilot normalization remains authoritative (M11-01)."
            ),
        )
        sim_summary = {
            "peak_depth_m": m4.peak_depth_m,
            "max_flooded_area_m2": m4.max_flooded_area_m2,
            "time_to_peak_min": m4.time_to_peak_min,
            "max_st1_head_m": m4.max_st1_head_m,
            "n_coupling_steps": m4.n_coupling_steps,
            "wall_seconds": m4.wall_seconds,
        }
        return RealPilotSimulationResult(
            model_mode=PilotModelMode.MODE_B_REAL_TERRAIN_SYNTHETIC_HYDRAULICS,
            content_label=LABEL_REAL_TERRAIN_SYNTHETIC_HYDRAULICS,
            roi=roi,
            cell_map=cell_map,
            m4_result=m4,
            mass_balance=m4.mass_balance,
            hydraulic_contract=contract,
            provenance=prov,
            rainfall_status={
                "d016_status": D016_STATUS,
                "d016_human_review": D016_HUMAN_REVIEW,
                "profile_status": "PROVISIONAL",
                "rainfall_fingerprint": rain_fp,
                "real_time": False,
                "validated_forecast": False,
            },
            limitations=limitations,
            sim_summary=sim_summary,
        )


# ---------------------------------------------------------------------------#
# helpers
# ---------------------------------------------------------------------------#

def _default_mode_a_contract() -> HydraulicReadinessContract:
    from services.pilot.contract import build_real_drainage_contract

    return build_real_drainage_contract("WB_AMRUT_Stormwater_drains")


def _pick_snapshot_interval(duration_minutes: int) -> int:
    """Pick a snapshot interval that divides the duration (engine contract).

    Prefers 5 min when it divides the duration; otherwise the duration itself
    (a single final snapshot). snapshot*60 % dt_c(=5) is always satisfied.
    """
    if duration_minutes >= 5 and duration_minutes % 5 == 0:
        return 5
    if duration_minutes >= 3 and duration_minutes % 3 == 0:
        return 3
    return duration_minutes


def _default_mode_b_contract() -> HydraulicReadinessContract:
    from services.pilot.contract import build_synthetic_fixture_contract

    return build_synthetic_fixture_contract("M4_synthetic_exact_exchange_fixture")


def _rainfall_fingerprint(rainfall_mmh: float, duration_minutes: int) -> str:
    payload = json.dumps(
        {
            "profile": "uniform_synthetic_provisional",
            "rainfall_mmh": rainfall_mmh,
            "duration_minutes": duration_minutes,
            "d016_status": D016_STATUS,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _build_provenance(
    *,
    terrain: RealTerrain,
    mode: PilotModelMode,
    config_fingerprint: str,
    gridspec: GridSpec,
    rainfall_fingerprint: str,
) -> RealPilotProvenance:
    grid_fp = gridspec_fingerprint(gridspec.model_dump(mode="json"))
    pilot_fp = gridspec_fingerprint(pilot_grid_spec().model_dump(mode="json"))
    return RealPilotProvenance(
        raw_dem_sha256=terrain.raw_dem_sha256,
        raw_dem_path=str(terrain.raw_dem_path),
        crs_source=terrain.crs_source,
        normalized_dem_fingerprint=terrain.processing_fingerprint,
        gridspec_fingerprint=grid_fp,
        rainfall_fingerprint=rainfall_fingerprint,
        model_config_fingerprint=config_fingerprint,
        scenario_fingerprint=pilot_fp,
        model_mode=mode.value,
        software_version=f"{M11_VERSION}+{ENGINE_MODEL_VERSION}",
        status_labels=(
            "REAL_TERRAIN",
            "SYNTHETIC_HYDRAULICS",
            "PROVISIONAL",
            "NOT_REAL_TIME",
            "NOT_VALIDATED_FORECAST",
        ),
        extra={"pilot_gridspec_fingerprint": pilot_fp},
    )


def dem_array_fingerprint(dem: np.ndarray) -> str:
    """Deterministic SHA-256 of a DEM array (matches engine dem_sha256 basis)."""
    return sha256_bytes(np.ascontiguousarray(dem, dtype=np.float64).tobytes())


def inp_fingerprint(path: Path) -> str:
    return sha256_file(path)
