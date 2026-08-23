from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from services.nowcast.nowcast_record import NowcastRecord
from services.routing.impact import RoadImpact
from services.routing.router import RouteResult


def _field_hash(rate_mmh: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(rate_mmh).tobytes()).hexdigest()


@dataclass(frozen=True)
class ForecastRainfallFrame:
    """Typed M9 rainfall-frame contract derived from an M8 nowcast record."""

    initialization_time: datetime
    valid_time: datetime
    valid_from: datetime
    valid_to: datetime
    lead_minutes: int
    rate_mmh: np.ndarray
    units: str
    spatial_reference: str
    spatial_resolution_m: float
    width: int
    height: int
    source_type: str
    source_name: str
    source_provider_id: str
    nowcast_method: str
    nowcast_fingerprint: str
    observation_fingerprint: str
    status: str
    provenance_status: tuple[str, ...]
    fingerprint: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.initialization_time.tzinfo is None or self.valid_time.tzinfo is None:
            raise ValueError("initialization_time and valid_time must be timezone-aware")
        if self.valid_from.tzinfo is None or self.valid_to.tzinfo is None:
            raise ValueError("valid_from and valid_to must be timezone-aware")
        if self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be after valid_from")
        if self.valid_time != self.initialization_time + timedelta(minutes=self.lead_minutes):
            raise ValueError("valid_time must equal initialization_time + lead_minutes")
        if self.valid_from != self.valid_time:
            raise ValueError("valid_from must equal valid_time for the M9 frame contract")
        if self.units != "mm/h":
            raise ValueError("forecast rainfall frame units must be 'mm/h'")
        if self.rate_mmh.ndim != 2:
            raise ValueError("forecast rainfall frame must be 2-D")
        if self.rate_mmh.shape != (self.height, self.width):
            raise ValueError(
                f"forecast rainfall frame shape {self.rate_mmh.shape} != ({self.height}, {self.width})"
            )
        if np.any(self.rate_mmh < 0):
            raise ValueError("forecast rainfall frame contains negative rainfall")
        if not np.all(np.isfinite(self.rate_mmh)):
            raise ValueError("forecast rainfall frame contains non-finite rainfall")

    @classmethod
    def from_nowcast_record(
        cls,
        record: NowcastRecord,
        *,
        interval_minutes: int,
        provenance_status: tuple[str, ...],
    ) -> ForecastRainfallFrame:
        obs_fp = str(record.metadata.get("observation_fingerprint", ""))
        frame = cls(
            initialization_time=record.initialization_time,
            valid_time=record.valid_time,
            valid_from=record.valid_time,
            valid_to=record.valid_time + timedelta(minutes=interval_minutes),
            lead_minutes=record.lead_minutes,
            rate_mmh=record.rate_mmh.copy(),
            units=record.units,
            spatial_reference=record.spatial_reference,
            spatial_resolution_m=record.spatial_resolution_m,
            width=record.width,
            height=record.height,
            source_type=record.source_type,
            source_name=record.source_name,
            source_provider_id=record.source_provider_id,
            nowcast_method=record.method,
            nowcast_fingerprint=record.fingerprint or record.compute_fingerprint(),
            observation_fingerprint=obs_fp,
            status=record.status,
            provenance_status=provenance_status,
            metadata={
                **record.metadata,
                "interval_minutes": interval_minutes,
                "frame_role": "future_rainfall_field",
            },
        )
        object.__setattr__(frame, "fingerprint", frame.compute_fingerprint())
        return frame

    def compute_fingerprint(self) -> str:
        payload = {
            "initialization_time": self.initialization_time.isoformat(),
            "valid_time": self.valid_time.isoformat(),
            "valid_from": self.valid_from.isoformat(),
            "valid_to": self.valid_to.isoformat(),
            "lead_minutes": self.lead_minutes,
            "units": self.units,
            "spatial_reference": self.spatial_reference,
            "spatial_resolution_m": self.spatial_resolution_m,
            "width": self.width,
            "height": self.height,
            "source_type": self.source_type,
            "source_provider_id": self.source_provider_id,
            "nowcast_method": self.nowcast_method,
            "nowcast_fingerprint": self.nowcast_fingerprint,
            "observation_fingerprint": self.observation_fingerprint,
            "status": self.status,
            "field_hash": _field_hash(self.rate_mmh),
            "shape": list(self.rate_mmh.shape),
            "dtype": str(self.rate_mmh.dtype),
        }
        canon = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canon.encode("utf-8")).hexdigest()

    def to_dict(self, include_values: bool = False) -> dict[str, Any]:
        data = {
            "initialization_time": self.initialization_time.isoformat(),
            "valid_time": self.valid_time.isoformat(),
            "valid_from": self.valid_from.isoformat(),
            "valid_to": self.valid_to.isoformat(),
            "lead_minutes": self.lead_minutes,
            "units": self.units,
            "spatial_reference": self.spatial_reference,
            "spatial_resolution_m": self.spatial_resolution_m,
            "width": self.width,
            "height": self.height,
            "source_type": self.source_type,
            "source_name": self.source_name,
            "source_provider_id": self.source_provider_id,
            "nowcast_method": self.nowcast_method,
            "nowcast_fingerprint": self.nowcast_fingerprint,
            "observation_fingerprint": self.observation_fingerprint,
            "status": self.status,
            "provenance_status": list(self.provenance_status),
            "fingerprint": self.fingerprint or self.compute_fingerprint(),
            "rate_mean_mmh": round(float(np.mean(self.rate_mmh)), 4),
            "rate_max_mmh": round(float(np.max(self.rate_mmh)), 4),
            "rate_min_mmh": round(float(np.min(self.rate_mmh)), 4),
            "metadata": self.metadata,
        }
        if include_values:
            data["values"] = [round(float(v), 4) for v in self.rate_mmh.reshape(-1)]
        return data


@dataclass(frozen=True)
class FloodImpactProjection:
    """Flood-impact projection for one lead produced by the M4 engine."""

    config_id: str
    initialization_time: datetime
    valid_time: datetime
    lead_minutes: int
    rainfall_frame: ForecastRainfallFrame
    depth_m: np.ndarray
    flooded_area_m2: float
    flooded_cells: int
    extent_threshold_m: float
    total_surface_storage_m3: float
    drainage: dict[str, Any]
    model_version: str
    engine_version: str
    configuration_fingerprint: str
    observation_fingerprint: str
    nowcast_fingerprint: str
    projection_fingerprint: str
    status: str
    mass_balance: dict[str, Any]
    labels: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.depth_m.ndim != 2:
            raise ValueError("depth_m must be 2-D")
        if self.depth_m.shape != (self.rainfall_frame.height, self.rainfall_frame.width):
            raise ValueError("depth_m shape must match rainfall-frame grid")
        if np.any(self.depth_m < -1e-12) or not np.all(np.isfinite(self.depth_m)):
            raise ValueError("depth_m must be finite and non-negative within tolerance")

    def to_dict(self, include_depth_values: bool = False) -> dict[str, Any]:
        data = {
            "config_id": self.config_id,
            "initialization_time": self.initialization_time.isoformat(),
            "valid_time": self.valid_time.isoformat(),
            "lead_minutes": self.lead_minutes,
            "max_depth_m": round(float(np.max(self.depth_m)), 6),
            "mean_depth_m": round(float(np.mean(self.depth_m)), 6),
            "flooded_area_m2": round(self.flooded_area_m2, 4),
            "flooded_cells": self.flooded_cells,
            "extent_threshold_m": self.extent_threshold_m,
            "total_surface_storage_m3": round(self.total_surface_storage_m3, 4),
            "drainage": self.drainage,
            "model_version": self.model_version,
            "engine_version": self.engine_version,
            "configuration_fingerprint": self.configuration_fingerprint,
            "observation_fingerprint": self.observation_fingerprint,
            "nowcast_fingerprint": self.nowcast_fingerprint,
            "rainfall_frame_fingerprint": self.rainfall_frame.fingerprint,
            "projection_fingerprint": self.projection_fingerprint,
            "status": self.status,
            "mass_balance": self.mass_balance,
            "labels": list(self.labels),
            "rainfall_frame": self.rainfall_frame.to_dict(include_values=False),
        }
        if include_depth_values:
            data["depth_values_m"] = [round(float(v), 6) for v in self.depth_m.reshape(-1)]
        return data


@dataclass(frozen=True)
class RoadImpactProjection:
    config_id: str
    initialization_time: datetime
    valid_time: datetime
    lead_minutes: int
    road_impacts: tuple[RoadImpact, ...]
    road_metrics: dict[str, Any]
    projection_fingerprint: str
    policy_version: str
    policy_fingerprint: str
    network_fingerprint: str
    road_projection_fingerprint: str
    labels: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_id": self.config_id,
            "initialization_time": self.initialization_time.isoformat(),
            "valid_time": self.valid_time.isoformat(),
            "lead_minutes": self.lead_minutes,
            "road_impacts": [impact.to_dict() for impact in self.road_impacts],
            "road_metrics": self.road_metrics,
            "projection_fingerprint": self.projection_fingerprint,
            "policy_version": self.policy_version,
            "policy_fingerprint": self.policy_fingerprint,
            "network_fingerprint": self.network_fingerprint,
            "road_projection_fingerprint": self.road_projection_fingerprint,
            "labels": list(self.labels),
        }


@dataclass(frozen=True)
class RouteProjection:
    config_id: str
    lead_minutes: int
    valid_time: datetime
    routing: RouteResult
    projection_fingerprint: str
    route_projection_fingerprint: str
    labels: tuple[str, ...]
    timings_ms: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_id": self.config_id,
            "lead_minutes": self.lead_minutes,
            "valid_time": self.valid_time.isoformat(),
            "routing": self.routing.to_dict(),
            "projection_fingerprint": self.projection_fingerprint,
            "route_projection_fingerprint": self.route_projection_fingerprint,
            "labels": list(self.labels),
            "timings_ms": self.timings_ms,
        }
