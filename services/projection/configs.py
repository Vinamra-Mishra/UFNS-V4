from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from services.projection import MODEL_VERSION, RAINFALL_INTERVAL_MINUTES, VALID_LEADS
from services.scenarios.drainage import DRAINAGE_CONDITIONS, DrainageCondition
from services.scenarios.registry import (
    M5_AO_PER_INLET,
    M5_CD,
    M5_DT_C,
    M5_EXTENT_THRESHOLD_M,
    M5_HORTON_F0_MMH,
    M5_HORTON_FMIN_MMH,
    M5_HORTON_K_S1,
    M5_M_ANNING,
    M5_MICROSTORE_M,
    M5_SEED,
)


@dataclass(frozen=True)
class ProjectionConfigRecord:
    """Configuration for an M9 persistence-impact projection run."""

    config_id: str
    display_name: str
    description: str
    drainage_condition: DrainageCondition
    base_scenarios: tuple[str, ...]
    duration_minutes: int
    lead_times_minutes: tuple[int, ...]
    rainfall_interval_minutes: int
    snapshot_interval_minutes: int
    coupling_timestep_s: int
    extent_threshold_m: float
    manning_n: float
    horton_f0_mmh: float
    horton_fmin_mmh: float
    horton_k_s1: float
    microstore_m: float
    cd: float
    ao_per_inlet: float
    seed: int
    status: str
    labels: tuple[str, ...]
    fingerprint: str = ""

    def __post_init__(self) -> None:
        payload = {
            "config_id": self.config_id,
            "base_scenarios": list(self.base_scenarios),
            "drainage_condition": self.drainage_condition.condition_id,
            "drainage_fingerprint": self.drainage_condition.inp_fingerprint,
            "duration_minutes": self.duration_minutes,
            "lead_times_minutes": list(self.lead_times_minutes),
            "rainfall_interval_minutes": self.rainfall_interval_minutes,
            "snapshot_interval_minutes": self.snapshot_interval_minutes,
            "coupling_timestep_s": self.coupling_timestep_s,
            "extent_threshold_m": self.extent_threshold_m,
            "manning_n": self.manning_n,
            "horton_f0_mmh": self.horton_f0_mmh,
            "horton_fmin_mmh": self.horton_fmin_mmh,
            "horton_k_s1": self.horton_k_s1,
            "microstore_m": self.microstore_m,
            "cd": self.cd,
            "ao_per_inlet": self.ao_per_inlet,
            "seed": self.seed,
            "model_version": MODEL_VERSION,
        }
        canon = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        fp = hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]
        object.__setattr__(self, "fingerprint", fp)

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_id": self.config_id,
            "display_name": self.display_name,
            "description": self.description,
            "drainage_condition": self.drainage_condition.to_dict(),
            "base_scenarios": list(self.base_scenarios),
            "duration_minutes": self.duration_minutes,
            "lead_times_minutes": list(self.lead_times_minutes),
            "rainfall_interval_minutes": self.rainfall_interval_minutes,
            "snapshot_interval_minutes": self.snapshot_interval_minutes,
            "coupling_timestep_s": self.coupling_timestep_s,
            "extent_threshold_m": self.extent_threshold_m,
            "manning_n": self.manning_n,
            "horton_f0_mmh": self.horton_f0_mmh,
            "horton_fmin_mmh": self.horton_fmin_mmh,
            "horton_k_s1": self.horton_k_s1,
            "microstore_m": self.microstore_m,
            "cd": self.cd,
            "ao_per_inlet": self.ao_per_inlet,
            "seed": self.seed,
            "status": self.status,
            "labels": list(self.labels),
            "fingerprint": self.fingerprint,
        }


PROJECTION_CONFIGS: dict[str, ProjectionConfigRecord] = {
    "P_NORMAL": ProjectionConfigRecord(
        config_id="P_NORMAL",
        display_name="Persistence projection — normal drainage",
        description=(
            "Persistence-based flood impact projection using the active M8 rainfall "
            "observation/nowcast and the clean synthetic drainage fixture."
        ),
        drainage_condition=DRAINAGE_CONDITIONS["D_NORMAL"],
        base_scenarios=("S1", "S2", "S3"),
        duration_minutes=VALID_LEADS[-1],
        lead_times_minutes=VALID_LEADS,
        rainfall_interval_minutes=RAINFALL_INTERVAL_MINUTES,
        snapshot_interval_minutes=RAINFALL_INTERVAL_MINUTES,
        coupling_timestep_s=M5_DT_C,
        extent_threshold_m=M5_EXTENT_THRESHOLD_M,
        manning_n=M5_M_ANNING,
        horton_f0_mmh=M5_HORTON_F0_MMH,
        horton_fmin_mmh=M5_HORTON_FMIN_MMH,
        horton_k_s1=M5_HORTON_K_S1,
        microstore_m=M5_MICROSTORE_M,
        cd=M5_CD,
        ao_per_inlet=M5_AO_PER_INLET,
        seed=M5_SEED,
        status="PROVISIONAL_DEMONSTRATION",
        labels=(
            "PERSISTENCE_PROJECTION",
            "SYNTHETIC",
            "SIMULATED",
            "NOT_REAL_TIME",
            "NOT_VALIDATED_FORECAST",
        ),
    ),
    "P_BLOCKED": ProjectionConfigRecord(
        config_id="P_BLOCKED",
        display_name="Persistence projection — blocked drainage",
        description=(
            "Persistence-based flood impact projection using the active M8 rainfall "
            "observation/nowcast and the blocked synthetic drainage fixture."
        ),
        drainage_condition=DRAINAGE_CONDITIONS["D_BLOCKED"],
        base_scenarios=("S4",),
        duration_minutes=VALID_LEADS[-1],
        lead_times_minutes=VALID_LEADS,
        rainfall_interval_minutes=RAINFALL_INTERVAL_MINUTES,
        snapshot_interval_minutes=RAINFALL_INTERVAL_MINUTES,
        coupling_timestep_s=M5_DT_C,
        extent_threshold_m=M5_EXTENT_THRESHOLD_M,
        manning_n=M5_M_ANNING,
        horton_f0_mmh=M5_HORTON_F0_MMH,
        horton_fmin_mmh=M5_HORTON_FMIN_MMH,
        horton_k_s1=M5_HORTON_K_S1,
        microstore_m=M5_MICROSTORE_M,
        cd=M5_CD,
        ao_per_inlet=M5_AO_PER_INLET,
        seed=M5_SEED,
        status="PROVISIONAL_DEMONSTRATION",
        labels=(
            "PERSISTENCE_PROJECTION",
            "SYNTHETIC",
            "SIMULATED",
            "NOT_REAL_TIME",
            "NOT_VALIDATED_FORECAST",
        ),
    ),
}


def get_projection_config(config_id: str) -> ProjectionConfigRecord:
    if config_id not in PROJECTION_CONFIGS:
        raise KeyError(config_id)
    return PROJECTION_CONFIGS[config_id]
