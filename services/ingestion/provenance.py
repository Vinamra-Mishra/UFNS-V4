"""Provenance, manifests, checksums, fingerprints (ARCHITECTURE §7, §9)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from services.contracts import DataLineage, ProvenanceClass, QualityFlag


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_lineage(
    dataset_id: str,
    version: str,
    source_name: str,
    provenance_class: ProvenanceClass,
    content: Path | bytes,
    licence_id: Optional[str] = None,
    source_url: Optional[str] = None,
    quality_flags: Optional[list[QualityFlag]] = None,
    native_crs: Optional[str] = None,
    native_resolution: Optional[dict[str, Any]] = None,
    processing_steps: Optional[list[str]] = None,
    acquired_at: Optional[datetime] = None,
) -> DataLineage:
    digest = sha256_file(content) if isinstance(content, Path) else sha256_bytes(content)
    return DataLineage(
        dataset_id=dataset_id,
        version=version,
        source_name=source_name,
        source_url=source_url,
        licence_id=licence_id,
        acquired_at=acquired_at or datetime.now(timezone.utc),
        content_sha256=digest,
        provenance_class=provenance_class,
        quality_flags=quality_flags or [],
        native_crs=native_crs,
        native_resolution=native_resolution,
        processing_steps=processing_steps or [],
    )


class Manifest:
    """Versioned pilot/demo bundle manifest (DATA_SOURCES §10)."""

    def __init__(self, pilot_id: str, base_dir: Optional[Path] = None) -> None:
        self.pilot_id = pilot_id
        self.base_dir = base_dir
        self.assets: list[dict[str, Any]] = []

    def add_asset(
        self,
        role: str,
        path: Path,
        lineage: DataLineage,
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        if self.base_dir is not None and self.base_dir in path.parents:
            uri = str(path.relative_to(self.base_dir))
        else:
            uri = str(path)
        base = {
            "role": role,
            "asset_uri": uri,
            "content_sha256": lineage.content_sha256,
            "provenance_class": lineage.provenance_class.value,
            "quality_flags": [f.value for f in lineage.quality_flags],
            "licence_id": lineage.licence_id,
            "native_crs": lineage.native_crs,
            "native_resolution": lineage.native_resolution,
        }
        if extra:
            for k, v in extra.items():
                if k not in base:
                    base[k] = v
        self.assets.append(base)

    def write(self, out_path: Path, extra: Optional[dict[str, Any]] = None, created_at: Optional[datetime] = None) -> Path:
        from services.ingestion.timeutil import iso_utc

        doc = {
            "pilot_id": self.pilot_id,
            "bundle_version": "v1",
            "created_at": iso_utc(created_at or datetime.now(timezone.utc)),
            "interchange_crs": "OGC:CRS84",
            "assets": self.assets,
        }
        if extra:
            for k, v in extra.items():
                if k not in doc:
                    doc[k] = v
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(doc, indent=2))
        return out_path
