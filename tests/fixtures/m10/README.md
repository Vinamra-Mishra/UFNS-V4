# M10 Test Fixtures — SYNTHETIC TEST FIXTURE

Everything produced by the generators in this package is **SYNTHETIC TEST
FIXTURE** data (`DataSourceClassification.FIXTURE`). No file generated here
is real-world data, and none may ever be labelled `REAL_DATA`.

Purpose: exercise the M10 real-data ingestion **machinery** (validation,
normalization, audit, mapping, provenance) deterministically and offline.
These fixtures say nothing about the actual pilot datasets, which remain
NOT_FETCHED/BLOCKED (see `data/raw/acquisition_attempts.json`).
