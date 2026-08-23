"""M10 — Attempt real-pilot data acquisition once, recording evidence.

Attempts the two documented real sources (WB AMRUT parquet, Copernicus DEM
GLO-30 STAC), each exactly once with a short timeout, and writes the
evidence record to data/raw/acquisition_attempts.json. Successful downloads
land in data/raw/ and must still pass the M10 validation/audit pipelines
before any VALIDATED claim is made.

Run: python scripts/attempt_real_data_acquisition.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.ingestion.acquisition import (
    attempt_copernicus_dem,
    attempt_wb_amrut_drains,
    write_attempts_evidence,
)

DATA_RAW = ROOT / "data" / "raw"
EVIDENCE = DATA_RAW / "acquisition_attempts.json"


def main() -> int:
    attempts = [
        attempt_wb_amrut_drains(DATA_RAW),
        attempt_copernicus_dem(DATA_RAW),
    ]
    write_attempts_evidence(attempts, EVIDENCE)
    for a in attempts:
        outcome = a.outcome.value
        detail = a.failure_mode or f"{a.artifact_bytes} bytes sha256={a.artifact_sha256}"
        print(f"{a.source_name}: {outcome} ({detail})")
    print(f"evidence: {EVIDENCE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
