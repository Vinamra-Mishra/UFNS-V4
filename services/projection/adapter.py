from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import numpy as np

from services.nowcast.nowcast_record import NowcastRecord
from services.projection import (
    RAINFALL_INTERVAL_MINUTES,
    VALID_LEADS,
)
from services.projection.configs import ProjectionConfigRecord
from services.projection.contracts import ForecastRainfallFrame
from services.simulation.engine import (
    FIXTURE_VENT_CELL,
    LossSpec,
    RainfallSpec,
    RunConfig,
    fixture_inlet_cells,
)


class ProjectionAdapterError(ValueError):
    """Raised when M8 nowcast data cannot be safely adapted into the M4 engine."""


def nowcast_records_to_frames(
    records: Iterable[NowcastRecord],
    *,
    interval_minutes: int = RAINFALL_INTERVAL_MINUTES,
) -> list[ForecastRainfallFrame]:
    """Convert M8 nowcast records into explicit M9 rainfall frames.

    The persistence baseline preserves the rainfall field exactly:

        frame.rate_mmh == nowcast.rate_mmh

    No resampling, no unit conversion, and no advection are introduced here.
    """
    out: list[ForecastRainfallFrame] = []
    for record in records:
        if record.units != "mm/h":
            raise ProjectionAdapterError(f"unsupported nowcast units: {record.units!r}")
        if record.lead_minutes not in VALID_LEADS:
            raise ProjectionAdapterError(f"unsupported lead {record.lead_minutes}")
        frame = ForecastRainfallFrame.from_nowcast_record(
            record,
            interval_minutes=interval_minutes,
            provenance_status=(
                "PERSISTENCE_PROJECTION",
                "NOT_REAL_TIME",
                "NOT_VALIDATED_FORECAST",
            ),
        )
        out.append(frame)
    out.sort(key=lambda frame: frame.lead_minutes)
    leads = tuple(frame.lead_minutes for frame in out)
    if leads != VALID_LEADS:
        raise ProjectionAdapterError(
            f"nowcast leads {list(leads)} do not match required {list(VALID_LEADS)}"
        )
    first = out[0]
    for frame in out[1:]:
        if frame.width != first.width or frame.height != first.height:
            raise ProjectionAdapterError("nowcast rainfall frames do not share one grid shape")
        if frame.spatial_reference != first.spatial_reference:
            raise ProjectionAdapterError("nowcast rainfall frames do not share one spatial reference")
        if abs(frame.spatial_resolution_m - first.spatial_resolution_m) > 1e-9:
            raise ProjectionAdapterError("nowcast rainfall frames do not share one spatial resolution")
    return out


def forcing_fields_from_frames(
    frames: Iterable[ForecastRainfallFrame],
    *,
    max_lead_minutes: int,
) -> list[np.ndarray]:
    """Return interval-forcing fields for the projection run.

    The M4 engine advances over rainfall intervals. For a 0–60 minute
    projection with 15-minute rainfall frames we need the interval-start frames
    at leads 0, 15, 30, and 45 to drive the intervals [0,15), [15,30),
    [30,45), and [45,60). The lead-60 frame is still preserved for provenance
    and API presentation, but it does not start an additional interval inside
    the 0–60 minute run.
    """
    selected = [frame.rate_mmh.copy() for frame in frames if frame.lead_minutes < max_lead_minutes]
    expected = max_lead_minutes // RAINFALL_INTERVAL_MINUTES
    if len(selected) != expected:
        raise ProjectionAdapterError(
            f"projection duration {max_lead_minutes} minutes needs {expected} forcing fields, "
            f"got {len(selected)}"
        )
    return selected


def build_runconfig_from_frames(
    config: ProjectionConfigRecord,
    frames: list[ForecastRainfallFrame],
    dem: np.ndarray,
    *,
    artifact_dir: Path | None = None,
) -> RunConfig:
    """Build an additive M4 RunConfig using explicit rainfall fields.

    This preserves the authoritative M4 physics while extending only the input
    adapter layer: rainfall is supplied as explicit 2-D mm/h fields rather than
    regenerated from a synthetic profile.
    """
    if not frames:
        raise ProjectionAdapterError("no rainfall frames available")
    first = frames[0]
    if dem.shape != (first.height, first.width):
        raise ProjectionAdapterError(
            f"rainfall grid {first.height}x{first.width} incompatible with DEM {dem.shape}"
        )
    if first.units != "mm/h":
        raise ProjectionAdapterError(f"unsupported rainfall units: {first.units!r}")

    forcing_fields = forcing_fields_from_frames(frames, max_lead_minutes=config.duration_minutes)
    rainfall = RainfallSpec(
        kind="explicit_fields",
        interval_minutes=config.rainfall_interval_minutes,
        intensities_mmh=[],
        pattern="explicit_fields",
        seed=config.seed,
        explicit_fields_mmh=forcing_fields,
    )
    losses = LossSpec(
        enabled=True,
        f0_mmh=config.horton_f0_mmh,
        fmin_mmh=config.horton_fmin_mmh,
        k_s1=config.horton_k_s1,
        microstore_m=config.microstore_m,
    )
    return RunConfig(
        run_id=f"m9_{config.config_id}_{first.initialization_time:%Y%m%dT%H%M%SZ}",
        scenario_id=config.config_id,
        issue_time=first.initialization_time,
        dem=dem,
        crs=first.spatial_reference,
        rainfall=rainfall,
        losses=losses,
        mannings_n=config.manning_n,
        alpha=0.5,
        theta=0.8,
        h_init=1e-6,
        closed_boundaries=False,
        drainage_inp=config.drainage_condition.inp_path,
        inlet_cells=fixture_inlet_cells(dem),
        vent_cell=FIXTURE_VENT_CELL,
        dt_c=config.coupling_timestep_s,
        surface_substeps=5,
        duration_minutes=config.duration_minutes,
        snapshot_interval_minutes=config.snapshot_interval_minutes,
        extent_threshold_m=config.extent_threshold_m,
        cd=config.cd,
        ao_per_inlet=config.ao_per_inlet,
        ao_vent=None,
        external_inflow_m3s=0.0,
        artifact_dir=artifact_dir,
    )
