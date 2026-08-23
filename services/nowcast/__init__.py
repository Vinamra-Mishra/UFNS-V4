"""M8 — Rainfall Ingestion + Nowcasting (UFNS), NOT_REAL_TIME demonstration.

This package provides:
  - A provider-independent rainfall ingestion interface (providers/)
  - Data-quality validation and freshness gating (quality.py)
  - A persistence-baseline nowcast engine (engine.py)
  - A typed nowcast record contract (nowcast_record.py)
  - Caching support for rainfall observations and forecasts (cache.py)
  - Verification metrics framework (verification.py)

Governance (UFNS M8 non-negotiable rules):
  - No fabricated data. No fabricated API responses. No fabricated forecasts.
  - Every observation carries provenance and a source_type label.
  - Every forecast identifies its source, method, status, and fingerprint.
  - Synthetic data is NEVER silently substituted for missing real data.
  - Real-time components fail safely and visibly when data is unavailable.
  - No fake "LIVE" badge. No fake forecast confidence.

Maturity: LEVEL 1 — DEMONSTRATION PROTOTYPE.
"""

NOWCAST_VERSION = "m8-nowcast-v1"
NOWCAST_METHOD_PERSISTENCE = "NOWCAST-PERSISTENCE-V1"
