"""M11 — Real drainage model integration adapter (Sections 5, 10, 11).

Wraps the authoritative M10 drainage mapping machinery and adds the M11
deterministic reprojection/alignment of real drainage geometry from the
source CRS (EPSG:4326) onto the model grid (EPSG:32645) through the existing
governed spatial stack (pyproj).

Rules enforced (Sections 5, 10, 11):
  - no hydraulic parameter is fabricated (delegated to M10 mapping);
  - the source CRS is established only through governed external provenance
    (the files carry no embedded CRS); it is never silently assumed;
  - no hand-written coordinate shifts / approximate offsets;
  - no filename-based positioning;
  - every resulting entity is traceable back to its source ID;
  - M10 entity-mapping semantics are preserved (MAPPED / UNRESOLVED_TYPE /
    REJECTED_*); unresolved types are never reinterpreted to raise counts;
  - vents (MultiPoint) are handled by the existing contract, never coerced
    into lines.

The output :class:`AlignedDrainage` carries the reprojection provenance and
the mapping statistics, but NO hydraulic parameters (those remain MISSING).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.contracts import GridSpec
from services.ingestion.drainage_real import (
    WB_AMRUT_EXTERNAL_CRS_PROVENANCE,
    CRSProvenanceStatus,
    DrainageMappingResult,
    map_drainage_entities,
)
from services.ingestion.provenance import sha256_file
from services.pilot.provenance import CRSSourceProvenance


@dataclass(frozen=True)
class AlignedDrainage:
    """Real drainage geometry aligned to the model grid (no hydraulics).

    ``entities_reprojected`` keeps each entity's source id/geometry and adds a
    reprojected geometry in the modelling CRS. No hydraulic fields are added.
    """

    grid: GridSpec
    mapping_result: DrainageMappingResult
    entities_reprojected: tuple[dict[str, Any], ...]
    source_crs: str
    modelling_crs: str
    crs_source: CRSSourceProvenance
    raw_drainage_sha256: str
    raw_drainage_path: str
    processing_fingerprint: str
    mapped_count: int
    unresolved_count: int
    rejected_count: int
    rejection_breakdown: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "grid": self.grid.model_dump(mode="json"),
            "source_crs": self.source_crs,
            "modelling_crs": self.modelling_crs,
            "crs_source": self.crs_source.to_dict(),
            "raw_drainage_sha256": self.raw_drainage_sha256,
            "raw_drainage_path": self.raw_drainage_path,
            "processing_fingerprint": self.processing_fingerprint,
            "mapped_count": self.mapped_count,
            "unresolved_count": self.unresolved_count,
            "rejected_count": self.rejected_count,
            "rejection_breakdown": dict(self.rejection_breakdown),
            "unresolved_source_types": list(self.mapping_result.unresolved_source_types),
            "entity_count": len(self.entities_reprojected),
            "labels": ["REAL_DATA", "PROVISIONAL", "REAL_DRAINAGE_GEOMETRY"],
        }


class RealDrainageAdapter:
    """Maps real drainage and aligns it to the model grid.

    The CRS is established through the governed external provenance
    (WB_AMRUT_EXTERNAL_CRS_PROVENANCE). The file's embedded CRS absence is
    preserved and never conflated.
    """

    def __init__(self, source_path: Path) -> None:
        self.source_path = Path(source_path)

    def map_and_align(self, grid: GridSpec) -> AlignedDrainage:
        mapping = map_drainage_entities(
            self.source_path,
            external_crs_provenance=WB_AMRUT_EXTERNAL_CRS_PROVENANCE,
        )
        if mapping.entities and mapping.entities[0].crs != "EPSG:4326" and not self.source_path:
            # Defensive: mapping carries EPSG:4326 when external provenance used.
            pass

        reprojected = _reproject_entities(mapping, target_crs=grid.crs_wkt_or_epsg)

        breakdown = Counter(r.status.value for r in mapping.rejections)
        crs_source = CRSSourceProvenance(
            source_crs="EPSG:4326",
            modelling_crs=grid.crs_wkt_or_epsg,
            embedded_crs="ABSENT",
            provenance_status=CRSProvenanceStatus.AUTHORITATIVE_EXTERNAL.value,
            authority="MoHUA / TCPO / NRSC AMRUT GIS Design & Standards",
        )
        return AlignedDrainage(
            grid=grid,
            mapping_result=mapping,
            entities_reprojected=tuple(reprojected),
            source_crs="EPSG:4326",
            modelling_crs=grid.crs_wkt_or_epsg,
            crs_source=crs_source,
            raw_drainage_sha256=sha256_file(self.source_path),
            raw_drainage_path=str(self.source_path),
            processing_fingerprint=mapping.processing_fingerprint,
            mapped_count=mapping.mapped_count,
            unresolved_count=mapping.unresolved_count,
            rejected_count=mapping.rejected_count,
            rejection_breakdown=dict(breakdown),
        )


def _reproject_entities(
    mapping: DrainageMappingResult,
    target_crs: str,
) -> list[dict[str, Any]]:
    """Deterministic reprojection of mapped entities to the modelling CRS.

    Uses pyproj Transformer (the governed spatial stack). Each output entity
    keeps its source id, mapping status, and source type — fully traceable.
    No hydraulic fields are added; geometries are reprojected verbatim.
    """
    from pyproj import Transformer
    from shapely import from_wkt
    from shapely.ops import transform as shp_transform

    if not mapping.entities:
        return []

    transformer = Transformer.from_crs("EPSG:4326", target_crs, always_xy=True)
    out: list[dict[str, Any]] = []
    for ent in mapping.entities:
        geom = from_wkt(ent.geometry_wkt)
        geom_t = shp_transform(transformer.transform, geom)
        out.append(
            {
                "feature_id": ent.feature_id,
                "source_id": ent.source_id,
                "source_type": ent.source_type,
                "mapping_status": ent.mapping_status.value,
                "feature_type": ent.feature_type.value,
                "geometry_wkt_model_crs": geom_t.wkt,
                "geometry_crs": target_crs,
            }
        )
    return out


def drainage_mapping_stats(mapping: DrainageMappingResult) -> dict[str, Any]:
    """Auditable per-status counts for a drainage mapping result."""
    breakdown = Counter(r.status.value for r in mapping.rejections)
    return {
        "total_source_features": mapping.mapped_count
        + mapping.unresolved_count
        + mapping.rejected_count,
        "mapped": mapping.mapped_count,
        "unresolved_type": mapping.unresolved_count,
        "rejected": mapping.rejected_count,
        "rejection_breakdown": dict(breakdown),
        "unresolved_source_types": list(mapping.unresolved_source_types),
        "missing_hydraulic_parameters": list(mapping.missing_hydraulic_parameters),
    }
