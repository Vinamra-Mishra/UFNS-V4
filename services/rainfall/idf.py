"""D-016 — Traceable rainfall depth-duration derivation (Option A).

Resolves the D-016 review (rainfall-profile derivation) using published,
peer-reviewed Intensity-Duration-Frequency (IDF) parameters for the pilot
region (West Bengal / Kolkata), replacing the earlier provisional
"illustrative" storm totals with a deterministic, source-traceable derivation.

SOURCE (published, peer-reviewed):
    Kumar, A., & Remesan, R. (2026). "Integrating Revised
    Intensity-Duration-Frequency Curves with Coupled 1D-2D MIKE+ Modelling
    for Urban Flood Hazard Assessment Under CMIP6 Projections."
    Water Resources Management, 40(3), 115.
    DOI: 10.1007/s11269-026-04514-5

    Observed (1980-2023) rainfall-intensity values for the Bagjola Canal
    basin, Kolkata Metropolitan Area, from the IMD Alipur gauge station,
    analysed with the Generalised Extreme Value (GEV) distribution (selected
    by the authors as the most suitable via chi-square / Kolmogorov-Smirnov /
    Anderson-Darling goodness-of-fit tests). The paper tabulates 2-year and
    100-year intensities (mm/h) at durations 1, 2, 6, 12, 24, 48 h and uses
    2-, 5-, and 10-year return periods for urban-drainage design per CPHEEO
    (2019).

DERIVATION METHOD (deterministic; same inputs -> same outputs):

    1. Convert the published intensity table to depths:  D(d, T) = i(d, T) * d.

    2. Return-period scaling between the two published anchors (2-yr, 100-yr)
       using the Sherman (1931) power form  i(d, T) = i(d, 2) * (T/2)^alpha(d)
       with  alpha(d) = ln(i100 / i2) / ln(50).

    3. Duration interpolation for the 3-hour scenario duration by log-log
       (power-law) interpolation between the two bracketing published
       duration nodes (2 h and 6 h).

    4. 15-minute hyetograph by the alternating-block method (Chow, Maidment &
       Mays 1988, ch. 14) with the existing storm-shape exponent 0.4 (an
       ASSUMPTION governing intra-storm temporal shape only; the total depth
       is unaffected because the block method normalises to the target total).

Status: the derivation is SCIENTIFICALLY PREPARED but remains PROVISIONAL —
a hydrologist must approve the return-period -> scenario-label mapping and the
derived totals before any operational use. No approval is fabricated here.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any

from services.rainfall.scenarios import alternating_block_hyetograph

# ---------------------------------------------------------------------------
# Source metadata (SOURCE FACT)
# ---------------------------------------------------------------------------

SOURCE = {
    "title": (
        "Integrating Revised Intensity-Duration-Frequency Curves with Coupled "
        "1D-2D MIKE+ Modelling for Urban Flood Hazard Assessment Under CMIP6 "
        "Projections"
    ),
    "authors": ["Aman Kumar", "Renji Remesan"],
    "organization": "School of Water Resources, Indian Institute of Technology Kharagpur",
    "journal": "Water Resources Management",
    "volume_issue_article": "40(3), 115",
    "publication_date": "2026-02-12",
    "doi": "10.1007/s11269-026-04514-5",
    "url": "https://doi.org/10.1007/s11269-026-04514-5",
    "gauge_station": "IMD Alipur",
    "record_period": "1980-2023",
    "geographic_applicability": "Bagjola Canal basin, Kolkata Metropolitan Area (West Bengal, India)",
    "distribution": "Generalized Extreme Value (GEV)",
    "return_periods_used_by_source": [2, 5, 10],
    "licence_note": "Subscription article; values transcribed from the published text. "
                    "Re-verify against the full text before operational adoption.",
}

# Published GEV intensities (mm/h) at 2-year and 100-year return periods.
# Durations are in hours. (SOURCE FACT — transcribed verbatim from the paper.)
PUBLISHED_DURATIONS_H: tuple[float, ...] = (1.0, 2.0, 6.0, 12.0, 24.0, 48.0)
PUBLISHED_INTENSITY_2YR: tuple[float, ...] = (45.05, 28.40, 18.05, 12.15, 7.90, 5.30)
PUBLISHED_INTENSITY_100YR: tuple[float, ...] = (105.20, 66.27, 45.24, 28.70, 18.22, 12.03)

# ---------------------------------------------------------------------------
# Scenario mapping recommendation (AI INFERENCE -> HUMAN DECISION)
# ---------------------------------------------------------------------------
# The demo scenario labels (NORMAL / HEAVY / EXTREME) are NOT automatically
# equated to return periods. The recommended mapping follows the return
# periods the source itself uses for urban-drainage design (2 / 5 / 10-year,
# per CPHEEO 2019). This mapping is a HUMAN DECISION; it is recorded here as a
# recommendation only until a hydrologist approves it.

INTERVAL_MINUTES = 15
DURATION_MINUTES = 180
STORM_SHAPE_EXPONENT = 0.4   # ASSUMED intra-storm shape (Chow 1988)

RECOMMENDED_SCENARIO_MAPPING: dict[str, dict[str, Any]] = {
    "NORMAL": {"return_period_yr": 2, "rationale": "frequent design storm (minor drainage, CPHEEO 2019)"},
    "HEAVY":  {"return_period_yr": 5, "rationale": "intermediate design storm (minor drainage, CPHEEO 2019)"},
    "EXTREME": {"return_period_yr": 10, "rationale": "major drainage design storm (CPHEEO 2019)"},
}


# ---------------------------------------------------------------------------
# Derivation functions (deterministic)
# ---------------------------------------------------------------------------

def _alpha(duration_h: float) -> float:
    """Sherman return-period exponent for a published duration node."""
    k = PUBLISHED_DURATIONS_H.index(duration_h)
    return math.log(PUBLISHED_INTENSITY_100YR[k] / PUBLISHED_INTENSITY_2YR[k]) / math.log(50.0)


def intensity_mmh(duration_h: float, return_period_yr: float) -> float:
    """Deterministic GEV-based rainfall intensity (mm/h) for a duration (h)
    and return period (yr).

    Return periods < 2 years are not supported by the source (annual-maxima
    series); the function clamps to the 2-year anchor with an explicit flag
    rather than silently extrapolating below the source's range.
    """
    if return_period_yr < 2.0:
        raise ValueError("return period < 2 years is outside the source's annual-maxima range")
    # Duration interpolation via log-log depth interpolation between the
    # bracketing published nodes.
    return depth_mm(duration_h, return_period_yr) / duration_h


def depth_mm(duration_h: float, return_period_yr: float) -> float:
    """Deterministic GEV-based rainfall depth (mm) for a duration (h) and
    return period (yr)."""
    if duration_h <= 0:
        raise ValueError("duration must be positive")
    if return_period_yr < 2.0:
        raise ValueError("return period < 2 years is outside the source's annual-maxima range")

    def _node_depth(d: float) -> float:
        k = PUBLISHED_DURATIONS_H.index(d)
        i = PUBLISHED_INTENSITY_2YR[k] * (return_period_yr / 2.0) ** _alpha(d)
        return i * d

    if duration_h in PUBLISHED_DURATIONS_H:
        return _node_depth(duration_h)
    if duration_h < PUBLISHED_DURATIONS_H[0]:
        # Below the shortest published duration: assume constant intensity
        # (extrapolation; flagged as an assumption, not used for 3 h here).
        return _node_depth(PUBLISHED_DURATIONS_H[0]) / PUBLISHED_DURATIONS_H[0] * duration_h
    if duration_h > PUBLISHED_DURATIONS_H[-1]:
        return _node_depth(PUBLISHED_DURATIONS_H[-1]) / PUBLISHED_DURATIONS_H[-1] * duration_h
    for k in range(len(PUBLISHED_DURATIONS_H) - 1):
        d0, d1 = PUBLISHED_DURATIONS_H[k], PUBLISHED_DURATIONS_H[k + 1]
        if d0 < duration_h < d1:
            D0 = _node_depth(d0)
            D1 = _node_depth(d1)
            frac = (math.log(duration_h) - math.log(d0)) / (math.log(d1) - math.log(d0))
            return math.exp(math.log(D0) + (math.log(D1) - math.log(D0)) * frac)
    raise ValueError(f"duration {duration_h} h could not be interpolated")


def derived_scenario_depths_mm(round_ndigits: int = 2) -> dict[str, float]:
    """Source-derived 3-hour storm totals for the three demo severities.

    Rounding rule: totals are rounded to `round_ndigits` decimals (0.01 mm)
    for presentation; the alternating-block hyetograph is then normalised to
    the rounded total so the 15-minute series sums exactly.
    """
    out: dict[str, float] = {}
    for sev, cfg in RECOMMENDED_SCENARIO_MAPPING.items():
        out[sev] = round(depth_mm(DURATION_MINUTES / 60.0, cfg["return_period_yr"]), round_ndigits)
    return out


def derived_hyetographs_mmh() -> dict[str, tuple[float, ...]]:
    """Alternating-block 15-minute hyetographs (mm/h) for the source-derived
    scenario totals. Deterministic; each series sums to its rounded total."""
    depths = derived_scenario_depths_mm()
    return {
        sev: tuple(
            alternating_block_hyetograph(
                depths[sev], DURATION_MINUTES, INTERVAL_MINUTES, exponent=STORM_SHAPE_EXPONENT
            )
        )
        for sev in depths
    }


def derivation_fingerprint() -> str:
    """Deterministic fingerprint of the source parameters and derivation.

    Changing any published anchor, duration node, mapping, or exponent changes
    the fingerprint. Used to prove the derivation inputs are recorded and
    stable.
    """
    payload = {
        "source_doi": SOURCE["doi"],
        "durations_h": list(PUBLISHED_DURATIONS_H),
        "intensity_2yr": list(PUBLISHED_INTENSITY_2YR),
        "intensity_100yr": list(PUBLISHED_INTENSITY_100YR),
        "mapping": {
            k: v["return_period_yr"] for k, v in sorted(RECOMMENDED_SCENARIO_MAPPING.items())
        },
        "interval_minutes": INTERVAL_MINUTES,
        "duration_minutes": DURATION_MINUTES,
        "storm_shape_exponent": STORM_SHAPE_EXPONENT,
    }
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


# Precomputed (import-time) derived values for convenience and for the tests.
DERIVED_DEPTHS_MM = derived_scenario_depths_mm()
DERIVED_HYETOGRAPHS_MMH = derived_hyetographs_mmh()
