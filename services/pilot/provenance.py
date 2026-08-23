"""M11 — Deeply immutable real-pilot provenance object (Section 13).

Every real-pilot result must be traceable. This object carries the full
provenance chain:

    raw DEM SHA-256
    raw drainage SHA-256
    source CRS provenance
    normalized DEM fingerprint
    drainage mapping fingerprint
    GridSpec fingerprint
    rainfall fingerprint
    model configuration fingerprint
    scenario fingerprint
    model mode
    software/model version
    status labels

It is deeply immutable: all nested members are immutable types and to_dict()
returns fresh copies. A caller must not be able to mutate provenance after
result creation.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any


def gridspec_fingerprint(grid_dict: Mapping[str, Any]) -> str:
    """Deterministic fingerprint of a GridSpec (canonical JSON subset)."""
    keys = (
        "grid_id", "crs_wkt_or_epsg", "width", "height",
        "affine_transform", "cell_size_m", "bounds",
    )
    payload = {k: grid_dict.get(k) for k in keys}
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CRSSourceProvenance:
    """How a dataset's CRS was established (immutable)."""

    source_crs: str
    modelling_crs: str
    embedded_crs: str            # "ABSENT" when the file carries no CRS
    provenance_status: str       # EMBEDDED | AUTHORITATIVE_EXTERNAL_PROVENANCE | UNRESOLVED
    authority: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_crs": self.source_crs,
            "modelling_crs": self.modelling_crs,
            "embedded_crs": self.embedded_crs,
            "provenance_status": self.provenance_status,
            "authority": self.authority,
        }


@dataclass(frozen=True)
class RealPilotProvenance:
    """Deeply immutable real-pilot provenance (Section 13)."""

    raw_dem_sha256: str = ""
    raw_dem_path: str = ""
    raw_drainage_sha256: str = ""
    raw_drainage_path: str = ""
    crs_source: CRSSourceProvenance | None = None
    normalized_dem_fingerprint: str = ""
    drainage_mapping_fingerprint: str = ""
    gridspec_fingerprint: str = ""
    rainfall_fingerprint: str = ""
    model_config_fingerprint: str = ""
    scenario_fingerprint: str = ""
    model_mode: str = ""
    software_version: str = ""
    status_labels: tuple[str, ...] = ()
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Independent read-only view of the caller's mapping so later
        # mutation of the caller's dict cannot reach this provenance.
        object.__setattr__(self, "extra", MappingProxyType(dict(self.extra)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_dem_sha256": self.raw_dem_sha256,
            "raw_dem_path": self.raw_dem_path,
            "raw_drainage_sha256": self.raw_drainage_sha256,
            "raw_drainage_path": self.raw_drainage_path,
            "crs_source": self.crs_source.to_dict() if self.crs_source else None,
            "normalized_dem_fingerprint": self.normalized_dem_fingerprint,
            "drainage_mapping_fingerprint": self.drainage_mapping_fingerprint,
            "gridspec_fingerprint": self.gridspec_fingerprint,
            "rainfall_fingerprint": self.rainfall_fingerprint,
            "model_config_fingerprint": self.model_config_fingerprint,
            "scenario_fingerprint": self.scenario_fingerprint,
            "model_mode": self.model_mode,
            "software_version": self.software_version,
            "status_labels": list(self.status_labels),
            "extra": dict(self.extra),
        }
