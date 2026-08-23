"""M5 — Scenario Engine (UFNS SIH26085).

Deterministic scenario execution on the validated M4 coupled model.
Four scenarios: S1 Normal, S2 Heavy, S3 Extreme, S4 Extreme + Blocked.

Reuse policy (M5 spec §4): the M4 scientific semantics are NOT modified.
This package provides:
  - rainfall-profile governance (profiles.py)
  - drainage-condition governance (drainage.py)
  - scenario schema + registry (registry.py)
  - scenario execution on the M4 engine (runner.py)
  - cross-scenario comparison (comparison.py)
  - visual diagnostics (diagnostics.py)
"""

MODEL_VERSION = "m5-scenario-engine-v1"
