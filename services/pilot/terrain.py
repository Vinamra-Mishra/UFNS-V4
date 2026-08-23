"""M11 — Real DEM terrain adapter (Section 4).

Integrates the normalized real DEM into the UFNS terrain/surface model through
an explicit M11 adapter that wraps the authoritative M10 normalization
machinery (services/ingestion/dem_real.py). It does NOT:

  - create a second DEM processing implementation,
  - silently fill source nodata,
  - infer terrain from filenames,
  - rewrite the M2/M4 surface-routing mathematics.

The resulting :class:`RealTerrain` object carries sufficient provenance to
answer (Section 4):

    1. Which raw DEM was used?
    2. What was its SHA-256?
    3. What CRS did it originate in?
    4. What CRS was used for modelling?
    5. What GridSpec was used?
    6. What resampling method was used?
    7. Was nodata present?
    8. What processing fingerprint identifies the normalized result?
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from services.contracts import GridSpec
from services.ingestion.dem_real import (
    DEMNormalizationResult,
    pilot_grid_spec,
)
from services.ingestion.drainage_real import CRSProvenanceStatus
from services.ingestion.provenance import sha256_file
from services.pilot.provenance import CRSSourceProvenance


@dataclass(frozen=True)
class RealTerrain:
    """Normalized real DEM as a terrain object with full provenance.

    Deeply immutable: elevation is not exposed mutably via the contract (the
    caller receives the array reference for modelling, but provenance fields
    are all immutable and ``to_dict`` does not leak the array).
    """

    elevation: np.ndarray
    grid: GridSpec
    nodata: float
    nodata_cells: int
    total_cells: int
    resampling: str
    raw_dem_path: Path
    raw_dem_sha256: str
    source_crs: str
    modelling_crs: str
    embedded_crs: str
    crs_provenance_status: str
    processing_fingerprint: str
    vertical_reference: str
    normalization_status: str
    crs_source: CRSSourceProvenance

    # -- provenance answers (Section 4) ------------------------------------
    @property
    def nodata_present(self) -> bool:
        return self.nodata_cells > 0

    def provenance_answers(self) -> dict[str, Any]:
        """The eight provenance questions, answered explicitly."""
        return {
            "raw_dem_used": str(self.raw_dem_path),
            "raw_dem_sha256": self.raw_dem_sha256,
            "source_crs": self.source_crs,
            "modelling_crs": self.modelling_crs,
            "gridspec": self.grid.model_dump(mode="json"),
            "resampling": self.resampling,
            "nodata_present": self.nodata_present,
            "processing_fingerprint": self.processing_fingerprint,
        }

    def to_dict(self) -> dict[str, Any]:
        valid = self.elevation[self.elevation != self.nodata]
        return {
            "normalization_status": self.normalization_status,
            "grid": self.grid.model_dump(mode="json"),
            "elevation_shape": list(self.elevation.shape),
            "nodata": self.nodata,
            "nodata_cells": self.nodata_cells,
            "total_cells": self.total_cells,
            "nodata_present": self.nodata_present,
            "resampling": self.resampling,
            "vertical_reference": self.vertical_reference,
            "raw_dem_path": str(self.raw_dem_path),
            "raw_dem_sha256": self.raw_dem_sha256,
            "crs_source": self.crs_source.to_dict(),
            "processing_fingerprint": self.processing_fingerprint,
            "valid_elevation_min_m": round(float(valid.min()), 4) if valid.size else None,
            "valid_elevation_max_m": round(float(valid.max()), 4) if valid.size else None,
            "provenance_answers": self.provenance_answers(),
            "labels": ["REAL_DATA", "PROVISIONAL", "REAL_TERRAIN"],
        }


class RealTerrainAdapter:
    """Adapts the authoritative M10 DEM normalization into a RealTerrain.

    Uses the existing normalize_dem() machinery and the authoritative pilot
    GridSpec. Never fabricates, never fills nodata, never infers from
    filenames.
    """

    def __init__(self, source_path: Path | None = None) -> None:
        self.source_path = source_path

    def load(
        self,
        source_path: Path | None = None,
    ) -> RealTerrain:
        path = source_path or self.source_path
        if path is None:
            raise ValueError("a real DEM source path is required")
        result: DEMNormalizationResult = _normalize(path)
        if result.elevation is None or result.grid is None:
            raise RuntimeError(
                f"real DEM normalization did not produce terrain "
                f"(status={result.status.value}); no fallback is fabricated"
            )

        grid = result.grid
        src_crs_prov = getattr(result.provenance, "crs_source", None)
        if src_crs_prov is not None:
            source_crs = src_crs_prov.source_crs
            prov_status = src_crs_prov.provenance_status
            embedded_crs = src_crs_prov.embedded_crs
            authority = src_crs_prov.authority
        elif result.provenance and getattr(result.provenance, "native_crs", None):
            source_crs = result.provenance.native_crs
            prov_status = CRSProvenanceStatus.EMBEDDED.value
            embedded_crs = source_crs
            authority = getattr(result.provenance, "source_name", "Source file metadata")
        elif result.output_crs:
            source_crs = result.output_crs
            prov_status = CRSProvenanceStatus.EMBEDDED.value
            embedded_crs = result.output_crs
            authority = "Source file raster metadata"
        else:
            source_crs = "ABSENT"
            prov_status = CRSProvenanceStatus.UNRESOLVED.value
            embedded_crs = "ABSENT"
            authority = ""

        crs_source = CRSSourceProvenance(
            source_crs=source_crs,
            modelling_crs=grid.crs_wkt_or_epsg,
            embedded_crs=embedded_crs,
            provenance_status=prov_status,
            authority=authority,
        )
        raw_sha = sha256_file(path)
        return RealTerrain(
            elevation=result.elevation,
            grid=grid,
            nodata=result.nodata if result.nodata is not None else float("nan"),
            nodata_cells=result.nodata_cells,
            total_cells=result.total_cells,
            resampling=result.resampling,
            raw_dem_path=Path(path),
            raw_dem_sha256=raw_sha,
            source_crs=source_crs,
            modelling_crs=grid.crs_wkt_or_epsg,
            embedded_crs=embedded_crs,
            crs_provenance_status=prov_status,
            processing_fingerprint=result.processing_fingerprint,
            vertical_reference="REAL_DEM_VERTICAL_DATUM_UNVERIFIED",
            normalization_status=result.status.value,
            crs_source=crs_source,
        )


def _normalize(source_path: Path) -> DEMNormalizationResult:
    """Wrap the authoritative M10 normalize_dem onto the pilot grid."""
    from services.ingestion.dem_real import DEMIngestionConfig, normalize_dem

    return normalize_dem(source_path, DEMIngestionConfig())


def authoritative_pilot_grid() -> GridSpec:
    """The authoritative real-pilot GridSpec (single source of truth)."""
    return pilot_grid_spec()
