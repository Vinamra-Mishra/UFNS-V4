#!/usr/bin/env python3
"""M6 dashboard/API launcher (UFNS SIH26085).

Serves the scenario-inspection dashboard and the versioned JSON/artifact API
from the precomputed M5 results (no simulation re-run). Usage:

    python3 scripts/run_dashboard.py            # http://127.0.0.1:8000

Environment (see .env.example): UFNS_API_HOST, UFNS_API_PORT.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn  # noqa: E402

from apps.api.app import app  # noqa: E402


def main() -> None:
    host = os.environ.get("UFNS_API_HOST", "127.0.0.1")
    port = int(os.environ.get("UFNS_API_PORT", "8000"))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
