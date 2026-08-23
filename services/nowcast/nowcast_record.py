"""M8 — Typed nowcast contract (NowcastRecord).

A NowcastRecord represents one forecast rainfall field at a specific lead time.
It carries full provenance: initialization time, valid time, lead minutes,
spatial reference, source, method, status, fingerprint.

The contract is intentionally separate from the existing RainfallGrid contract
(services/contracts.py) to avoid overloading it. NowcastRecord is specific to
the M8 nowcast pipeline.

Status vocabulary for nowcast records:
  SIMULATED   — generated from a deterministic model (e.g., persistence)
  PROVISIONAL — method not yet scientifically approved
  REAL        — from verified operational data + approved method
  SYNTHETIC   — from a synthetic provider (NOT real data)
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import numpy as np


@dataclass(frozen=True)
class NowcastRecord:
    """One nowcast rainfall field at a specific lead time.

    Attributes:
        initialization_time: When the forecast was initialized (UTC).
        valid_time: The time this forecast is valid for (UTC).
        lead_minutes: Forecast lead time in minutes (valid_time - initialization_time).
        rate_mmh: 2-D array of forecast rainfall rates (mm/h).
        units: Always "mm/h".
        spatial_reference: CRS (e.g., "EPSG:32645").
        spatial_resolution_m: Cell size in metres.
        width: Grid width (cells).
        height: Grid height (cells).
        source_type: REAL / SYNTHETIC / FIXTURE.
        source_name: Human-readable source.
        source_provider_id: Machine-readable provider ID.
        method: Nowcast method identifier (e.g., "NOWCAST-PERSISTENCE-V1").
        status: Nowcast status (SIMULATED, PROVISIONAL, REAL, etc.).
        uncertainty: Uncertainty description ("NOT PROVIDED" for deterministic).
        quality_flags: List of quality flag strings.
        fingerprint: Deterministic hash of the forecast parameters.
        metadata: Additional provenance metadata.
    """
    initialization_time: datetime
    valid_time: datetime
    lead_minutes: int
    rate_mmh: np.ndarray
    units: str = "mm/h"
    spatial_reference: str = "EPSG:32645"
    spatial_resolution_m: float = 30.0
    width: int = 134
    height: int = 134
    source_type: str = "SYNTHETIC"
    source_name: str = ""
    source_provider_id: str = ""
    method: str = "NOWCAST-PERSISTENCE-V1"
    status: str = "SIMULATED"
    uncertainty: str = "NOT PROVIDED"
    quality_flags: tuple[str, ...] = ()
    fingerprint: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.initialization_time.tzinfo is None:
            raise ValueError("initialization_time must be timezone-aware")
        if self.valid_time.tzinfo is None:
            raise ValueError("valid_time must be timezone-aware")
        if self.lead_minutes < 0:
            raise ValueError("lead_minutes must be non-negative")
        # Lead-time invariant: valid_time == initialization_time + lead_minutes.
        expected_valid_time = self.initialization_time + timedelta(minutes=self.lead_minutes)
        if self.valid_time != expected_valid_time:
            raise ValueError(
                "valid_time must equal initialization_time + timedelta(minutes=lead_minutes)"
            )
        if self.rate_mmh.ndim != 2:
            raise ValueError("rate_mmh must be 2-D")
        if self.rate_mmh.shape != (self.height, self.width):
            raise ValueError(
                f"rate_mmh shape {self.rate_mmh.shape} != ({self.height}, {self.width})"
            )
        if self.units != "mm/h":
            raise ValueError(f"units must be 'mm/h', got {self.units!r}")
        if np.any(self.rate_mmh < 0):
            raise ValueError("negative rainfall rates are not allowed")
        if not np.all(np.isfinite(self.rate_mmh)):
            raise ValueError("rainfall rates must be finite")

    def compute_fingerprint(self) -> str:
        """Deterministic fingerprint of the nowcast parameters.

        Includes a deterministic hash of the complete contiguous ``rate_mmh``
        array (plus its shape and dtype) so that two fields which share summary
        statistics (mean/max/min) but differ in their full field are
        distinguished. Metadata and summary fields are retained.
        """
        contiguous_array = np.ascontiguousarray(self.rate_mmh)
        field_hash = hashlib.sha256(contiguous_array.tobytes()).hexdigest()
        payload = {
            "initialization_time": self.initialization_time.isoformat(),
            "valid_time": self.valid_time.isoformat(),
            "lead_minutes": self.lead_minutes,
            "method": self.method,
            "source_type": self.source_type,
            "source_provider_id": self.source_provider_id,
            "spatial_reference": self.spatial_reference,
            "spatial_resolution_m": self.spatial_resolution_m,
            "width": self.width,
            "height": self.height,
            "units": self.units,
            "rate_mean_mmh": round(float(np.mean(self.rate_mmh)), 8),
            "rate_max_mmh": round(float(np.max(self.rate_mmh)), 8),
            "rate_min_mmh": round(float(np.min(self.rate_mmh)), 8),
            "field_hash": field_hash,
            "shape": list(self.rate_mmh.shape),
            "dtype": str(self.rate_mmh.dtype),
        }
        canon = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canon.encode("utf-8")).hexdigest()

    def to_dict(self, include_rates: bool = False) -> dict[str, Any]:
        """JSON-safe serialisation.

        Args:
            include_rates: If True, include the full rate array (for API frame).
        """
        d: dict[str, Any] = {
            "initialization_time": self.initialization_time.isoformat(),
            "valid_time": self.valid_time.isoformat(),
            "lead_minutes": self.lead_minutes,
            "units": self.units,
            "spatial_reference": self.spatial_reference,
            "spatial_resolution_m": self.spatial_resolution_m,
            "width": self.width,
            "height": self.height,
            "source_type": self.source_type,
            "source_name": self.source_name,
            "source_provider_id": self.source_provider_id,
            "method": self.method,
            "status": self.status,
            "uncertainty": self.uncertainty,
            "quality_flags": list(self.quality_flags),
            "fingerprint": self.fingerprint or self.compute_fingerprint(),
            "rate_mean_mmh": round(float(np.mean(self.rate_mmh)), 4),
            "rate_max_mmh": round(float(np.max(self.rate_mmh)), 4),
            "rate_min_mmh": round(float(np.min(self.rate_mmh)), 4),
        }
        if include_rates:
            d["values"] = [round(float(v), 3) for v in self.rate_mmh.reshape(-1)]
        if self.metadata:
            d["metadata"] = self.metadata
        return d
