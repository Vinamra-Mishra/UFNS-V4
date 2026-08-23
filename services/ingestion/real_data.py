"""M10 — Real-pilot data ingestion contracts and quality gates.

This module provides the typed contracts, provenance records, and validation
gates for real data ingestion. It enforces strict separation between
SYNTHETIC/FIXTURE and REAL/PROVISIONAL data.

Label semantics (must never be conflated):
  NOT_FETCHED  — no dataset was fetched/loaded; no data is represented.
  SYNTHETIC    — actual synthetic data/entities ARE being represented.
  REAL_DATA    — actual real source data was loaded.
  PROVISIONAL  — governance/approval status, orthogonal to the above.

STATUS: ARCHITECTURE ONLY — actual real datasets (B02 WB AMRUT, Copernicus DEM)
are NOT_FETCHED from the sandbox (CDN blocked). The pipeline is designed to
accept real data when available, but never fabricates missing attributes.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from services.ingestion.provenance import sha256_file


class DataSourceClassification(str, Enum):
    """Mandatory classification for all data sources."""
    SYNTHETIC = "SYNTHETIC"
    SIMULATED = "SIMULATED"
    FIXTURE = "FIXTURE"
    REAL = "REAL"
    PROVISIONAL = "PROVISIONAL"
    APPROVED = "APPROVED"


class DataIngestionStatus(str, Enum):
    """Status of real data ingestion."""
    NOT_FETCHED = "NOT_FETCHED"
    FETCHED = "FETCHED"
    VALIDATED = "VALIDATED"
    NORMALIZED = "NORMALIZED"
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"
    AUDIT_PARTIAL = "AUDIT_PARTIAL"


# SourceProvenance.validation_status values. Describes whether a dataset was
# actually observed and what validation did to it — never conflated with
# ingestion status or governance classification.
VALIDATION_NOT_VALIDATED = "NOT_VALIDATED"  # no data observed; nothing validated
VALIDATION_VALIDATED = "VALIDATED"          # observed data passed all gates
VALIDATION_PARTIAL = "PARTIAL"              # read/fingerprinted, audit incomplete
VALIDATION_FAILED = "FAILED"                # observed data failed to read/validate


class AttributeAvailability(str, Enum):
    """Whether a required attribute is present in the source data."""
    PRESENT = "PRESENT"
    MISSING = "MISSING"
    UNKNOWN = "UNKNOWN"
    DERIVED = "DERIVED"


@dataclass(frozen=True)
class SpatialBounds:
    """Immutable geographic bounding box (degrees)."""
    west: float
    south: float
    east: float
    north: float

    def to_dict(self) -> dict[str, float]:
        return {
            "west": self.west,
            "south": self.south,
            "east": self.east,
            "north": self.north,
        }


@dataclass(frozen=True)
class SourceProvenance:
    """Immutable provenance record for a real data source.

    Deeply immutable: nested spatial bounds are an immutable value object and
    every other field is an immutable type. to_dict() returns fresh copies.
    """
    source_name: str
    dataset_name: str
    version: str
    acquisition_timestamp: datetime
    source_url: str
    license_id: str
    classification: DataSourceClassification
    crs: str
    resolution: str | None = None
    spatial_extent: SpatialBounds | None = None
    schema_fingerprint: str = ""
    data_fingerprint: str = ""
    processing_fingerprint: str = ""
    validation_status: str = VALIDATION_NOT_VALIDATED
    known_limitations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "dataset_name": self.dataset_name,
            "version": self.version,
            "acquisition_timestamp": self.acquisition_timestamp.isoformat(),
            "source_url": self.source_url,
            "license_id": self.license_id,
            "classification": self.classification.value,
            "crs": self.crs,
            "resolution": self.resolution,
            "spatial_extent": self.spatial_extent.to_dict() if self.spatial_extent is not None else None,
            "schema_fingerprint": self.schema_fingerprint,
            "data_fingerprint": self.data_fingerprint,
            "processing_fingerprint": self.processing_fingerprint,
            "validation_status": self.validation_status,
            "known_limitations": list(self.known_limitations),
        }

    def result_snapshot(
        self,
        *,
        acquisition_timestamp: datetime | None = None,
        schema_fingerprint: str = "",
        data_fingerprint: str = "",
        processing_fingerprint: str = "",
        validation_status: str = VALIDATION_NOT_VALIDATED,
        spatial_extent: SpatialBounds | None = None,
        known_limitations: tuple[str, ...] | None = None,
        resolution: str | None = None,
    ) -> SourceProvenance:
        """New immutable provenance snapshot for one ingestion result.

        Source templates (WB_AMRUT_SOURCE, COPERNICUS_DEM_SOURCE) describe the
        source, not a particular ingestion run. Each result must carry its own
        observed state (fingerprints, validation status, extent, limitations);
        the template is never mutated and never shared into results by identity.
        """
        return SourceProvenance(
            source_name=self.source_name,
            dataset_name=self.dataset_name,
            version=self.version,
            acquisition_timestamp=(
                acquisition_timestamp if acquisition_timestamp is not None else self.acquisition_timestamp
            ),
            source_url=self.source_url,
            license_id=self.license_id,
            classification=self.classification,
            crs=self.crs,
            resolution=self.resolution if resolution is None else resolution,
            spatial_extent=spatial_extent,
            schema_fingerprint=schema_fingerprint,
            data_fingerprint=data_fingerprint,
            processing_fingerprint=processing_fingerprint,
            validation_status=validation_status,
            known_limitations=(
                self.known_limitations if known_limitations is None else known_limitations
            ),
        )


@dataclass(frozen=True)
class AttributeAudit:
    """Audit result for a single attribute/column in a real dataset."""
    name: str
    dtype: str
    availability: AttributeAvailability
    null_rate: float = 0.0
    sample_values: tuple[Any, ...] = ()
    unit: str | None = None
    description: str | None = None
    notes: str = ""


@dataclass(frozen=True)
class DatasetAuditResult:
    """Complete audit result for a real dataset."""
    source: SourceProvenance
    file_identity: str
    file_size_bytes: int
    record_count: int
    geometry_type: str
    crs_valid: bool
    coordinate_units: str
    attributes: tuple[AttributeAudit, ...]
    duplicate_count: int = 0
    invalid_geometry_count: int = 0
    spatial_coverage: Mapping[str, float] | None = None
    known_gaps: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    audit_timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        # Independent read-only view: later mutation of the caller's mapping
        # must not reach this record.
        if self.spatial_coverage is not None:
            object.__setattr__(
                self,
                "spatial_coverage",
                MappingProxyType(dict(self.spatial_coverage)),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source.to_dict(),
            "file_identity": self.file_identity,
            "file_size_bytes": self.file_size_bytes,
            "record_count": self.record_count,
            "geometry_type": self.geometry_type,
            "crs_valid": self.crs_valid,
            "coordinate_units": self.coordinate_units,
            "attributes": [
                {
                    "name": a.name,
                    "dtype": a.dtype,
                    "availability": a.availability.value,
                    "null_rate": a.null_rate,
                    "unit": a.unit,
                    "notes": a.notes,
                }
                for a in self.attributes
            ],
            "duplicate_count": self.duplicate_count,
            "invalid_geometry_count": self.invalid_geometry_count,
            "spatial_coverage": dict(self.spatial_coverage) if self.spatial_coverage is not None else None,
            "known_gaps": list(self.known_gaps),
            "blockers": list(self.blockers),
            "audit_timestamp": self.audit_timestamp.isoformat(),
        }


def compute_schema_fingerprint(columns: list[dict[str, str]]) -> str:
    """Deterministic fingerprint of a dataset schema (column names and types)."""
    canon = json.dumps(
        sorted(columns, key=lambda c: c["name"]),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def compute_data_fingerprint(path: Path) -> str:
    """Deterministic fingerprint of a data file."""
    return sha256_file(path)


def validate_crs(crs_string: str, expected_epsg: int | None = None) -> bool:
    """Validate a CRS string, optionally checking against an expected EPSG code."""
    try:
        from pyproj import CRS
        crs = CRS.from_user_input(crs_string)
        if expected_epsg is not None:
            return crs.to_epsg() == expected_epsg
        # CRS.from_user_input raises on invalid input; success means valid.
        return crs.to_epsg() is not None or len(crs.to_wkt()) > 0
    except Exception:  # noqa: BLE001
        return False


def compute_processing_fingerprint(
    steps: Sequence[str],
    params: Mapping[str, Any],
) -> str:
    """Deterministic fingerprint of a processing pipeline invocation.

    Covers the ordered step names plus canonicalized parameters. Wall-clock
    values must never be included: the same input and parameters must yield
    the same fingerprint at any time.
    """
    payload = json.dumps(
        {"steps": list(steps), "params": dict(params)},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def result_labels(
    status: DataIngestionStatus,
    classification: DataSourceClassification,
) -> list[str]:
    """Label triple [ingestion status, governance classification, what is represented].

    The third label describes the DATA ACTUALLY REPRESENTED in the result:
    - NO_DATA: nothing was loaded (NOT_FETCHED/BLOCKED);
    - REAL_DATA: data was loaded through a real-source classification
      (REAL/PROVISIONAL/APPROVED);
    - SYNTHETIC: data was loaded through a fixture/synthetic classification
      (SYNTHETIC/SIMULATED/FIXTURE). Fixture bytes pushed through the real
      ingestion machinery must never be labelled REAL_DATA.
    """
    if status in (DataIngestionStatus.NOT_FETCHED, DataIngestionStatus.BLOCKED):
        represented = "NO_DATA"
    elif classification in (
        DataSourceClassification.SYNTHETIC,
        DataSourceClassification.SIMULATED,
        DataSourceClassification.FIXTURE,
    ):
        represented = "SYNTHETIC"
    else:
        represented = "REAL_DATA"
    return [status.value, classification.value, represented]


class AcquisitionOutcome(str, Enum):
    """Outcome of a single real-source acquisition attempt."""
    FETCHED = "FETCHED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class AcquisitionAttempt:
    """Evidence record for one real-source acquisition attempt.

    Records what was attempted, how it failed (or succeeded), which M10
    real-data gate it affects, and the consequence. A URL alone is not
    evidence of fetching; only FETCHED outcomes carry artifact identity.
    """
    source_name: str
    url: str
    outcome: AcquisitionOutcome
    failure_mode: str = ""
    affected_gate: str = ""
    consequence: str = ""
    attempted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    artifact_path: str | None = None
    artifact_bytes: int | None = None
    artifact_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "url": self.url,
            "outcome": self.outcome.value,
            "failure_mode": self.failure_mode,
            "affected_gate": self.affected_gate,
            "consequence": self.consequence,
            "attempted_at": self.attempted_at.isoformat(),
            "artifact_path": self.artifact_path,
            "artifact_bytes": self.artifact_bytes,
            "artifact_sha256": self.artifact_sha256,
        }


# ---------------------------------------------------------------------------
# Source metadata templates (from documented metadata — NOT_FETCHED).
# These describe the sources; ingestion results must derive result-specific
# snapshots via SourceProvenance.result_snapshot(), never return templates.
# ---------------------------------------------------------------------------

WB_AMRUT_SOURCE = SourceProvenance(
    source_name="india-geodata (yashveeeeeeer/india-geodata)",
    dataset_name="WB_AMRUT_Stormwater",
    version="water/urban-water (2026-03-15)",
    acquisition_timestamp=datetime(2026, 8, 22, tzinfo=timezone.utc),
    source_url="https://github.com/yashveeeeeeer/india-geodata/releases/tag/water/urban-water",
    license_id="India-OGL",
    classification=DataSourceClassification.PROVISIONAL,
    crs="EPSG:4326",
    known_limitations=(
        "CDN blocked from sandbox — actual parquet files NOT_FETCHED",
        "Third-party aggregator (ramSeraph) in provenance chain",
        "Attribute-level audit incomplete (B02 OPEN)",
        "No verified hydraulic attributes (diameter, invert, capacity)",
    ),
)

COPERNICUS_DEM_SOURCE = SourceProvenance(
    source_name="Copernicus DEM GLO-30",
    dataset_name="cop-dem-glo-30",
    version="2021",
    acquisition_timestamp=datetime(2026, 8, 22, tzinfo=timezone.utc),
    source_url="https://planetarycomputer.microsoft.com/api/stac/v1/collections/cop-dem-glo-30",
    license_id="Copernicus",
    classification=DataSourceClassification.PROVISIONAL,
    crs="EPSG:4326",
    resolution="30m (approximately 1 arc-second)",
    known_limitations=(
        "Planetary Computer STAC API unreachable from sandbox",
        "Actual DEM tiles NOT_FETCHED",
        "No pilot-region tile verified",
    ),
)
