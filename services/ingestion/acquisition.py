"""M10 — Real-source acquisition attempts with explicit evidence capture.

Each attempt is single-shot (no retry loops): an unreachable source is
recorded once with its failure mode, the affected real-data gate, and the
consequence. The pipeline stays ready to accept the artifact when a human
supplies it or a different environment can reach the source.

Evidence records never upgrade a gate: only FETCHED outcomes carry artifact
identity (path/size/SHA-256), and a FETCHED artifact still has to pass the
validation/audit pipelines before any VALIDATED claim is made.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from services.ingestion.provenance import sha256_file
from services.ingestion.real_data import AcquisitionAttempt, AcquisitionOutcome

WB_AMRUT_DRAINS_URL = (
    "https://github.com/yashveeeeeeer/india-geodata/releases/download/"
    "water/urban-water/WB_AMRUT_Stormwater_drains.parquet"
)
COPERNICUS_DEM_STAC_URL = (
    "https://planetarycomputer.microsoft.com/api/stac/v1/collections/cop-dem-glo-30"
)


def _failure_mode(exc: Exception) -> str:
    if isinstance(exc, HTTPError):
        return f"HTTP {exc.code} {exc.reason}"
    if isinstance(exc, URLError):
        reason = exc.reason
        return f"URLError: {reason}" if not isinstance(reason, Exception) else f"URLError: {type(reason).__name__}: {reason}"
    return f"{type(exc).__name__}: {exc}"


MAX_ARTIFACT_BYTES: int = 250 * 1024 * 1024  # 250 MB


def attempt_download(
    *,
    source_name: str,
    url: str,
    dest: Path,
    affected_gate: str,
    consequence: str,
    timeout_s: float = 20.0,
    max_bytes: int = MAX_ARTIFACT_BYTES,
) -> AcquisitionAttempt:
    """Attempt one download; return the evidence record either way."""
    tmp = dest.with_name(dest.name + ".tmp")
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        total_written = 0
        with urlopen(url, timeout=timeout_s) as response:
            with open(tmp, "wb") as f:
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    total_written += len(chunk)
                    if total_written > max_bytes:
                        raise ValueError(
                            f"download exceeded maximum allowed size of {max_bytes} bytes"
                        )
                    f.write(chunk)
        tmp.replace(dest)
        artifact_bytes = dest.stat().st_size
        digest = sha256_file(dest)
    except Exception as exc:  # noqa: BLE001
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        return AcquisitionAttempt(
            source_name=source_name,
            url=url,
            outcome=AcquisitionOutcome.BLOCKED,
            failure_mode=_failure_mode(exc),
            affected_gate=affected_gate,
            consequence=consequence,
        )

    return AcquisitionAttempt(
        source_name=source_name,
        url=url,
        outcome=AcquisitionOutcome.FETCHED,
        affected_gate=affected_gate,
        consequence="artifact downloaded; still requires validation before any VALIDATED claim",
        artifact_path=str(dest),
        artifact_bytes=artifact_bytes,
        artifact_sha256=digest,
    )


def verify_local_artifact(
    *,
    source_name: str,
    url: str,
    dest: Path,
    affected_gate: str,
    consequence: str,
) -> AcquisitionAttempt:
    """Record provenance for an artifact already present at ``dest``.

    Used when a human supplies the artifact outside the sandbox (in-sandbox
    download blocked). Verifies the file exists and captures its identity
    (path, bytes, SHA-256) — never re-downloads and never assumes contents.
    A missing file yields a BLOCKED record, not a FETCHED one.
    """
    if not dest.exists():
        return AcquisitionAttempt(
            source_name=source_name,
            url=url,
            outcome=AcquisitionOutcome.BLOCKED,
            failure_mode=f"artifact not present at {dest}",
            affected_gate=affected_gate,
            consequence=consequence,
        )
    return AcquisitionAttempt(
        source_name=source_name,
        url=url,
        outcome=AcquisitionOutcome.FETCHED,
        affected_gate=affected_gate,
        consequence=consequence,
        artifact_path=str(dest),
        artifact_bytes=dest.stat().st_size,
        artifact_sha256=sha256_file(dest),
    )


def attempt_wb_amrut_drains(data_dir: Path) -> AcquisitionAttempt:
    """Single attempt to obtain the actual WB AMRUT drains parquet (B02)."""
    return attempt_download(
        source_name="WB AMRUT Stormwater drains (india-geodata release water/urban-water)",
        url=WB_AMRUT_DRAINS_URL,
        dest=data_dir / "WB_AMRUT_Stormwater_drains.parquet",
        affected_gate="RD-07 (WB AMRUT artifact obtained); B02 attribute audit",
        consequence=(
            "real drainage ingestion/audit/entity mapping remain NOT_FETCHED; "
            "synthetic drainage fixture remains the authoritative test asset"
        ),
    )


def attempt_copernicus_dem(data_dir: Path) -> AcquisitionAttempt:
    """Single attempt to reach the Copernicus DEM GLO-30 STAC collection."""
    return attempt_download(
        source_name="Copernicus DEM GLO-30 (Planetary Computer STAC collection)",
        url=COPERNICUS_DEM_STAC_URL,
        dest=data_dir / "cop-dem-glo-30-stac-collection.json",
        affected_gate="RD-01 (pilot DEM artifact fetched)",
        consequence=(
            "real DEM ingestion/normalization remain NOT_FETCHED; "
            "synthetic DEM fixture remains the authoritative test asset"
        ),
    )


def write_attempts_evidence(attempts: list[AcquisitionAttempt], out_path: Path) -> Path:
    doc: dict[str, Any] = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "note": (
            "Single-shot acquisition evidence. BLOCKED outcomes keep M10 real-data "
            "gates NOT_FETCHED/BLOCKED; they never justify a VALIDATED claim."
        ),
        "attempts": [a.to_dict() for a in attempts],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(doc, indent=2, sort_keys=False))
    return out_path
