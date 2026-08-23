"""M10 — Real drainage data validation, audit and entity mapping (WB AMRUT).

Data-honesty rules enforced here:
  - no hydraulic parameter is ever fabricated (diameter, invert, capacity,
    roughness, Manning n, ...);
  - attributes present in the source with ambiguous semantics or units are
    classified UNRESOLVED, never guessed;
  - a GIS line is not assumed to be a pipe: feature typing uses an explicit
    rule table, and unknown source types map to feature_type UNKNOWN with
    mapping status UNRESOLVED_TYPE;
  - entities that cannot be safely mapped are REJECTED with an explicit
    reason, never silently dropped or coerced.

CRS provenance (2026-08-23):
  The WB AMRUT GeoParquet files carry GeoParquet 1.1.0 structure but do NOT
  embed a CRS in their geo metadata. The source CRS is established as
  EPSG:4326 from authoritative external provenance: the MoHUA / TCPO / NRSC
  AMRUT GIS "Design & Standards for Formulation of GIS based Master Plans
  for AMRUT Cities". This provenance is represented by
  ExternalCRSProvenance and is NEVER conflated with embedded file metadata.

IMPLEMENTED stages (audit_wb_amrut_drains):
  parquet access → data/schema fingerprints → observed-schema audit →
  GeoParquet geometry-column + CRS verification (embedded OR authoritative
  external provenance) → geometry validation (parse/valid/empty/
  unsupported/duplicates) → spatial extent → UFNS required-attribute
  classification (accepted/missing/rejected/unresolved) → explicit audit
  report → result-specific provenance

IMPLEMENTED stages (map_drainage_entities):
  validated source → per-feature geometry normalization → stable entity
  identifiers → explicit type-rule mapping → optional hydraulic attributes
  (only from unambiguous source columns) → mapping status per entity →
  processing fingerprint → result-specific provenance
"""

from __future__ import annotations

import functools
import hashlib
import json
import math
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from services.ingestion.real_data import (
    VALIDATION_FAILED,
    VALIDATION_PARTIAL,
    VALIDATION_VALIDATED,
    WB_AMRUT_SOURCE,
    AttributeAudit,
    AttributeAvailability,
    DataIngestionStatus,
    DatasetAuditResult,
    SourceProvenance,
    SpatialBounds,
    compute_data_fingerprint,
    compute_processing_fingerprint,
    compute_schema_fingerprint,
    result_labels,
    validate_crs,
)


class DrainageFeatureType(str, Enum):
    """Types of drainage features."""
    PIPE = "PIPE"
    DRAIN = "DRAIN"
    CHANNEL = "CHANNEL"
    INLET = "INLET"
    OUTLET = "OUTLET"
    VENT = "VENT"
    MANHOLE = "MANHOLE"
    PUMP = "PUMP"
    UNKNOWN = "UNKNOWN"


class EntityMappingStatus(str, Enum):
    """Mapping outcome for one source feature."""
    MAPPED = "MAPPED"
    UNRESOLVED_TYPE = "UNRESOLVED_TYPE"
    REJECTED_INVALID_GEOMETRY = "REJECTED_INVALID_GEOMETRY"
    REJECTED_UNSUPPORTED_GEOMETRY = "REJECTED_UNSUPPORTED_GEOMETRY"
    REJECTED_DUPLICATE = "REJECTED_DUPLICATE"
    REJECTED_MISSING_GEOMETRY = "REJECTED_MISSING_GEOMETRY"


class CRSProvenanceStatus(str, Enum):
    """How the CRS was established for a dataset.

    EMBEDDED: CRS verified from the file's own GeoParquet metadata.
    AUTHORITATIVE_EXTERNAL: CRS established from authoritative external
        specification (e.g. government GIS standards), NOT from file metadata.
        The file itself carries no embedded CRS; the provenance is recorded
        separately and must never be confused with embedded metadata.
    UNRESOLVED: CRS not established by any verified mechanism.
    """
    EMBEDDED = "EMBEDDED"
    AUTHORITATIVE_EXTERNAL = "AUTHORITATIVE_EXTERNAL_PROVENANCE"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class ExternalCRSProvenance:
    """Authoritative external CRS provenance (NOT from file metadata).

    Records that the CRS was established from an authoritative external
    specification rather than from the file's embedded metadata. The file
    itself may carry no CRS; this record documents the external authority.

    The distinction between embedded and external provenance is preserved
    in all downstream results: external provenance never becomes embedded.
    """
    crs: str                                    # e.g. "EPSG:4326"
    authority: str                              # e.g. "MoHUA / TCPO / NRSC AMRUT GIS D&S"
    source_layers: tuple[str, ...] = ()         # AMRUT feature classes
    evidence_url: str = ""                      # URL to the standard/spec
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "crs": self.crs,
            "authority": self.authority,
            "source_layers": list(self.source_layers),
            "evidence_url": self.evidence_url,
            "notes": self.notes,
        }


# Explicit source-value → feature-type rules. Exact (case-insensitive,
# whitespace-stripped) matches only; every other value is UNRESOLVED_TYPE.
TYPE_RULES: dict[str, DrainageFeatureType] = {
    "drain": DrainageFeatureType.DRAIN,
    "stormwater drain": DrainageFeatureType.DRAIN,
    "pipe": DrainageFeatureType.PIPE,
    "channel": DrainageFeatureType.CHANNEL,
    "open channel": DrainageFeatureType.CHANNEL,
    "vent": DrainageFeatureType.VENT,
    "inlet": DrainageFeatureType.INLET,
    "outlet": DrainageFeatureType.OUTLET,
    "manhole": DrainageFeatureType.MANHOLE,
    "pump": DrainageFeatureType.PUMP,
}


@dataclass(frozen=True)
class HydraulicAttributeRule:
    """Extraction rule from an unambiguous source column.

    scale != 1.0 marks an explicit documented unit derivation (recorded as
    AttributeAvailability.DERIVED on the entity).
    """
    column: str
    target: str
    availability_field: str
    scale: float = 1.0
    derivation: str = ""


# Unambiguous hydraulic columns. Columns whose presence alone leaves units or
# semantics ambiguous (e.g. "diameter", "capacity", "invert", "roughness")
# are deliberately NOT here; they are preserved verbatim in entity attributes
# and classified UNRESOLVED by the schema audit.
HYDRAULIC_RULES: tuple[HydraulicAttributeRule, ...] = (
    HydraulicAttributeRule("diameter_m", "diameter_m", "diameter_availability"),
    HydraulicAttributeRule("diameter_mm", "diameter_m", "diameter_availability",
                           0.001, "mm→m (÷1000)"),
    HydraulicAttributeRule("invert_upstream_m", "invert_upstream_m", "invert_upstream_availability"),
    HydraulicAttributeRule("invert_downstream_m", "invert_downstream_m", "invert_downstream_availability"),
    HydraulicAttributeRule("manning_n", "manning_n", "manning_n_availability"),
    HydraulicAttributeRule("capacity_m3s", "capacity_m3s", "capacity_availability"),
)

# UFNS-required hydraulic attributes and the columns that would satisfy them
# unambiguously (accepted) vs ambiguously (unresolved).
REQUIRED_HYDRAULIC_ATTRIBUTES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("diameter_m", ("diameter_m", "diameter_mm"), ("diameter", "dia", "pipe_diameter")),
    ("invert_upstream_m", ("invert_upstream_m",), ("invert_level_m", "invert", "invert_level")),
    ("invert_downstream_m", ("invert_downstream_m",), ("invert_level_m", "invert", "invert_level")),
    ("manning_n", ("manning_n",), ("roughness", "roughness_coefficient")),
    ("capacity_m3s", ("capacity_m3s",), ("capacity", "design_capacity")),
)

ID_COLUMNS: tuple[str, ...] = ("id", "uid", "feature_id", "ogc_fid")

PIPELINE_VERSION = "m10-drainage-map-v1"

# ---------------------------------------------------------------------------
# WB AMRUT authoritative external CRS provenance
#
# The WB AMRUT GeoParquet files carry GeoParquet 1.1.0 structure metadata
# but do NOT embed a CRS in their geo metadata. The source CRS is established
# from the official AMRUT GIS specification:
#
#   MoHUA / TCPO + NRSC AMRUT GIS programme
#   "Design & Standards for Formulation of GIS based Master Plans for
#    AMRUT Cities"
#
# The AMRUT GIS standards specify:
#   Datum: WGS84
#   GIS database storage/management: Geographic coordinate system
#   UTM projection used for mapping/analysis/printing
#
# The source feature classes correspond to:
#   Str_Drain_NW_Line = Storm Water Drain (line feature)
#   Str_Drain_NW_Pnt  = Storm Water Vent  (point feature)
#
# DISTINCTION: embedded CRS = ABSENT; source CRS = EPSG:4326 via
# authoritative external provenance. This provenance record must NEVER be
# conflated with embedded file metadata.
# ---------------------------------------------------------------------------
WB_AMRUT_EXTERNAL_CRS_PROVENANCE = ExternalCRSProvenance(
    crs="EPSG:4326",
    authority="MoHUA / TCPO / NRSC AMRUT GIS Design & Standards",
    source_layers=("Str_Drain_NW_Line", "Str_Drain_NW_Pnt"),
    evidence_url="https://amrut.gov.in/",
    notes=(
        "WGS84 geographic coordinates per AMRUT GIS specification; "
        "embedded CRS absent from GeoParquet file metadata"
    ),
)


@dataclass(frozen=True)
class DrainageEntity:
    """Normalized drainage entity from real data.

    Missing hydraulic parameters are marked as UNKNOWN, never fabricated.
    Nested ``attributes`` is an immutable mapping; ``to_dict`` returns copies.
    """
    feature_id: str
    feature_type: DrainageFeatureType
    geometry_wkt: str
    crs: str
    attributes: dict[str, Any] = field(default_factory=dict)
    mapping_status: EntityMappingStatus = EntityMappingStatus.MAPPED
    mapping_reason: str = ""
    source_id: str = ""
    source_type: str = ""

    # Hydraulic parameters — may be UNKNOWN
    diameter_m: float | None = None
    diameter_availability: AttributeAvailability = AttributeAvailability.UNKNOWN
    invert_upstream_m: float | None = None
    invert_upstream_availability: AttributeAvailability = AttributeAvailability.UNKNOWN
    invert_downstream_m: float | None = None
    invert_downstream_availability: AttributeAvailability = AttributeAvailability.UNKNOWN
    manning_n: float | None = None
    manning_n_availability: AttributeAvailability = AttributeAvailability.UNKNOWN
    capacity_m3s: float | None = None
    capacity_availability: AttributeAvailability = AttributeAvailability.UNKNOWN

    def __post_init__(self) -> None:
        object.__setattr__(self, "attributes", MappingProxyType(dict(self.attributes)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_id": self.feature_id,
            "feature_type": self.feature_type.value,
            "mapping_status": self.mapping_status.value,
            "mapping_reason": self.mapping_reason,
            "source_id": self.source_id,
            "source_type": self.source_type,
            "crs": self.crs,
            "attributes": dict(self.attributes),
            "diameter_m": self.diameter_m,
            "diameter_availability": self.diameter_availability.value,
            "invert_upstream_m": self.invert_upstream_m,
            "invert_upstream_availability": self.invert_upstream_availability.value,
            "invert_downstream_m": self.invert_downstream_m,
            "invert_downstream_availability": self.invert_downstream_availability.value,
            "manning_n": self.manning_n,
            "manning_n_availability": self.manning_n_availability.value,
            "capacity_m3s": self.capacity_m3s,
            "capacity_availability": self.capacity_availability.value,
        }


@dataclass(frozen=True)
class DrainageSchemaAudit:
    """Source-vs-observed schema classification for a drainage dataset.

    Separates: source (expected) schema, observed schema, accepted attributes
    (unambiguous for UFNS), missing attributes (confirmed absent), rejected
    attributes (present but unusable), unresolved attributes (present but
    semantics/units unverifiable).
    """
    source_attributes: tuple[str, ...]
    observed_columns: tuple[AttributeAudit, ...]
    accepted_attributes: tuple[str, ...]
    missing_attributes: tuple[str, ...]
    rejected_attributes: tuple[str, ...]
    unresolved_attributes: tuple[str, ...]
    hydraulic_findings: tuple[tuple[str, str], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_attributes": list(self.source_attributes),
            "observed_columns": [
                {
                    "name": c.name,
                    "dtype": c.dtype,
                    "availability": c.availability.value,
                    "null_rate": round(c.null_rate, 6),
                    "notes": c.notes,
                }
                for c in self.observed_columns
            ],
            "accepted_attributes": list(self.accepted_attributes),
            "missing_attributes": list(self.missing_attributes),
            "rejected_attributes": list(self.rejected_attributes),
            "unresolved_attributes": list(self.unresolved_attributes),
            "hydraulic_findings": [[k, v] for k, v in self.hydraulic_findings],
        }


@dataclass(frozen=True)
class DrainageIngestionResult:
    """Result of drainage data ingestion."""
    status: DataIngestionStatus
    provenance: SourceProvenance
    entities: tuple[DrainageEntity, ...] = ()
    source_fingerprint: str = ""
    schema_fingerprint: str = ""
    crs_valid: bool = False
    crs_provenance_status: CRSProvenanceStatus = CRSProvenanceStatus.UNRESOLVED
    external_crs_provenance: ExternalCRSProvenance | None = None
    domain_aligned: bool = False
    topology_valid: bool = False
    blockers: tuple[str, ...] = ()
    missing_hydraulic_parameters: tuple[str, ...] = ()
    audit: DatasetAuditResult | None = None
    schema_audit: DrainageSchemaAudit | None = None
    record_count: int = 0
    unsupported_geometry_count: int = 0
    spatial_coverage: SpatialBounds | None = None

    @property
    def labels(self) -> list[str]:
        return result_labels(self.status, self.provenance.classification)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "provenance": self.provenance.to_dict(),
            "entity_count": len(self.entities),
            "source_fingerprint": self.source_fingerprint,
            "schema_fingerprint": self.schema_fingerprint,
            "crs_valid": self.crs_valid,
            "crs_provenance_status": self.crs_provenance_status.value,
            "external_crs_provenance": (
                self.external_crs_provenance.to_dict()
                if self.external_crs_provenance is not None
                else None
            ),
            "domain_aligned": self.domain_aligned,
            "topology_valid": self.topology_valid,
            "blockers": list(self.blockers),
            "missing_hydraulic_parameters": list(self.missing_hydraulic_parameters),
            "audit": self.audit.to_dict() if self.audit is not None else None,
            "schema_audit": self.schema_audit.to_dict() if self.schema_audit is not None else None,
            "record_count": self.record_count,
            "unsupported_geometry_count": self.unsupported_geometry_count,
            "spatial_coverage": self.spatial_coverage.to_dict() if self.spatial_coverage else None,
            "labels": self.labels,
        }


@dataclass(frozen=True)
class MappingRejection:
    """A source feature that could not be safely mapped."""
    source_index: int
    source_id: str
    status: EntityMappingStatus
    detail: str
    source_type: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_index": self.source_index,
            "source_id": self.source_id,
            "status": self.status.value,
            "detail": self.detail,
            "source_type": self.source_type,
        }


@dataclass(frozen=True)
class DrainageMappingConfig:
    """Configuration for drainage entity mapping."""
    source: SourceProvenance = WB_AMRUT_SOURCE
    expected_epsg: int = 4326
    supported_geometry_types: frozenset[str] = frozenset({"LineString", "MultiLineString"})
    type_rules: Mapping[str, DrainageFeatureType] = field(
        default_factory=lambda: MappingProxyType(dict(TYPE_RULES))
    )
    hydraulic_rules: tuple[HydraulicAttributeRule, ...] = HYDRAULIC_RULES
    id_columns: tuple[str, ...] = ID_COLUMNS


@dataclass(frozen=True)
class DrainageMappingResult:
    """Result of mapping audited drainage features to UFNS entities."""
    status: DataIngestionStatus
    provenance: SourceProvenance
    entities: tuple[DrainageEntity, ...] = ()
    rejections: tuple[MappingRejection, ...] = ()
    mapped_count: int = 0
    unresolved_count: int = 0
    rejected_count: int = 0
    unresolved_source_types: tuple[str, ...] = ()
    source_fingerprint: str = ""
    schema_fingerprint: str = ""
    processing_fingerprint: str = ""
    missing_hydraulic_parameters: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    @property
    def labels(self) -> list[str]:
        return result_labels(self.status, self.provenance.classification)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "provenance": self.provenance.to_dict(),
            "entities": [e.to_dict() for e in self.entities],
            "rejections": [r.to_dict() for r in self.rejections],
            "mapped_count": self.mapped_count,
            "unresolved_count": self.unresolved_count,
            "rejected_count": self.rejected_count,
            "unresolved_source_types": list(self.unresolved_source_types),
            "source_fingerprint": self.source_fingerprint,
            "schema_fingerprint": self.schema_fingerprint,
            "processing_fingerprint": self.processing_fingerprint,
            "missing_hydraulic_parameters": list(self.missing_hydraulic_parameters),
            "blockers": list(self.blockers),
            "labels": self.labels,
        }


# ---------------------------------------------------------------------------
# WB AMRUT B02 audit status
# ---------------------------------------------------------------------------

# Expected attributes based on documented metadata (NOT verified — B02 OPEN)
EXPECTED_WB_AMRUT_DRAIN_ATTRIBUTES = [
    {"name": "geometry", "dtype": "LineString"},
    {"name": "id", "dtype": "string"},
    {"name": "name", "dtype": "string"},
    {"name": "type", "dtype": "string"},
    # The following are UNKNOWN until the actual parquet is inspected:
    {"name": "diameter_m", "dtype": "UNKNOWN"},
    {"name": "invert_level_m", "dtype": "UNKNOWN"},
    {"name": "capacity_m3s", "dtype": "UNKNOWN"},
    {"name": "material", "dtype": "UNKNOWN"},
    {"name": "condition", "dtype": "UNKNOWN"},
]


def _read_geoparquet(
    source_path: Path,
) -> tuple[Any, str | None, str | None, list[str]]:
    """Read a (Geo)Parquet file: (df, geometry_column, crs_wkt, notes)."""
    p = Path(source_path).resolve()
    try:
        stat = p.stat()
        file_version = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        file_version = (0, 0)
    return _read_geoparquet_cached(str(p), file_version)


@functools.lru_cache(maxsize=4)
def _read_geoparquet_cached(
    source_path_str: str,
    file_version: tuple[int, int],
) -> tuple[Any, str | None, str | None, list[str]]:
    import pyarrow.parquet as pq

    source_path = Path(source_path_str)
    notes: list[str] = []
    table = pq.read_table(source_path)
    schema_meta = table.schema.metadata or {}
    geo_meta: dict[str, Any] = {}
    if b"geo" in schema_meta:
        try:
            geo_meta = json.loads(schema_meta[b"geo"].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            notes.append("geo schema metadata present but unparseable")
    else:
        notes.append("GeoParquet geo metadata absent — CRS unverifiable from file")

    df = table.to_pandas()
    geom_col: str | None = geo_meta.get("primary_column")
    crs_wkt: str | None = None
    if geom_col is not None:
        col_meta = geo_meta.get("columns", {}).get(geom_col, {})
        crs = col_meta.get("crs")
        crs_wkt = crs if isinstance(crs, str) else json.dumps(crs, sort_keys=True) if crs else None
    if geom_col is None:
        for candidate in ("geometry", "geom", "wkb_geometry"):
            if candidate in df.columns:
                geom_col = candidate
                notes.append(f"geometry column '{candidate}' found without geo metadata")
                break
    return df, geom_col, crs_wkt, notes


def _parse_geometries(df: Any, geom_col: str | None) -> list[Any]:
    """Parse WKB/WKT geometries.

    Null entries become None; unparseable entries become the
    UNPARSEABLE_GEOMETRY sentinel (a distinct source defect).
    """
    if geom_col is None or geom_col not in df.columns:
        return []
    import shapely

    raw = df[geom_col].tolist()
    out: list[Any] = []
    for value in raw:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            out.append(None)
            continue
        geom = None
        if isinstance(value, (bytes, bytearray)):
            try:
                geom = shapely.from_wkb(bytes(value))
            except Exception:  # noqa: BLE001
                geom = UNPARSEABLE_GEOMETRY
        elif isinstance(value, str):
            try:
                geom = shapely.from_wkt(value)
            except Exception:  # noqa: BLE001
                geom = UNPARSEABLE_GEOMETRY
        out.append(geom if geom is not None else UNPARSEABLE_GEOMETRY)
    return out


def _null_rate(series: Any) -> float:
    n = len(series)
    return float(series.isna().sum()) / n if n else 0.0


def _json_safe(value: Any) -> Any:
    import numpy as np

    if value is None or isinstance(value, (bool, int, float, str)):
        if isinstance(value, float) and math.isnan(value):
            return None
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    return str(value)


# Sentinel distinguishing "unparseable geometry bytes" from "null geometry":
# both are unusable, but they are different source defects.
UNPARSEABLE_GEOMETRY = object()


def _classify_schema(
    df: Any,
    geom_col: str | None,
) -> DrainageSchemaAudit:
    """Classify observed columns against UFNS drainage modelling needs."""
    import pandas as pd

    observed: list[AttributeAudit] = []
    accepted: list[str] = []
    rejected: list[str] = []
    unresolved: list[str] = []
    missing: list[str] = []
    findings: list[tuple[str, str]] = []
    columns = {str(c).strip().lower(): c for c in df.columns}

    for col in df.columns:
        series = df[col]
        observed.append(
            AttributeAudit(
                name=str(col),
                dtype=str(series.dtype),
                availability=AttributeAvailability.PRESENT,
                null_rate=_null_rate(series),
                notes="geometry column" if str(col) == geom_col else "",
            )
        )

    if geom_col is None:
        missing.append("geometry: no geometry column observed")

    id_col = next((columns[c] for c in ID_COLUMNS if c in columns), None)
    if id_col is not None:
        accepted.append(f"{id_col}: identifier column")
    else:
        missing.append("identifier: no id-like column (id/uid/feature_id/ogc_fid)")

    type_col = columns.get("type")
    if type_col is not None:
        accepted.append(f"{type_col}: feature type column")
    else:
        missing.append("type: no type column (feature typing will be UNRESOLVED)")

    for required, ok_columns, ambiguous in REQUIRED_HYDRAULIC_ATTRIBUTES:
        ok = next((columns[c] for c in ok_columns if c in columns), None)
        if ok is not None:
            if not pd.api.types.is_numeric_dtype(df[ok]):
                rejected.append(f"{ok}: present but non-numeric dtype ({df[ok].dtype})")
                findings.append((required, f"REJECTED column '{ok}' (non-numeric)"))
            else:
                accepted.append(f"{ok}: satisfies {required}")
                findings.append((required, f"ACCEPTED column '{ok}'"))
        else:
            amb = next((columns[c] for c in ambiguous if c in columns), None)
            if amb is not None:
                unresolved.append(
                    f"{amb}: candidate for {required} but units/semantics unverifiable from column name"
                )
                findings.append((required, f"UNRESOLVED candidate column '{amb}'"))
            else:
                missing.append(f"{required}: confirmed absent from source")
                findings.append((required, "MISSING confirmed absent"))

    return DrainageSchemaAudit(
        source_attributes=tuple(a["name"] for a in EXPECTED_WB_AMRUT_DRAIN_ATTRIBUTES),
        observed_columns=tuple(observed),
        accepted_attributes=tuple(accepted),
        missing_attributes=tuple(missing),
        rejected_attributes=tuple(rejected),
        unresolved_attributes=tuple(unresolved),
        hydraulic_findings=tuple(findings),
    )


def audit_wb_amrut_drains(
    source_path: Path | None = None,
    external_crs_provenance: ExternalCRSProvenance | None = None,
) -> DrainageIngestionResult:
    """Audit the WB AMRUT stormwater drains dataset.

    Without the file: NOT_FETCHED (no data is fabricated or assumed). With the
    file: full attribute/geometry/CRS audit producing an explicit report.

    CRS provenance can be established through two mechanisms:
      A) Embedded CRS in the GeoParquet file metadata (crs_wkt from file)
      B) Authoritative external CRS provenance (external_crs_provenance param)

    When embedded CRS is absent but authoritative external provenance is
    provided, the CRS is marked as AUTHORITATIVE_EXTERNAL_PROVENANCE — never
    conflated with embedded metadata. The file's lack of embedded CRS remains
    explicitly documented.
    """
    if source_path is None or not source_path.exists():
        return DrainageIngestionResult(
            status=DataIngestionStatus.NOT_FETCHED,
            provenance=WB_AMRUT_SOURCE.result_snapshot(),
            blockers=(
                "Source parquet file not available — CDN blocked from sandbox",
                "Attribute-level audit incomplete (B02 OPEN)",
                "Human must run: gh release download water/urban-water --repo yashveeeeeeer/india-geodata --dir data/raw",
            ),
            missing_hydraulic_parameters=(
                "diameter_m (UNKNOWN — not verified in source)",
                "invert_level_m (UNKNOWN — not verified in source)",
                "capacity_m3s (UNKNOWN — not verified in source)",
                "manning_n (UNKNOWN — not verified in source)",
            ),
        )

    now = datetime.now(timezone.utc)
    source_fp = compute_data_fingerprint(source_path)

    try:
        import pandas as pd  # noqa: F401  (readiness guard, matching prior behaviour)
    except ImportError:
        return DrainageIngestionResult(
            status=DataIngestionStatus.BLOCKED,
            provenance=WB_AMRUT_SOURCE.result_snapshot(
                acquisition_timestamp=now,
                data_fingerprint=source_fp,
                validation_status=VALIDATION_FAILED,
                known_limitations=("pandas not available for parquet reading",),
            ),
            source_fingerprint=source_fp,
            blockers=("pandas not available for parquet reading",),
        )

    try:
        df, geom_col, crs_wkt, read_notes = _read_geoparquet(source_path)
    except Exception as e:  # noqa: BLE001
        return DrainageIngestionResult(
            status=DataIngestionStatus.BLOCKED,
            provenance=WB_AMRUT_SOURCE.result_snapshot(
                acquisition_timestamp=now,
                data_fingerprint=source_fp,
                validation_status=VALIDATION_FAILED,
                known_limitations=(f"failed to read parquet: {e}",),
            ),
            source_fingerprint=source_fp,
            blockers=(f"Failed to read parquet: {e}",),
        )

    schema_fp = compute_schema_fingerprint(
        [{"name": col, "dtype": str(dtype)} for col, dtype in df.dtypes.items()]
    )

    crs_valid = False
    crs_provenance_status = CRSProvenanceStatus.UNRESOLVED
    crs_note = "no CRS in file"
    if crs_wkt is not None:
        if validate_crs(crs_wkt, expected_epsg=4326):
            crs_valid = True
            crs_provenance_status = CRSProvenanceStatus.EMBEDDED
            crs_note = "EPSG:4326 (verified from embedded geo metadata)"
        elif validate_crs(crs_wkt):
            crs_note = f"valid CRS but not EPSG:4326: {crs_wkt[:60]}…"
        else:
            crs_note = "CRS unparseable from embedded metadata"
    elif external_crs_provenance is not None:
        # Embedded CRS absent; authoritative external provenance provided.
        # Validate the external CRS independently.
        if validate_crs(external_crs_provenance.crs, expected_epsg=4326):
            crs_valid = True
            crs_provenance_status = CRSProvenanceStatus.AUTHORITATIVE_EXTERNAL
            crs_note = (
                f"embedded CRS: ABSENT; source CRS: {external_crs_provenance.crs} "
                f"(authoritative external: {external_crs_provenance.authority})"
            )
        else:
            crs_note = (
                f"external provenance CRS invalid: {external_crs_provenance.crs}"
            )

    geoms = _parse_geometries(df, geom_col)
    n = len(df)
    unusable = sum(1 for g in geoms if g is None or g is UNPARSEABLE_GEOMETRY)
    valid_geoms = [g for g in geoms if g is not None and g is not UNPARSEABLE_GEOMETRY and not g.is_empty]
    invalid_geom = unusable + sum(1 for g in geoms if g is not None and g is not UNPARSEABLE_GEOMETRY and g.is_empty)
    type_counts = Counter(g.geom_type for g in valid_geoms)
    unsupported = sum(c for t, c in type_counts.items() if t not in ("LineString", "MultiLineString"))
    geometry_type = type_counts.most_common(1)[0][0] if type_counts else "NONE"

    duplicate_count = 0
    columns_lower = {str(c).strip().lower(): c for c in df.columns}
    id_col = next((columns_lower[c] for c in ID_COLUMNS if c in columns_lower), None)
    if id_col is not None:
        duplicate_count = int(df[id_col].duplicated(keep="first").sum())
    elif geom_col is not None and geom_col in df.columns:
        seen: set[bytes] = set()
        for value in df[geom_col].tolist():
            key = bytes(value) if isinstance(value, (bytes, bytearray)) else str(value).encode()
            if key in seen:
                duplicate_count += 1
            else:
                seen.add(key)

    spatial_coverage = None
    if valid_geoms:
        xs: list[float] = []
        ys: list[float] = []
        for g in valid_geoms:
            minx, miny, maxx, maxy = g.bounds
            xs.extend((minx, maxx))
            ys.extend((miny, maxy))
        spatial_coverage = SpatialBounds(
            west=min(xs), south=min(ys), east=max(xs), north=max(ys)
        )

    schema_audit = _classify_schema(df, geom_col)
    missing_params = tuple(
        f"{name} ({finding})"
        for name, finding in schema_audit.hydraulic_findings
        if not finding.startswith("ACCEPTED")
    )

    blockers: list[str] = []
    gaps: list[str] = list(read_notes)
    limitations: list[str] = []

    if n == 0:
        blockers.append("parquet readable but contains zero records")
    if geom_col is None:
        # Schema/attribute audit still runs; geometry audit cannot.
        gaps.append("no geometry column — geometry/extent audit not possible (schema audit only)")
    elif valid_geoms and invalid_geom == n:
        blockers.append("all geometries empty or unparseable")
    elif not valid_geoms and geom_col is not None:
        blockers.append("no parseable geometries")
    if not crs_valid:
        gaps.append(f"CRS not verified: {crs_note}")
    elif crs_provenance_status == CRSProvenanceStatus.AUTHORITATIVE_EXTERNAL:
        # CRS established via authoritative external provenance.
        # Remove the "CRS unverifiable from file" read-notes from gaps:
        # they are expected/documented when external provenance is used.
        # They remain in limitations as informational notes.
        gaps = [
            g for g in gaps
            if "CRS unverifiable from file" not in g
        ]
        limitations.append(f"CRS provenance: {crs_note}")
        if external_crs_provenance is not None:
            limitations.append(
                f"embedded CRS: ABSENT; external authority: "
                f"{external_crs_provenance.authority}; "
                f"source layers: {', '.join(external_crs_provenance.source_layers)}"
            )
    elif crs_provenance_status == CRSProvenanceStatus.EMBEDDED:
        limitations.append(f"CRS: {crs_note}")

    if blockers:
        status = DataIngestionStatus.BLOCKED
        validation_status = VALIDATION_FAILED
        limitations.extend(blockers)
    elif gaps:
        status = DataIngestionStatus.AUDIT_PARTIAL
        validation_status = VALIDATION_PARTIAL
        limitations.extend(gaps)
        limitations.append("attribute/geometry audit incomplete (B02 OPEN)")
    else:
        status = DataIngestionStatus.VALIDATED
        validation_status = VALIDATION_VALIDATED
        limitations.append("attribute-level audit executed; hydraulic modelling use still requires B02 acceptance")
    limitations.extend(f"missing: {m}" for m in schema_audit.missing_attributes)
    limitations.extend(f"unresolved: {u}" for u in schema_audit.unresolved_attributes)
    limitations.extend(f"rejected: {r}" for r in schema_audit.rejected_attributes)

    audit_report = DatasetAuditResult(
        source=WB_AMRUT_SOURCE,
        file_identity=source_path.name,
        file_size_bytes=source_path.stat().st_size,
        record_count=n,
        geometry_type=geometry_type,
        crs_valid=crs_valid,
        coordinate_units="degrees" if crs_valid else "unknown",
        attributes=schema_audit.observed_columns,
        duplicate_count=duplicate_count,
        invalid_geometry_count=invalid_geom,
        spatial_coverage=(
            MappingProxyType(
                {
                    "west": spatial_coverage.west,
                    "south": spatial_coverage.south,
                    "east": spatial_coverage.east,
                    "north": spatial_coverage.north,
                }
            )
            if spatial_coverage
            else None
        ),
        known_gaps=tuple(gaps),
        blockers=tuple(blockers),
        audit_timestamp=now,
    )

    return DrainageIngestionResult(
        status=status,
        provenance=WB_AMRUT_SOURCE.result_snapshot(
            acquisition_timestamp=now,
            schema_fingerprint=schema_fp,
            data_fingerprint=source_fp,
            validation_status=validation_status,
            spatial_extent=spatial_coverage,
            known_limitations=tuple(limitations),
        ),
        entities=(),
        source_fingerprint=source_fp,
        schema_fingerprint=schema_fp,
        crs_valid=crs_valid,
        crs_provenance_status=crs_provenance_status,
        external_crs_provenance=external_crs_provenance,
        blockers=tuple(blockers),
        missing_hydraulic_parameters=tuple(missing_params),
        audit=audit_report,
        schema_audit=schema_audit,
        record_count=n,
        unsupported_geometry_count=unsupported,
        spatial_coverage=spatial_coverage,
    )


def _stable_entity_id(dataset_name: str, identity: str) -> str:
    digest = hashlib.sha256(f"{dataset_name}:{identity}".encode()).hexdigest()
    return f"ufns-{digest[:16]}"


def map_drainage_entities(
    source_path: Path | None = None,
    config: DrainageMappingConfig | None = None,
    external_crs_provenance: ExternalCRSProvenance | None = None,
) -> DrainageMappingResult:
    """Map audited WB AMRUT drain features into UFNS DrainageEntity records.

    Requires a VALIDATED source audit (geometry + CRS verified, where CRS
    may be established through embedded metadata or authoritative external
    provenance). Every source feature becomes either an entity (MAPPED or
    UNRESOLVED_TYPE) or an explicit MappingRejection — nothing is silently
    dropped, coerced, or fabricated.
    """
    config = config or DrainageMappingConfig()

    audit = audit_wb_amrut_drains(source_path, external_crs_provenance=external_crs_provenance)
    if audit.status == DataIngestionStatus.NOT_FETCHED:
        return DrainageMappingResult(
            status=DataIngestionStatus.NOT_FETCHED,
            provenance=audit.provenance,
            blockers=audit.blockers,
            missing_hydraulic_parameters=audit.missing_hydraulic_parameters,
        )
    if audit.status != DataIngestionStatus.VALIDATED:
        return DrainageMappingResult(
            status=DataIngestionStatus.BLOCKED,
            provenance=audit.provenance.result_snapshot(
                validation_status=VALIDATION_FAILED,
                known_limitations=audit.blockers or ("source audit incomplete",),
            ),
            source_fingerprint=audit.source_fingerprint,
            schema_fingerprint=audit.schema_fingerprint,
            blockers=("mapping requires a VALIDATED source audit", *audit.blockers),
            missing_hydraulic_parameters=audit.missing_hydraulic_parameters,
        )

    assert source_path is not None
    from shapely import wkb as wkb_io

    df, geom_col, _crs_wkt, _notes = _read_geoparquet(source_path)
    assert geom_col is not None and geom_col in df.columns  # guaranteed by VALIDATED
    geoms = _parse_geometries(df, geom_col)
    columns_lower = {str(c).strip().lower(): c for c in df.columns}
    id_col = next((columns_lower[c] for c in config.id_columns if c in columns_lower), None)
    type_col = columns_lower.get("type")

    crs_label = f"EPSG:{config.expected_epsg}"
    entities: list[DrainageEntity] = []
    rejections: list[MappingRejection] = []
    unresolved_types: set[str] = set()
    seen_ids: set[str] = set()
    seen_geom: set[bytes] = set()
    now = datetime.now(timezone.utc)

    for i, geom in enumerate(geoms):
        row = df.iloc[i]
        source_id = str(row[id_col]) if id_col is not None and row[id_col] == row[id_col] else ""
        source_type = (
            str(row[type_col]) if type_col is not None and row[type_col] == row[type_col] else ""
        )

        if geom is None:
            rejections.append(
                MappingRejection(i, source_id, EntityMappingStatus.REJECTED_MISSING_GEOMETRY,
                                 "geometry is null in source", source_type)
            )
            continue
        if geom is UNPARSEABLE_GEOMETRY:
            rejections.append(
                MappingRejection(i, source_id, EntityMappingStatus.REJECTED_INVALID_GEOMETRY,
                                 "geometry bytes unparseable as WKB/WKT", source_type)
            )
            continue
        if geom.is_empty:
            rejections.append(
                MappingRejection(i, source_id, EntityMappingStatus.REJECTED_INVALID_GEOMETRY,
                                 "geometry is empty", source_type)
            )
            continue
        if not geom.is_valid:
            rejections.append(
                MappingRejection(i, source_id, EntityMappingStatus.REJECTED_INVALID_GEOMETRY,
                                 "geometry fails OGC validity", source_type)
            )
            continue
        if geom.geom_type not in config.supported_geometry_types:
            rejections.append(
                MappingRejection(i, source_id, EntityMappingStatus.REJECTED_UNSUPPORTED_GEOMETRY,
                                 f"unsupported geometry type {geom.geom_type} for drain mapping", source_type)
            )
            continue

        wkb = wkb_io.dumps(geom)
        geom_key = hashlib.sha256(wkb).digest()
        if id_col is not None and source_id != "" and source_id in seen_ids:
            rejections.append(
                MappingRejection(i, source_id, EntityMappingStatus.REJECTED_DUPLICATE,
                                 f"duplicate source id '{source_id}'", source_type)
            )
            continue
        if geom_key in seen_geom:
            rejections.append(
                MappingRejection(i, source_id, EntityMappingStatus.REJECTED_DUPLICATE,
                                 "duplicate geometry (identical WKB seen earlier)", source_type)
            )
            continue
        seen_geom.add(geom_key)
        if source_id != "":
            seen_ids.add(source_id)

        identity = source_id if source_id != "" else f"geom:{geom_key.hex()[:32]}"
        feature_id = _stable_entity_id(config.source.dataset_name, identity)

        feature_type = DrainageFeatureType.UNKNOWN
        mapping_status = EntityMappingStatus.UNRESOLVED_TYPE
        reason = ""
        raw_type = source_type.strip().lower() if source_type else ""
        if raw_type in config.type_rules:
            feature_type = config.type_rules[raw_type]
            mapping_status = EntityMappingStatus.MAPPED
            reason = f"type rule '{raw_type}' → {feature_type.value}"
        else:
            unresolved_types.add(source_type or "<empty type>")
            reason = f"no explicit type rule for source value '{source_type or ''}' — not guessed"

        if identity.startswith("geom:"):
            reason += "; stable id derived from geometry (no source id column)"

        hydraulic_kwargs: dict[str, Any] = {}
        derivations: list[str] = []
        for rule in config.hydraulic_rules:
            col = columns_lower.get(rule.column)
            if col is None:
                continue
            value = row[col]
            if value is None or (isinstance(value, float) and math.isnan(value)):
                hydraulic_kwargs[rule.target] = None
                hydraulic_kwargs[rule.availability_field] = AttributeAvailability.MISSING
                derivations.append(f"{rule.target}: null in source row")
                continue
            try:
                scaled = float(value) * rule.scale
            except (TypeError, ValueError):
                hydraulic_kwargs[rule.target] = None
                hydraulic_kwargs[rule.availability_field] = AttributeAvailability.MISSING
                derivations.append(f"{rule.target}: non-numeric source value")
                continue
            hydraulic_kwargs[rule.target] = scaled
            hydraulic_kwargs[rule.availability_field] = (
                AttributeAvailability.DERIVED if rule.derivation else AttributeAvailability.PRESENT
            )
            if rule.derivation:
                derivations.append(f"{rule.target}: {rule.derivation}")

        attrs = {
            str(c): _json_safe(row[c])
            for c in df.columns
            if c != geom_col
        }

        if derivations:
            reason += "; " + ", ".join(derivations)

        entities.append(
            DrainageEntity(
                feature_id=feature_id,
                feature_type=feature_type,
                geometry_wkt=geom.wkt,
                crs=crs_label,
                attributes=attrs,
                mapping_status=mapping_status,
                mapping_reason=reason,
                source_id=source_id,
                source_type=source_type,
                **hydraulic_kwargs,
            )
        )

    mapped = sum(1 for e in entities if e.mapping_status == EntityMappingStatus.MAPPED)
    unresolved = len(entities) - mapped

    steps = [
        "audit_source",
        "normalize_geometry",
        "stable_entity_ids",
        "type_rule_mapping",
        "hydraulic_attribute_extraction",
        "provenance",
    ]
    params = {
        "pipeline_version": PIPELINE_VERSION,
        "source_data_fingerprint": audit.source_fingerprint,
        "schema_fingerprint": audit.schema_fingerprint,
        "source_dataset_name": config.source.dataset_name,
        "expected_epsg": config.expected_epsg,
        "supported_geometry_types": sorted(config.supported_geometry_types),
        "type_rules": [
            [k, getattr(config.type_rules[k], "value", str(config.type_rules[k]))]
            for k in sorted(config.type_rules)
        ],
        "hydraulic_rules": [
            [r.column, r.target, r.scale, r.derivation] for r in config.hydraulic_rules
        ],
        "id_columns": list(config.id_columns),
        "entity_count": len(entities),
        "rejection_count": len(rejections),
    }
    processing_fp = compute_processing_fingerprint(steps, params)

    limitations = [
        "geometry preserved in source CRS (EPSG:4326); domain/grid alignment not yet applied",
        "topology/connectivity not validated",
        "hydraulic attributes only where unambiguous source columns exist — none fabricated",
    ]
    limitations.extend(f"unresolved source types: {t}" for t in sorted(unresolved_types))
    if audit.missing_hydraulic_parameters:
        limitations.extend(f"missing hydraulic: {m}" for m in audit.missing_hydraulic_parameters)
    if rejections:
        limitations.append(f"{len(rejections)} source features rejected (see rejections in result)")

    return DrainageMappingResult(
        status=DataIngestionStatus.NORMALIZED,
        provenance=config.source.result_snapshot(
            acquisition_timestamp=now,
            schema_fingerprint=audit.schema_fingerprint,
            data_fingerprint=audit.source_fingerprint,
            processing_fingerprint=processing_fp,
            validation_status=VALIDATION_VALIDATED,
            spatial_extent=audit.spatial_coverage,
            known_limitations=tuple(limitations),
        ),
        entities=tuple(entities),
        rejections=tuple(rejections),
        mapped_count=mapped,
        unresolved_count=unresolved,
        rejected_count=len(rejections),
        unresolved_source_types=tuple(sorted(unresolved_types)),
        source_fingerprint=audit.source_fingerprint,
        schema_fingerprint=audit.schema_fingerprint,
        processing_fingerprint=processing_fp,
        missing_hydraulic_parameters=audit.missing_hydraulic_parameters,
    )
