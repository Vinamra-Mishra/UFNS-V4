"""M10 — Record provenance for real artifacts supplied outside the sandbox.

The 2026-08-22 in-sandbox download attempts for the WB AMRUT release assets
and the Copernicus DEM GLO-30 STAC collection were BLOCKED (see the existing
records in data/raw/acquisition_attempts.json). The artifacts were then
supplied by a human from a machine with normal network access and placed in
the canonical raw-data location (data/raw/).

This script records FETCHED evidence for each supplied artifact — path,
bytes, SHA-256 — using the existing AcquisitionAttempt record type, and
appends the records to the existing evidence file. Previous attempt records
are preserved verbatim: a resolved acquisition blocker is evidenced, never
deleted.

A FETCHED record only establishes that the artifact is available; it does
NOT validate the artifact. Validation/audit evidence comes from the M10
pipelines (ingest_dem / normalize_dem / audit_wb_amrut_drains /
map_drainage_entities) run against data/raw/.

Run: python scripts/record_real_artifact_evidence.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.ingestion.acquisition import (
    verify_local_artifact,
    write_attempts_evidence,
)
from services.ingestion.real_data import AcquisitionAttempt, AcquisitionOutcome


def _reconstruct(rec: dict) -> AcquisitionAttempt:
    rec = dict(rec)
    rec["outcome"] = AcquisitionOutcome(rec["outcome"])
    rec["attempted_at"] = datetime.fromisoformat(rec["attempted_at"])
    return AcquisitionAttempt(**rec)


def _repo_relative(path_str: str | None) -> str | None:
    """Record committed evidence with repo-relative artifact paths (portable)."""
    if path_str is None:
        return None
    try:
        return Path(path_str).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path_str


def _record_path(a: AcquisitionAttempt) -> AcquisitionAttempt:
    """Re-record a new attempt with a repo-relative artifact path."""
    if a.artifact_path is None:
        return a
    return AcquisitionAttempt(
        source_name=a.source_name,
        url=a.url,
        outcome=a.outcome,
        failure_mode=a.failure_mode,
        affected_gate=a.affected_gate,
        consequence=a.consequence,
        attempted_at=a.attempted_at,
        artifact_path=_repo_relative(a.artifact_path),
        artifact_bytes=a.artifact_bytes,
        artifact_sha256=a.artifact_sha256,
    )

DATA_RAW = ROOT / "data" / "raw"
EVIDENCE = DATA_RAW / "acquisition_attempts.json"

WB_AMRUT_RELEASE = (
    "https://github.com/yashveeeeeeer/india-geodata/releases/tag/water/urban-water"
)
COPERNICUS_STAC = (
    "https://planetarycomputer.microsoft.com/api/stac/v1/collections/cop-dem-glo-30"
)

CONSEQUENCE_VALIDATION_PENDING = (
    "artifact available in canonical raw location; still requires the M10 "
    "validation/audit pipelines before any VALIDATED claim"
)


def supplied_attempts() -> list[AcquisitionAttempt]:
    return [
        verify_local_artifact(
            source_name="WB AMRUT Stormwater drains (india-geodata release water/urban-water; human-supplied)",
            url=WB_AMRUT_RELEASE,
            dest=DATA_RAW / "WB_AMRUT_Stormwater_drains.parquet",
            affected_gate="RD-07 (WB AMRUT artifact obtained); B02 attribute audit",
            consequence=CONSEQUENCE_VALIDATION_PENDING,
        ),
        verify_local_artifact(
            source_name="WB AMRUT Stormwater vents (india-geodata release water/urban-water; human-supplied)",
            url=WB_AMRUT_RELEASE,
            dest=DATA_RAW / "WB_AMRUT_Stormwater_vents.parquet",
            affected_gate="RD-07 (WB AMRUT artifact obtained); B02 attribute audit",
            consequence=CONSEQUENCE_VALIDATION_PENDING,
        ),
        verify_local_artifact(
            source_name="Copernicus DEM GLO-30 tile bagjola_kolkata_glo30_dem.tif (human-supplied)",
            url=COPERNICUS_STAC,
            dest=DATA_RAW / "bagjola_kolkata_glo30_dem.tif",
            affected_gate="RD-01 (pilot DEM artifact fetched)",
            consequence=CONSEQUENCE_VALIDATION_PENDING,
        ),
    ]


def main() -> int:
    prior: list[dict] = []
    if EVIDENCE.exists():
        doc = json.loads(EVIDENCE.read_text())
        prior = list(doc.get("attempts", []))
        # Normalize artifact paths to repo-relative form (portable evidence).
        for rec in prior:
            if rec.get("artifact_path") is not None:
                rec["artifact_path"] = _repo_relative(rec["artifact_path"])

    new_attempts = supplied_attempts()
    # Idempotent: skip artifacts whose verified identity is already recorded.
    already = {
        (_repo_relative(rec.get("artifact_path")), rec.get("artifact_sha256"))
        for rec in prior
        if rec.get("outcome") == "FETCHED"
    }
    new_attempts = [
        a for a in new_attempts
        if (_repo_relative(a.artifact_path), a.artifact_sha256) not in already
    ]
    combined = [_reconstruct(rec) for rec in prior] + [_record_path(a) for a in new_attempts]
    write_attempts_evidence(combined, EVIDENCE)
    for a in new_attempts:
        detail = a.failure_mode or f"{a.artifact_bytes} bytes sha256={a.artifact_sha256}"
        print(f"{a.source_name}: {a.outcome.value} ({detail})")
    print(f"evidence: {EVIDENCE} ({len(combined)} records, previous records preserved)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
