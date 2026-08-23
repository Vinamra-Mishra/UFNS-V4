"""Demo scenario definitions (IMPLEMENTATION_SPEC §7, §13 M5).

DERIVATION (B03 / D-016 — provisional, pending hydrologist approval):
The four demo hyetographs are built with the alternating-block method
(Chow, Maidment & Mays, "Applied Hydrology", 1988, ch. 14), the standard
synthetic-storm construction from a depth–duration relationship. Provisional
depth–duration relationship for this fixture:

    P(d) = P60 * (d / 60)^0.4 ,  P60 = total 1-hour depth (mm)

with provisional storm totals per scenario. Exponent 0.4 and the totals are
PROVISIONAL illustrative parameters for fixture/contract testing only.
Before M5 scenario acceptance, the human team must approve final parameters
derived from published IDF curves for the pilot region (candidate: Kumar &
Remesan 2026, Bagjola Canal basin / Kolkata IDF study) or a documented
historical event (D-016). Nothing here claims to be a calibrated design storm.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from services.contracts import (
    BlockageConfiguration,
    DataLineage,
    DrainageConfiguration,
    GridSpec,
    ProvenanceClass,
    QualityFlag,
    RainfallProfile,
    ScenarioDefinition,
    SurfaceParameters,
)

DERIVATION_NOTE = (
    "Alternating-block method (Chow et al. 1988) from provisional depth-duration "
    "P(d)=P60*(d/60)^0.4. PROVISIONAL: final M5 parameters require published pilot-region "
    "IDF or documented historical event with hydrologist approval (D-016)."
)

INTERVAL_MINUTES = 15
DURATION_MINUTES = 180
PROVISIONAL_TOTALS_MM = {
    "normal": 20.0,
    "heavy": 45.0,
    "extreme": 90.0,
}


def alternating_block_hyetograph(total_mm: float, duration_min: int, interval_min: int, exponent: float = 0.4) -> list[float]:
    """Standard alternating-block construction (Chow et al. 1988).

    Incremental depths are computed from the depth-duration curve, then the
    largest increment is placed at mid-storm and the rest alternate outward.
    Returns per-interval intensities in mm/h.
    """
    if duration_min <= 0:
        raise ValueError(f"duration_min must be positive, got {duration_min}")
    if interval_min <= 0:
        raise ValueError(f"interval_min must be positive, got {interval_min}")
    if duration_min % interval_min != 0:
        raise ValueError(
            f"duration_min ({duration_min}) must be exactly divisible by interval_min ({interval_min})"
        )
    n = duration_min // interval_min
    if n < 2:
        raise ValueError("duration must cover at least two intervals")
    durations = np.arange(1, n + 1) * interval_min
    p60 = total_mm / (60 ** exponent)  # P(60min) consistent with the chosen total... see note
    # NOTE: provisional parametrization anchors the depth-duration curve so that
    # the storm total equals `total_mm` over `duration_min`. Documented deviation
    # from strict P60 anchoring; flagged PROVISIONAL (see module docstring).
    p_dur = p60 * (durations ** exponent)
    p_dur = p_dur * (total_mm / p_dur[-1])  # normalize to exact storm total
    increments = np.diff(np.concatenate([[0.0], p_dur]))
    order = [0] * n
    mid = n // 2
    order[mid] = int(np.argmax(increments))
    idx = 1
    left, right = mid - 1, mid + 1
    remaining = np.argsort(increments)[::-1][1:]
    for k in remaining:
        if left >= 0 and right < n:
            if idx % 2 == 1:
                order[left] = k
                left -= 1
            else:
                order[right] = k
                right += 1
            idx += 1
        elif left >= 0:
            order[left] = k
            left -= 1
        else:
            order[right] = k
            right += 1
    intensity = increments[order] / (interval_min / 60.0)
    return [float(x) for x in intensity]


def build_profile(scenario_id: str, total_mm: float) -> RainfallProfile:
    return RainfallProfile(
        profile_id=f"{scenario_id}_v1",
        derivation=DERIVATION_NOTE,
        review_status="PROVISIONAL",
        interval_minutes=INTERVAL_MINUTES,
        intensities_mmh=alternating_block_hyetograph(total_mm, DURATION_MINUTES, INTERVAL_MINUTES),
    )


def build_demo_scenarios(
    grid: GridSpec,
    dem_asset_uri: str,
    network_asset_uri: str,
    issue_time: datetime,
    lineage: DataLineage,
) -> list[ScenarioDefinition]:
    """The four approved demo scenarios (M5 preview; provisional rainfall)."""

    def _scenario(scenario_id: str, name: str, description: str, blockage: BlockageConfiguration | None) -> ScenarioDefinition:
        return ScenarioDefinition(
            scenario_id=scenario_id,
            name=name,
            description=description,
            rainfall_source="demo",
            rainfall_profile=build_profile(scenario_id, PROVISIONAL_TOTALS_MM[scenario_id.split("_")[0]]),
            spatial_pattern="convective_cell",
            duration_minutes=DURATION_MINUTES,
            issue_time=issue_time,
            initial_conditions={"surface_depth_m": 0.0},
            drainage_configuration=DrainageConfiguration(
                network_asset_uri=network_asset_uri,
                parameter_status={"all": "assumed"},  # synthetic fixture network
                blockage=blockage,
            ),
            surface_parameters=SurfaceParameters(
                manning_n=0.03,
                horton_f0_m_s=25.0 / (1000.0 * 3600.0),
                horton_fmin_m_s=2.0 / (1000.0 * 3600.0),
                horton_k_s1=1.0 / 1800.0,
                depression_storage_m=0.002,
                review_status="PROVISIONAL",
            ),
            simulation_grid=grid,
            simulation_timestep_s=None,  # solver-adaptive
            random_seed=20260821,
            provenance=lineage,
        )

    extreme_blockage = BlockageConfiguration(
        blocked_links=["C4", "C9"],  # fixture conduit IDs (documented in fixture design)
        fraction=1.0,
        start_minutes=60,
        end_minutes=None,
    )
    return [
        _scenario("normal", "Normal rainfall", "Provisional normal rainfall event (20 mm/3 h).", None),
        _scenario("heavy", "Heavy rainfall", "Provisional heavy rainfall event (45 mm/3 h).", None),
        _scenario("extreme", "Extreme rainfall", "Provisional extreme rainfall event (90 mm/3 h).", None),
        _scenario(
            "extreme_blockage",
            "Extreme rainfall + drainage blockage",
            "Extreme event with 100% blockage of fixture conduits C4/C9 from t+60 min. "
            "Primary demonstration of drainage–rainfall coupling.",
            extreme_blockage,
        ),
    ]
