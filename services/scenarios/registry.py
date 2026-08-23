"""M5 scenario registry (M5 spec §5, §8).

Exactly four scenario classes are defined:

  S1 — Normal Rainfall + Normal Drainage
  S2 — Heavy Rainfall + Normal Drainage
  S3 — Extreme Rainfall + Normal Drainage
  S4 — Extreme Rainfall + Blocked Drainage

Comparability is enforced by construction: DEM, grid, surface parameters,
duration, coupling timestep, snapshot cadence, initial conditions and
model versions are identical across the four scenarios. S3 vs S4 differs
ONLY in the drainage condition (clean vs blocked) — the intended paired
comparison.

Every scenario defines a complete, typed ScenarioRecord with explicit
provenance, assumptions, and limitations. Scenario behaviour is NOT encoded
as undocumented conditionals inside the simulation engine.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from services.contracts import SCHEMA_VERSION
from services.scenarios.drainage import DRAINAGE_CONDITIONS, DrainageCondition
from services.scenarios.profiles import (
    D016_STATUS,
    RainfallProfileRecord,
    SEVERITY_DEFINITIONS,
    build_profile_record,
)


# ---------------------------------------------------------------------------
# Canonical M5 configuration constants (shared across all scenarios)
# ---------------------------------------------------------------------------

M5_DURATION_MINUTES = 180
M5_DT_C = 5                 # coupling stride, integer seconds (M4 default)
M5_SURFACE_SUBSTEPS = 5     # 1 s surface sub-steps (M4 default)
M5_SNAPSHOT_INTERVAL_MIN = 5
M5_EXTENT_THRESHOLD_M = 0.05  # demonstration threshold (NOT a safety threshold)
M5_SEED = 20260821
M5_ISSUE_TIME = datetime(2026, 8, 21, 0, 0, 0, tzinfo=timezone.utc)
M5_CD = 0.6
M5_AO_PER_INLET = 0.002     # m2 per inlet (ASSUMED)
M5_M_ANNING = 0.03
M5_HORTON_F0_MMH = 25.0
M5_HORTON_FMIN_MMH = 2.0
M5_HORTON_K_S1 = 1.0 / 1800.0
M5_MICROSTORE_M = 0.002
M5_SPATIAL_PATTERN = "convective_cell"


class ScenarioStatus(str, Enum):
    DEFINED = "DEFINED"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class ScenarioRecord:
    """Complete scenario definition with full provenance (M5 §5)."""

    scenario_id: str                           # "S1", "S2", "S3", "S4"
    display_name: str
    description: str
    rainfall_profile: RainfallProfileRecord
    rainfall_status: str                       # PROVISIONAL (D-016 pending)
    drainage_condition: DrainageCondition
    duration_minutes: int
    start_time: datetime
    initial_condition_policy: str
    coupling_timestep_s: int
    snapshot_interval_minutes: int
    surface_config_fingerprint: str
    swmm_fixture_fingerprint: str
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]
    provenance_note: str
    fingerprint: str
    # M4 engine parameters (needed to build RunConfig)
    manning_n: float
    horton_f0_mmh: float
    horton_fmin_mmh: float
    horton_k_s1: float
    microstore_m: float
    cd: float
    ao_per_inlet: float
    spatial_pattern: str
    extent_threshold_m: float
    seed: int
    external_inflow_m3s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "display_name": self.display_name,
            "description": self.description,
            "rainfall_profile": self.rainfall_profile.to_dict(),
            "rainfall_profile_id": self.rainfall_profile.profile_id,
            "rainfall_status": self.rainfall_status,
            "drainage_condition": self.drainage_condition.to_dict(),
            "duration_minutes": self.duration_minutes,
            "start_time": self.start_time.isoformat(),
            "initial_condition_policy": self.initial_condition_policy,
            "coupling_timestep_s": self.coupling_timestep_s,
            "snapshot_interval_minutes": self.snapshot_interval_minutes,
            "surface_config_fingerprint": self.surface_config_fingerprint,
            "swmm_fixture_fingerprint": self.swmm_fixture_fingerprint,
            "assumptions": list(self.assumptions),
            "limitations": list(self.limitations),
            "provenance": self.provenance_note,
            "fingerprint": self.fingerprint,
            "manning_n": self.manning_n,
            "horton_f0_mmh": self.horton_f0_mmh,
            "horton_fmin_mmh": self.horton_fmin_mmh,
            "horton_k_s1": self.horton_k_s1,
            "microstore_m": self.microstore_m,
            "cd": self.cd,
            "ao_per_inlet": self.ao_per_inlet,
            "spatial_pattern": self.spatial_pattern,
            "extent_threshold_m": self.extent_threshold_m,
            "seed": self.seed,
            "external_inflow_m3s": self.external_inflow_m3s,
            "schema_version": SCHEMA_VERSION,
        }


# ---------------------------------------------------------------------------
# Surface / fixture fingerprints (shared across scenarios; recomputed once)
# ---------------------------------------------------------------------------

def _surface_fingerprint() -> str:
    payload = {
        "manning_n": M5_M_ANNING,
        "alpha": 0.5, "theta": 0.8,
        "h_init": 1e-6,
        "closed_boundaries": False,
        "surface_substeps": M5_SURFACE_SUBSTEPS,
        "losses": {
            "f0_mmh": M5_HORTON_F0_MMH,
            "fmin_mmh": M5_HORTON_FMIN_MMH,
            "k_s1": M5_HORTON_K_S1,
            "microstore_m": M5_MICROSTORE_M,
            "enabled": True,
        },
        "exchange": {"cd": M5_CD, "ao_per_inlet_m2": M5_AO_PER_INLET},
    }
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


def _scenario_fingerprint(scenario_id: str, profile_id: str, profile_fp: str,
                          drainage_id: str, surface_fp: str,
                          swmm_fp: str) -> str:
    payload = {
        "scenario_id": scenario_id,
        "rainfall_profile": profile_id,
        "rainfall_profile_fingerprint": profile_fp,
        "drainage_condition": drainage_id,
        "surface_config": surface_fp,
        "swmm_fixture": swmm_fp,
        "duration_minutes": M5_DURATION_MINUTES,
        "dt_c": M5_DT_C,
        "snapshot_interval_minutes": M5_SNAPSHOT_INTERVAL_MIN,
        "extent_threshold_m": M5_EXTENT_THRESHOLD_M,
        "seed": M5_SEED,
        "schema_version": SCHEMA_VERSION,
    }
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


COMMON_ASSUMPTIONS = (
    "Synthetic 134x134 @ 30 m DEM (SYNTHETIC_LOCAL_DATUM, EPSG:32645); "
    "~4 km x 4 km domain.",
    "16 rim inlets at beds 22.10-22.30 m and one vent cell at (95,79); all "
    "SYNTHETIC/ASSUMED mapping (M4 §11).",
    f"Coupling timestep {M5_DT_C} s; Landlab OverlandFlow with "
    f"{M5_SURFACE_SUBSTEPS} sub-steps per stride (1 s effective); SWMM "
    f"dynamic-wave routing at internal 1 s step.",
    "Loss model: micro-depression store (2 mm) + per-cell Horton infiltration "
    "(f0=25, fmin=2 mm/h, k=1/1800 s^-1); all parameters PROVISIONAL.",
    "Initial state per run: surface depth = film scale, wetting clocks = 0, "
    "microstore = 0, SWMM dry, t=0; no cross-run state leakage (M4/M5-09).",
    "All rainfall fields rendered by the M2 convective-cell renderer "
    "(deterministic, seed 20260821).",
    "Coupling exchange uses the M3-validated signed head-driven orifice law "
    "(Cd=0.6, Ao=0.002 m^2/inlet ASSUMED).",
)

COMMON_LIMITATIONS = (
    "SYNTHETIC fixture — results represent NO real location or event.",
    "SIMULATED output — not a measurement; outputs must not be presented as "
    "observations or street-scale truth (30 m resolution limit).",
    f"PROVISIONAL rainfall profiles pending D-016 hydrologist review "
    f"(status: {D016_STATUS}); not for operational use.",
    "Drainage parameters (pipe sizes, orifice areas, roughness) are "
    "ASSUMED/SYNTHETIC.",
    "Single SWMM storage-exchange network; real-network geometry replaces "
    "this in the pilot phase (M10).",
)


def _build_scenarios() -> dict[str, ScenarioRecord]:
    surface_fp = _surface_fingerprint()

    p_normal = build_profile_record("P_NORMAL")
    p_heavy = build_profile_record("P_HEAVY")
    p_extreme = build_profile_record("P_EXTREME")

    d_normal = DRAINAGE_CONDITIONS["D_NORMAL"]
    d_blocked = DRAINAGE_CONDITIONS["D_BLOCKED"]

    scenarios: list[tuple[str, str, str, RainfallProfileRecord, DrainageCondition, str]] = [
        (
            "S1", "Normal Rainfall + Normal Drainage",
            "S1: Moderate 20 mm / 3 h rainfall on the clean synthetic "
            "drainage network. Establishes the no-surprise baseline.",
            p_normal, d_normal,
            "Baseline scenario: drainage in capture regime; minimal surcharge expected."
        ),
        (
            "S2", "Heavy Rainfall + Normal Drainage",
            "S2: 45 mm / 3 h convective storm on clean drainage. M4 heavy "
            "baseline reproduced for comparability.",
            p_heavy, d_normal,
            "Heavy storm on clean network: capture operates, surface ponding develops."
        ),
        (
            "S3", "Extreme Rainfall + Normal Drainage",
            "S3: 90 mm / 3 h severe event on clean drainage. Stresses the "
            "coupled system at its upper end.",
            p_extreme, d_normal,
            "Extreme storm on clean network: largest surface response with functional drainage."
        ),
        (
            "S4", "Extreme Rainfall + Blocked Drainage",
            "S4: 90 mm / 3 h severe event on the blocked conduit (C1 D=0.12 m). "
            "The S3/S4 pair isolates drainage-condition effect — identical "
            "rainfall, DEM, parameters, initial state, duration, cadence.",
            p_extreme, d_blocked,
            "Paired comparison with S3: only C1 diameter differs. Surcharge, "
            "reduced outfall, vent spill, and increased surface flooding expected."
        ),
    ]

    out: dict[str, ScenarioRecord] = {}
    for sid, name, desc, profile, drain, assumption in scenarios:
        fp = _scenario_fingerprint(sid, profile.profile_id, profile.fingerprint, drain.condition_id,
                                   surface_fp, drain.inp_fingerprint)
        out[sid] = ScenarioRecord(
            scenario_id=sid,
            display_name=name,
            description=desc,
            rainfall_profile=profile,
            rainfall_status="PROVISIONAL" if profile.review_status.value == "PROVISIONAL"
                            else profile.review_status.value,
            drainage_condition=drain,
            duration_minutes=M5_DURATION_MINUTES,
            start_time=M5_ISSUE_TIME,
            initial_condition_policy=(
                "clean state: surface depth = h_init (1e-6 m, film scale), "
                "Horton wetting clocks = 0, microstore = 0, SWMM dry at t=0; "
                "fresh model instance per scenario; no cross-run leakage."
            ),
            coupling_timestep_s=M5_DT_C,
            snapshot_interval_minutes=M5_SNAPSHOT_INTERVAL_MIN,
            surface_config_fingerprint=surface_fp,
            swmm_fixture_fingerprint=drain.inp_fingerprint,
            assumptions=(*COMMON_ASSUMPTIONS, assumption, *profile.limitations,
                         *drain.assumptions),
            limitations=COMMON_LIMITATIONS,
            provenance_note=(
                f"UFNS M5 scenario suite — synthetic fixture, deterministic "
                f"build; schema {SCHEMA_VERSION}; D-016 status {D016_STATUS}. "
                f"Rainfall: {profile.source}. Drainage: synthetic SWMM INP "
                f"(fingerprint {drain.inp_fingerprint})."
            ),
            fingerprint=fp,
            manning_n=M5_M_ANNING,
            horton_f0_mmh=M5_HORTON_F0_MMH,
            horton_fmin_mmh=M5_HORTON_FMIN_MMH,
            horton_k_s1=M5_HORTON_K_S1,
            microstore_m=M5_MICROSTORE_M,
            cd=M5_CD,
            ao_per_inlet=M5_AO_PER_INLET,
            spatial_pattern=M5_SPATIAL_PATTERN,
            extent_threshold_m=M5_EXTENT_THRESHOLD_M,
            seed=M5_SEED,
        )
    return out


M5_SCENARIOS = _build_scenarios()


def required_scenario_ids() -> tuple[str, ...]:
    return ("S1", "S2", "S3", "S4")


def get_scenario(sid: str) -> ScenarioRecord:
    if sid not in M5_SCENARIOS:
        raise KeyError(f"unknown M5 scenario id {sid!r}; known: {sorted(M5_SCENARIOS)}")
    return M5_SCENARIOS[sid]
